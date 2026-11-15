"""Application configuration.

All values can be overridden with environment variables prefixed with
``EARTHSCOPE_`` (for example ``EARTHSCOPE_NASA_TIMEOUT_SECONDS=60``) or via a
``.env`` file in the ``backend`` directory. See ``.env.example``.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="EARTHSCOPE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "Earth Scope API"
    app_version: str = "0.6.0"

    # --- NASA POWER -------------------------------------------------------
    nasa_power_monthly_url: str = "https://power.larc.nasa.gov/api/temporal/monthly/point"
    nasa_power_regional_url: str = "https://power.larc.nasa.gov/api/temporal/monthly/regional"
    nasa_regional_timeout_seconds: float = 120.0
    nasa_timeout_seconds: float = 45.0
    # NASA POWER's MERRA-2 based meteorology starts on 1981-01-01
    # (confirmed from the API's own validation message).
    data_min_year: int = 1981

    # --- Caching ------------------------------------------------------------
    cache_ttl_seconds: int = 24 * 60 * 60
    cache_max_entries: int = 256

    # --- Analysis -----------------------------------------------------------
    significance_alpha: float = 0.05
    confidence_level: float = 0.95
    # A year is used in the trend tests only if it has at least this many
    # valid monthly values (out of 12).
    min_valid_months_per_year: int = 10
    # Minimum number of usable annual values needed to run the trend tests.
    # The Mann-Kendall p-value uses the normal approximation of S, which is
    # generally considered adequate for n >= 10.
    min_annual_records: int = 10
    # Minimum requested time span in years (inclusive of both ends).
    min_year_span: int = 10
    default_start_year: int = 2001
    # --- Regional analysis ----------------------------------------------------
    # Verified live: NASA POWER regional requests must span 2°–10° per side. Earth
    # Scope expands each request by half a grid cell per side (to capture cells cut
    # by the box edge), so the user's box may span at most 9° per side.
    regional_min_span_deg: float = 2.0
    regional_max_span_deg: float = 9.0
    # A month's regional mean is used only if valid cells cover at least this
    # fraction of the analysed area (the box, or its land part for land-only variables).
    regional_coverage_threshold: float = 0.8
    # Land-only variables (soil wetness): minimum land fraction of the box.
    regional_min_land_fraction: float = 0.1

    # --- Country / custom-polygon analysis (tiled regional requests) -----------
    # Budgets measured on this machine (see README "Large-country processing"):
    # a full-size tile (285 cells, 25 years) downloads in ~1–4 s; Brazil (17 tiles,
    # 2,462 cells) loaded in 17.5 s; per-cell trend statistics cost ~6.5 ms per
    # cell for 25 years, so 3,000 cells ≈ 20 s.
    polygon_max_cells: int = 3000          # grid cells intersecting the area
    polygon_max_tiles: int = 24            # NASA regional requests per analysis
    polygon_max_values: int = 1_500_000    # cells × months held in memory
    polygon_max_concurrency: int = 3       # simultaneous NASA requests (respectful usage)
    polygon_tile_retries: int = 2          # retries per tile after the first attempt
    polygon_retry_backoff_seconds: float = 1.5
    polygon_max_vertices: int = 5000       # user-drawn / uploaded geometry
    polygon_max_parts: int = 50
    polygon_max_body_bytes: int = 3_000_000
    country_max_vertices: int = 600_000    # trusted boundary files
    boundary_cache_dir: str = ""           # default: app/data/boundary_cache
    boundary_timeout_seconds: float = 90.0

    # --- Background jobs & large-country analysis (Phase 6) -------------------
    # PostgreSQL in Docker Compose (postgresql+psycopg://...). The SQLite default is
    # for tests and single-machine experiments only; it is NOT the supported setup
    # for several workers (see README "Scalable Background Jobs").
    database_url: str = "sqlite:///./var/earthscope_jobs.db"
    redis_url: str = "redis://localhost:6379/0"
    artifact_dir: str = ""                  # default: backend/var/artifacts (a mounted volume in Docker)
    job_queue_name: str = "earthscope-analysis"
    job_rq_timeout_seconds: int = 6 * 3600  # hard RQ limit; normal jobs finish far sooner
    job_lease_seconds: float = 120.0           # a RUNNING job whose lease expires is treated as orphaned
    job_heartbeat_seconds: float = 15.0
    job_max_attempts: int = 3               # automatic attempts per run (worker loss, NASA outage, ...)
    job_max_manual_retries: int = 5
    job_retry_backoff_seconds: float = 60.0 # automatic job-level retry: 60 s, 120 s, ... (capped at 15 min)
    job_pending_requeue_seconds: int = 30   # outbox: PENDING jobs older than this are (re-)enqueued
    job_queued_recheck_seconds: int = 300   # QUEUED jobs whose RQ entry vanished are re-enqueued
    job_reconcile_interval_seconds: int = 20
    job_db_outage_tolerance_seconds: float = 120.0
    job_result_retention_days: int = 14
    job_failed_retention_days: int = 7
    job_tile_cache_hours: int = 24          # reuse a verified NASA tile from another job for this long
    job_tile_cache_retention_days: int = 30
    job_cell_chunk_size: int = 500          # cells per statistics checkpoint
    job_min_free_disk_mb: int = 200
    job_worker_class: str = "auto"          # auto | fork | simple (simple = no fork, required on native Windows)
    # Resource tiers (measured on this machine — README "Large-country resource budgets").
    # SMALL = inside the synchronous polygon_* limits above.
    job_medium_max_cells: int = 6000
    job_medium_max_tiles: int = 60
    job_large_max_cells: int = 15000
    job_large_max_tiles: int = 100
    job_large_max_values: int = 6_000_000   # cells × months
    job_max_memory_mb: int = 1536           # estimated worker peak; above this a job is VERY_LARGE
    job_max_storage_mb: int = 512           # artifacts written for one job (tiles + results)
    job_allow_very_large: bool = False      # deployments with bigger workers may enable the VERY_LARGE tier
    job_very_large_max_cells: int = 40000
    job_very_large_max_tiles: int = 250
    # Abuse protection (anonymous sessions)
    job_max_active_per_session: int = 2
    job_max_global_active: int = 20
    job_max_submissions_per_hour: int = 6
    job_max_submissions_per_ip_per_day: int = 30
    job_daily_tile_budget_per_session: int = 250
    # NASA POWER request coordination ACROSS ALL WORKERS (Redis)
    nasa_global_max_concurrency: int = 3
    nasa_min_request_interval_seconds: float = 0.5   # between request starts, application-wide
    nasa_slot_lease_seconds: float = 300.0           # > regional timeout, so a crashed holder frees its slot
    job_tile_max_attempts: int = 5
    job_tile_backoff_seconds: float = 2.0            # 2, 4, 8, 16 s (+ jitter), capped below
    job_tile_backoff_max_seconds: float = 120.0
    # Sessions & ownership (anonymous, cookie-bound)
    session_cookie_name: str = "es_session"
    csrf_cookie_name: str = "es_csrf"
    session_cookie_secure: bool = False     # set true behind HTTPS
    session_max_age_days: int = 30
    ops_token: str = ""                     # enables GET /api/analysis/ops when set (X-Ops-Token header)

    # Multi-location comparison: maximum number of locations per request
    # (fetched concurrently, at most compare_max_concurrency NASA requests at a time).
    max_compare_locations: int = 3
    compare_max_concurrency: int = 3

    # --- Location search (OpenStreetMap Nominatim) ----------------------------
    # Used ONLY to turn place names into coordinates; NASA data is always fetched
    # by coordinates. Policy: https://operations.osmfoundation.org/policies/nominatim/
    # (max 1 request/second, identifying User-Agent, no autocomplete, cache results).
    geocoder_search_url: str = "https://nominatim.openstreetmap.org/search"
    geocoder_reverse_url: str = "https://nominatim.openstreetmap.org/reverse"
    # Identify the application. Deployers may append their own contact, e.g.
    # "EarthScope/0.2 (+https://your-site.example)".
    geocoder_user_agent: str = "EarthScope/0.2 (educational NASA POWER trend explorer)"
    geocoder_timeout_seconds: float = 15.0
    geocoder_min_interval_seconds: float = 1.0
    geocoder_cache_ttl_seconds: int = 7 * 24 * 60 * 60
    geocoder_language: str = "en"

    # --- AI assistant (Google Gemini) -----------------------------------------
    # The key is read ONLY on the server (environment or backend/.env) and is never
    # returned to the browser or written to logs. GEMINI_* names are the documented
    # ones; EARTHSCOPE_GEMINI_* is accepted too, like every other setting.
    gemini_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias=AliasChoices("GEMINI_API_KEY", "EARTHSCOPE_GEMINI_API_KEY", "gemini_api_key"))
    # Empty = pick an available "flash" text model from the account's model list at first use.
    gemini_model: str = Field(default="", validation_alias=AliasChoices("GEMINI_MODEL", "EARTHSCOPE_GEMINI_MODEL", "gemini_model"))
    gemini_chat_enabled: bool = Field(
        default=True, validation_alias=AliasChoices("GEMINI_CHAT_ENABLED", "EARTHSCOPE_GEMINI_CHAT_ENABLED", "gemini_chat_enabled"))
    gemini_max_output_tokens: int = Field(
        default=1200, ge=64, le=8192,
        validation_alias=AliasChoices("GEMINI_MAX_OUTPUT_TOKENS", "EARTHSCOPE_GEMINI_MAX_OUTPUT_TOKENS", "gemini_max_output_tokens"))
    # Model rotation: when a model is exhausted (429 quota), unavailable (503/404) or timed out, the next
    # model is tried and the failed one rests until Google says it can be used again; it then rejoins the
    # rotation. GEMINI_FALLBACK_MODELS = comma-separated ids (empty = the key's available "flash" models).
    gemini_fallback_models: str = Field(
        default="", validation_alias=AliasChoices("GEMINI_FALLBACK_MODELS", "EARTHSCOPE_GEMINI_FALLBACK_MODELS", "gemini_fallback_models"))
    gemini_model_fallback: bool = Field(
        default=True, validation_alias=AliasChoices("GEMINI_MODEL_FALLBACK", "EARTHSCOPE_GEMINI_MODEL_FALLBACK", "gemini_model_fallback"))
    gemini_max_model_attempts: int = Field(default=6, ge=1, le=20)
    # Extra output tokens for "thinking" models (Gemini 2.5 / 3.x) on top of the answer budget,
    # because their thinking tokens count against max_output_tokens.
    gemini_thinking_reserve_tokens: int = Field(default=1024, ge=0, le=16384)
    gemini_timeout_seconds: float = 30.0
    gemini_temperature: float = 0.3
    # Cost / abuse controls (in-memory, per browser session or IP; nothing is persisted).
    ai_max_message_chars: int = 2000
    ai_max_history_messages: int = 20
    ai_max_history_message_chars: int = 4000
    ai_max_summary_chars: int = 1500
    ai_max_context_chars: int = 12000
    ai_rate_limit_per_minute: int = 8
    ai_rate_limit_per_hour: int = 60
    ai_max_concurrency: int = 4

    # --- Web ------------------------------------------------------------------
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173,http://127.0.0.1:4173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def max_year(self) -> int:
        """Latest year a user may request (the current calendar year)."""
        return date.today().year

    @property
    def default_end_year(self) -> int:
        """Latest year that is normally *complete* in NASA POWER.

        MERRA-2 based monthly values are published with a lag of roughly one
        to two months, so the previous calendar year is normally complete from
        March onwards. The analysis response always reports the actual
        ``latest_complete_year`` found in the data, and incomplete years are
        excluded from trend tests, so this is only a sensible default.
        """
        today = date.today()
        return today.year - 1 if today.month >= 3 else today.year - 2


@lru_cache
def get_settings() -> Settings:
    return Settings()
