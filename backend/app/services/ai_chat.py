"""Stateless AI chat orchestration.

Request → validate limits → resolve trusted context → system instruction + bounded history
+ question → Gemini → reply. Nothing is persisted: no database row, no Redis key, no file.
Logs contain metadata only (page type, action, context id, latency, token counts, outcome),
never message text, context content or credentials.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Any

from fastapi import Request

from app.ai import gemini
from app.ai.errors import NOT_CONFIGURED_MESSAGE, AiMessageTooLongError, AiNotConfiguredError
from app.ai.rate_limit import get_limiter
from app.ai.system_prompt import JOB_NOT_READY_REPLY, NO_RESULTS_REPLY, SUMMARY_PROMPT, build_system_instruction
from app.core.config import Settings
from app.models.ai_schemas import AiChatRequest
from app.services.ai_context import fit_context, resolve_context
from app.services.nasa_power import NasaPowerClient

logger = logging.getLogger("earthscope.ai")

PRIVACY_NOTICE = ("Your messages and a compact summary of the analysis on screen are sent to Google Gemini to generate answers. "
                  "Earth Scope itself does not save your chat; it is kept only in this browser tab until you end it or reload.")

# Identical request from the same client within a few seconds (double click, network retry) → same answer,
# no second billable call. Holds replies for DEDUPE_SECONDS only.
DEDUPE_SECONDS = 8.0
_recent: dict[str, tuple[float, dict[str, Any]]] = {}
_recent_lock = threading.Lock()


def client_key(request: Request, settings: Settings) -> str:
    """Rate-limit key: the anonymous job-session cookie when present, else the client IP (hashed)."""
    token = request.cookies.get(settings.session_cookie_name)
    raw = f"s:{token}" if token else f"ip:{request.client.host if request.client else 'unknown'}"
    return hashlib.sha256(f"earthscope-ai:{raw}".encode()).hexdigest()[:24]


def _redact(text: str, settings: Settings) -> str:
    key = settings.gemini_api_key.get_secret_value().strip()
    if key and key in text:
        text = text.replace(key, "[redacted]")
    return text


def bounded_history(req: AiChatRequest, settings: Settings) -> list[dict[str, Any]]:
    """Last N turns, each truncated; roles mapped to Gemini's user/model; consecutive same-role turns merged;
    the conversation always starts with a user turn."""
    turns = req.history[-settings.ai_max_history_messages:]
    contents: list[dict[str, Any]] = []
    if req.earlier_summary and req.earlier_summary.strip():
        digest = req.earlier_summary.strip()[: settings.ai_max_summary_chars]
        contents.append({"role": "user", "parts": [{"text": f"(Summary of our earlier conversation, for reference only: {digest})"}]})
        contents.append({"role": "model", "parts": [{"text": "Thanks — I'll keep that in mind."}]})
    for t in turns:
        role = "user" if t.role == "user" else "model"
        text = t.content.strip()[: settings.ai_max_history_message_chars]
        if not text:
            continue
        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"][0]["text"] += "\n\n" + text
        else:
            contents.append({"role": role, "parts": [{"text": text}]})
    while contents and contents[0]["role"] != "user":
        contents.pop(0)
    return contents


def status_payload(settings: Settings) -> dict[str, Any]:
    ok, reason = gemini.availability(settings)
    messages = {
        "ok": "AI Assistant is ready.",
        "disabled": "AI Assistant is turned off on this server.",
        "missing_api_key": NOT_CONFIGURED_MESSAGE,
        "sdk_not_installed": "AI Assistant is not configured yet (the Gemini SDK is not installed on the server).",
    }
    return {
        "enabled": settings.gemini_chat_enabled,
        "configured": ok,
        "available": ok,
        "reason": reason,
        "model": (settings.gemini_model.strip() or "auto") if ok else None,
        "model_rotation": settings.gemini_model_fallback or not settings.gemini_model.strip(),
        # Models currently resting after exhaustion / errors → seconds left (no Google call made here).
        "resting_models": gemini.get_provider(settings).resting_models() if ok else {},
        "message": messages.get(reason, NOT_CONFIGURED_MESSAGE),
        "limits": {"max_message_chars": settings.ai_max_message_chars, "max_history_messages": settings.ai_max_history_messages,
                   "requests_per_minute": settings.ai_rate_limit_per_minute, "requests_per_hour": settings.ai_rate_limit_per_hour},
        "privacy_notice": PRIVACY_NOTICE,
    }


def chat(req: AiChatRequest, *, client: NasaPowerClient, settings: Settings, request: Request) -> dict[str, Any]:
    t0 = time.monotonic()
    ok, reason = gemini.availability(settings)
    if not ok:
        raise AiNotConfiguredError(NOT_CONFIGURED_MESSAGE, [reason])
    message = req.message.strip()
    if req.action == "ask":
        if not message:
            raise AiMessageTooLongError("Please type a question.")
        if len(message) > settings.ai_max_message_chars:
            raise AiMessageTooLongError(f"Your message is too long. Please keep it under {settings.ai_max_message_chars} characters.")

    key = client_key(request, settings)
    fingerprint = hashlib.sha256(
        f"{key}|{req.action}|{req.page_type}|{message}|{len(req.history)}|{req.reference}".encode()).hexdigest()
    now = time.monotonic()
    with _recent_lock:
        for k in [k for k, (t, _) in _recent.items() if now - t > DEDUPE_SECONDS]:
            _recent.pop(k, None)
        hit = _recent.get(fingerprint)
    if hit:
        return hit[1]

    limiter = get_limiter(settings.ai_rate_limit_per_minute, settings.ai_rate_limit_per_hour, settings.ai_max_concurrency)
    limiter.check(key)

    ctx = resolve_context(req.page_type, req.reference, client=client, settings=settings, request=request)
    base = {"context_id": ctx.context_id, "context_label": ctx.label, "has_results": ctx.has_results}

    if req.action == "summarize" and not ctx.has_results:
        reply = JOB_NOT_READY_REPLY if ctx.job_unfinished else NO_RESULTS_REPLY
        logger.info("ai chat page=%s action=summarize ctx=%s outcome=no_results", req.page_type, ctx.context_id)
        return {**base, "reply": reply, "model": None, "usage": None, "generated": False}

    context = fit_context(ctx.data, settings.ai_max_context_chars)
    system = build_system_instruction(context)
    contents = bounded_history(req, settings)
    question = SUMMARY_PROMPT if req.action == "summarize" else message
    if contents and contents[-1]["role"] == "user":
        contents[-1]["parts"][0]["text"] += "\n\n" + question
    else:
        contents.append({"role": "user", "parts": [{"text": question}]})

    provider = gemini.get_provider(settings)
    outcome = "error"
    try:
        with limiter.slot():
            result = provider.generate(system, contents)
        outcome = "ok"
    finally:
        logger.info("ai chat page=%s action=%s ctx=%s turns=%d outcome=%s latency_ms=%d",
                    req.page_type, req.action, ctx.context_id, len(contents), outcome, (time.monotonic() - t0) * 1000)
    payload = {**base, "reply": _redact(result.text, settings), "model": result.model, "usage": result.usage, "generated": True}
    with _recent_lock:
        _recent[fingerprint] = (time.monotonic(), payload)
    return payload


def reset_state() -> None:
    with _recent_lock:
        _recent.clear()
