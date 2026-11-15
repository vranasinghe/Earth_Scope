"""Google Gemini provider (official ``google-genai`` SDK), used only by the FastAPI backend.

* The SDK is imported lazily, so the rest of Earth Scope runs even if it is not installed.
* The API key comes from Settings (environment / backend/.env) and never leaves this module.
* SDK-level automatic retries are disabled (``attempts=1``). Instead the provider ROTATES between
  models: a model that is exhausted (429 RESOURCE_EXHAUSTED), unavailable (503/404) or timed out
  rests for a cool-down (Google's own retry delay when it gives one) and the next model is tried;
  rested models rejoin the rotation automatically. Failed calls produce no answer, so one user
  message still yields at most one billable answer (the model list is fetched once per 6 h).
* Provider errors are mapped to friendly AI errors; their text is never shown to users or logged.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

from app.ai.errors import (
    NOT_CONFIGURED_MESSAGE,
    UNAVAILABLE_MESSAGE,
    AiBadResponseError,
    AiConfigurationError,
    AiNotConfiguredError,
    AiQuotaExceededError,
    AiTimeoutError,
    AiUnavailableError,
)
from app.core.config import Settings

logger = logging.getLogger("earthscope.ai")

MODEL_CACHE_SECONDS = 6 * 3600
MODEL_COOLDOWN_SECONDS = 600         # unavailable (503/404) or timed-out model rests this long
QUOTA_COOLDOWN_SECONDS = 60          # exhausted model without a retry delay from Google (per-minute quotas)
DAILY_QUOTA_COOLDOWN_SECONDS = 3600  # exhausted daily quota: re-check hourly (it resets once a day)
MAX_QUOTA_COOLDOWN_SECONDS = 24 * 3600
_EXCLUDED_MODEL_WORDS = ("lite", "image", "tts", "live", "audio", "embedding", "exp", "thinking", "computer",
                         "robotics", "native", "learnlm", "veo", "imagen", "aqa")


@dataclass
class GeminiResult:
    text: str
    model: str
    usage: dict[str, int] | None


def sdk_installed() -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec("google.genai") is not None
    except Exception:  # noqa: BLE001 - a broken install: report "not configured"
        return False


def availability(settings: Settings) -> tuple[bool, str]:
    """(usable, reason) without contacting Google."""
    if not settings.gemini_chat_enabled:
        return False, "disabled"
    if not settings.gemini_api_key.get_secret_value().strip():
        return False, "missing_api_key"
    if not sdk_installed():
        return False, "sdk_not_installed"
    return True, "ok"


def _make_client(settings: Settings) -> Any:
    from google import genai
    from google.genai import types

    return genai.Client(
        api_key=settings.gemini_api_key.get_secret_value().strip(),
        http_options=types.HttpOptions(
            timeout=int(settings.gemini_timeout_seconds * 1000),
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )


def _version_key(name: str) -> tuple[float, int]:
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    return (float(m.group(1)) if m else 0.0, -len(name))


def rank_models(names: list[str]) -> list[str]:
    """General text models from a model list, best first: newest 'flash', stable before preview, alias before pinned."""
    cand = [n for n in names if "flash" in n and not any(w in n for w in _EXCLUDED_MODEL_WORDS)]
    stable = [n for n in cand if "preview" not in n] or cand
    return sorted(set(stable), key=_version_key, reverse=True)


def pick_model(names: list[str]) -> str | None:
    ranked = rank_models(names)
    return ranked[0] if ranked else None


def _api_error(exc: Exception) -> tuple[int, str] | None:
    try:
        from google.genai import errors as gerr
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(exc, gerr.APIError):
        return None
    return int(getattr(exc, "code", 0) or 0), str(getattr(exc, "status", "") or "")


def _is_exhausted(exc: Exception) -> bool:
    """The model's quota is used up (per minute / per day / tokens): try another model."""
    e = _api_error(exc)
    return e is not None and (e[0] == 429 or e[1] == "RESOURCE_EXHAUSTED")


def _is_model_unavailable(exc: Exception) -> bool:
    """This model cannot serve right now (overloaded / not available to the key): try another model."""
    e = _api_error(exc)
    return e is not None and (e[0] in (404, 503) or e[1] in ("NOT_FOUND", "UNAVAILABLE"))


def _is_model_slow(exc: Exception) -> bool:
    """The provider gave up on this model (504 / DEADLINE_EXCEEDED): rest it, but do not retry in the
    same request (that would double an already long wait)."""
    e = _api_error(exc)
    return e is not None and (e[0] == 504 or e[1] == "DEADLINE_EXCEEDED")


def _duration_seconds(value: Any) -> float | None:
    """google.protobuf.Duration as JSON ("37s", "1.5s") or {"seconds": 37}."""
    if isinstance(value, dict):
        try:
            return float(value.get("seconds", 0)) + float(value.get("nanos", 0)) / 1e9
        except (TypeError, ValueError):
            return None
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)s\s*", str(value or ""))
    return float(m.group(1)) if m else None


def quota_cooldown_seconds(exc: Exception) -> float:
    """How long an exhausted model rests: Google's RetryInfo delay when present, at least an hour for
    daily quotas, otherwise one minute (the usual per-minute quota window)."""
    details = getattr(exc, "details", None)
    err = details.get("error", details) if isinstance(details, dict) else {}
    items = err.get("details") if isinstance(err, dict) else None
    delay: float | None = None
    daily = False
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        if "retryDelay" in item:
            delay = _duration_seconds(item.get("retryDelay"))
        for v in item.get("violations") or []:
            if isinstance(v, dict) and "perday" in str(v.get("quotaId", "")).replace("_", "").lower():
                daily = True
    if daily and (delay is None or delay < DAILY_QUOTA_COOLDOWN_SECONDS):
        return float(DAILY_QUOTA_COOLDOWN_SECONDS)
    if delay is not None:
        return float(min(max(delay, 1.0), MAX_QUOTA_COOLDOWN_SECONDS))
    return float(QUOTA_COOLDOWN_SECONDS)


def _is_thinking_model(model: str) -> bool:
    return bool(re.search(r"gemini-(2\.5|[3-9])", model))


def _thinking_config(model: str) -> Any:
    """Keep 'thinking' minimal. Thinking tokens count against max_output_tokens, so with "low"
    thinking a Gemini 3 model could spend most of the budget thinking and cut the answer short
    (seen live: up to 819 thought tokens of a 1200-token budget). Minimal = no thoughts, faster."""
    from google.genai import types

    if re.search(r"gemini-2\.5-flash", model):
        return types.ThinkingConfig(thinking_budget=0)
    if re.search(r"gemini-[3-9]", model):
        return types.ThinkingConfig(thinking_level="minimal")
    return None


def output_token_limit(model: str, settings: Settings) -> int:
    """GEMINI_MAX_OUTPUT_TOKENS is the budget for the ANSWER; thinking models get an extra reserve
    so any thinking they still do can never eat into it."""
    reserve = settings.gemini_thinking_reserve_tokens if _is_thinking_model(model) else 0
    return settings.gemini_max_output_tokens + reserve


TRUNCATED_NOTE = "\n\n*(My answer was cut short. Ask me to continue, or ask a narrower question.)*"


def _map_error(exc: Exception) -> Exception:
    """Translate SDK / transport exceptions to AI errors (without leaking provider text)."""
    try:
        from google.genai import errors as gerr
    except Exception:  # noqa: BLE001
        gerr = None
    name = type(exc).__name__
    if gerr is not None and isinstance(exc, gerr.APIError):
        code = int(getattr(exc, "code", 0) or 0)
        status = str(getattr(exc, "status", "") or "")
        logger.warning("gemini api error code=%s status=%s", code, status)
        if code == 429 or status == "RESOURCE_EXHAUSTED":
            return AiQuotaExceededError("The AI Assistant has reached its usage limit for now. Please try again later.")
        if code in (401, 403) or (code == 400 and "API_KEY" in status.upper()):
            return AiConfigurationError("The AI Assistant is not configured correctly (the Gemini API key was rejected).")
        if code == 400 and "api key" in str(getattr(exc, "message", "")).lower():
            return AiConfigurationError("The AI Assistant is not configured correctly (the Gemini API key was rejected).")
        if code == 404:
            return AiConfigurationError("The configured Gemini model is not available to this API key. Check GEMINI_MODEL.")
        if code == 408 or code == 504:
            return AiTimeoutError("The AI Assistant took too long to answer. Please try again.")
        return AiUnavailableError(UNAVAILABLE_MESSAGE)
    if "Timeout" in name or isinstance(exc, TimeoutError):
        logger.warning("gemini timeout (%s)", name)
        return AiTimeoutError("The AI Assistant took too long to answer. Please try again.")
    logger.warning("gemini transport failure (%s)", name)
    return AiUnavailableError(UNAVAILABLE_MESSAGE)


class GeminiProvider:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: Any = None
        self._lock = threading.Lock()
        self._auto_models: tuple[float, list[str]] | None = None
        self._cooldown: dict[str, float] = {}

    def _get_client(self) -> Any:
        ok, reason = availability(self.settings)
        if not ok:
            raise AiNotConfiguredError(NOT_CONFIGURED_MESSAGE, [reason])
        with self._lock:
            if self._client is None:
                self._client = _make_client(self.settings)
            return self._client

    def _available_models(self) -> list[str]:
        """The key's general text models, best first (cached for 6 h)."""
        with self._lock:
            cached = self._auto_models
        if cached is None or time.monotonic() - cached[0] >= MODEL_CACHE_SECONDS:
            client = self._get_client()
            try:
                names = []
                for m in client.models.list():
                    actions = getattr(m, "supported_actions", None) or []
                    if actions and "generateContent" not in actions:
                        continue
                    names.append(str(getattr(m, "name", "") or "").removeprefix("models/"))
            except Exception as exc:  # noqa: BLE001
                raise _map_error(exc) from None
            cached = (time.monotonic(), rank_models(names))
            with self._lock:
                self._auto_models = cached
            logger.info("gemini models available for rotation: %s", ", ".join(cached[1][:8]) or "(none)")
        return cached[1]

    def rotation(self) -> list[str]:
        """Full model rotation in preference order: GEMINI_MODEL (if set) first, then
        GEMINI_FALLBACK_MODELS (if set) or the key's available flash models."""
        s = self.settings
        configured = s.gemini_model.strip().removeprefix("models/")
        if configured and not s.gemini_model_fallback:
            return [configured]
        explicit = [m.strip().removeprefix("models/") for m in s.gemini_fallback_models.split(",") if m.strip()]
        if explicit:
            others = explicit
        else:
            try:
                others = self._available_models()
            except Exception:  # noqa: BLE001 - a configured model still works without the model list
                if not configured:
                    raise
                others = []
        order = list(dict.fromkeys(([configured] if configured else []) + others))
        if not order:
            raise AiConfigurationError("No suitable Gemini text model is available to this API key. Set GEMINI_MODEL.")
        return order

    def candidates(self) -> list[str]:
        """The rotation with resting models moved to the back (soonest-recovering first). A rested
        model rejoins at its preferred position as soon as its cool-down ends."""
        order = self.rotation()
        now = time.monotonic()
        with self._lock:
            ready = [m for m in order if self._cooldown.get(m, 0) <= now]
            resting = sorted((m for m in order if self._cooldown.get(m, 0) > now), key=lambda m: self._cooldown[m])
        return ready + resting

    def model_name(self) -> str:
        return self.candidates()[0]

    def resting_models(self) -> dict[str, int]:
        """Models currently cooling down → seconds left (status / logs; no secrets)."""
        now = time.monotonic()
        with self._lock:
            return {m: int(t - now) + 1 for m, t in self._cooldown.items() if t > now}

    def _all_exhausted_error(self) -> AiQuotaExceededError:
        resting = self.resting_models()
        wait = min(resting.values()) if resting else QUOTA_COOLDOWN_SECONDS
        when = f"about {max(1, round(wait / 60))} minute(s)" if wait >= 60 else f"about {wait} seconds"
        return AiQuotaExceededError(
            f"All available AI models have reached their usage limits. Please try again in {when}.",
            [f"{len(resting)} model(s) are resting."],
        )

    def _cool_down(self, model: str, seconds: float, reason: str) -> None:
        with self._lock:
            self._cooldown[model] = time.monotonic() + seconds
        logger.warning("gemini model %s %s; resting it for %ds", model, reason, int(seconds))

    def generate(self, system_instruction: str, contents: list[dict[str, Any]]) -> GeminiResult:
        from google.genai import types

        client = self._get_client()
        order = self.candidates()
        now = time.monotonic()
        with self._lock:
            ready = [m for m in order if self._cooldown.get(m, 0) <= now]
        # Only models that are not resting are tried, best first. If every model rests, the one that
        # recovers first gets a single try (its quota may already be back).
        models = (ready or order[:1])[: self.settings.gemini_max_model_attempts]
        response = None
        exhausted = 0
        for i, model in enumerate(models):
            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                max_output_tokens=output_token_limit(model, self.settings),
                temperature=self.settings.gemini_temperature,
                thinking_config=_thinking_config(model),
                # Explanation assistant only: no tools, no automatic function calling.
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            )
            try:
                response = client.models.generate_content(model=model, contents=contents, config=config)
                if i:
                    logger.info("gemini rotation answered with %s after %d failed model(s)", model, i)
                break
            except Exception as exc:  # noqa: BLE001 - mapped to a friendly error
                last = i + 1 >= len(models)
                if _is_exhausted(exc):
                    exhausted += 1
                    self._cool_down(model, quota_cooldown_seconds(exc), "is exhausted (quota)")
                    if not last:
                        continue
                    raise self._all_exhausted_error() from None
                if _is_model_unavailable(exc):
                    self._cool_down(model, MODEL_COOLDOWN_SECONDS, "is unavailable")
                    if not last:
                        continue
                elif _is_model_slow(exc):
                    self._cool_down(model, MODEL_COOLDOWN_SECONDS, "timed out")
                if exhausted and last:
                    raise self._all_exhausted_error() from None
                raise _map_error(exc) from None
        try:
            text = (response.text or "").strip()
        except Exception:  # noqa: BLE001 - .text raises on some blocked / malformed responses
            text = ""
        if not text:
            feedback = getattr(response, "prompt_feedback", None)
            if feedback is not None and getattr(feedback, "block_reason", None):
                raise AiBadResponseError("I can't answer that request. Please rephrase your question about the analysis.")
            raise AiBadResponseError("The AI Assistant returned an empty answer. Please try again.")
        # Never present a cut-off answer as complete.
        candidates = getattr(response, "candidates", None) or []
        finish = str(getattr(candidates[0], "finish_reason", "") or "") if candidates else ""
        if finish.endswith("MAX_TOKENS"):
            meta0 = getattr(response, "usage_metadata", None)
            logger.warning("gemini answer truncated (MAX_TOKENS) model=%s output_tokens=%s thought_tokens=%s", model,
                           getattr(meta0, "candidates_token_count", None), getattr(meta0, "thoughts_token_count", None))
            text += TRUNCATED_NOTE
        usage = None
        meta = getattr(response, "usage_metadata", None)
        if meta is not None:
            usage = {k: int(v) for k, v in {
                "prompt_tokens": getattr(meta, "prompt_token_count", None),
                "output_tokens": getattr(meta, "candidates_token_count", None),
                "total_tokens": getattr(meta, "total_token_count", None),
            }.items() if isinstance(v, int)}
        return GeminiResult(text=text, model=model, usage=usage or None)


_provider: GeminiProvider | None = None
_provider_lock = threading.Lock()


def get_provider(settings: Settings) -> GeminiProvider:
    global _provider
    with _provider_lock:
        if _provider is None or _provider.settings is not settings:
            _provider = GeminiProvider(settings)
        return _provider


def reset_provider() -> None:
    global _provider
    with _provider_lock:
        _provider = None
