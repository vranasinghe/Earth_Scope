"""Request / response schemas for the AI assistant (/api/ai/...).

The browser never sends numerical results. It sends an *analysis reference* — the same
parameters it used to request the analysis (or a background job id) — and the server
recomputes / reloads the authoritative result (from its caches) before building context.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field

from app.models.regional_schemas import BBoxModel

PageType = Literal[
    "home", "explore", "point_results", "compare_setup", "compare_results",
    "regional_setup", "regional_results", "jobs", "job_details", "learn", "other",
]

_CELL_ID = r"^-?\d{1,3}(\.\d{1,6})?_-?\d{1,3}(\.\d{1,6})?$"
_JOB_ID = r"^[0-9a-fA-F-]{36}$"


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., max_length=20_000)


class PointReference(BaseModel):
    variable: str = Field(..., max_length=40)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    start_year: int | None = None
    end_year: int | None = None
    place: str | None = Field(None, max_length=200)


class CompareLocationRef(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    label: str = Field("", max_length=200)


class CompareReference(BaseModel):
    variable: str = Field(..., max_length=40)
    locations: list[CompareLocationRef] = Field(..., min_length=2, max_length=3)
    start_year: int | None = None
    end_year: int | None = None


class RectangleArea(BaseModel):
    kind: Literal["rectangle"]
    bbox: BBoxModel


class CountryArea(BaseModel):
    kind: Literal["country"]
    iso3: str = Field(..., pattern=r"^[A-Za-z]{3}$")


class PolygonArea(BaseModel):
    kind: Literal["polygon"]
    geometry: dict[str, Any]
    name: str | None = Field(None, max_length=200)


AreaReference = Annotated[Union[RectangleArea, CountryArea, PolygonArea], Field(discriminator="kind")]


class SpatialReference(BaseModel):
    """Spatial Trend Explorer settings. Test settings are re-validated and recomputed on the
    server; ``layer`` / ``estimator`` / ``basis`` only describe what the map is showing."""

    method: str = Field("mann_kendall", max_length=40)
    correction: str = Field("fdr_bh", max_length=20)
    alpha: float = 0.05
    layer: Literal["magnitude", "direction", "significance", "availability"] | None = None
    estimator: Literal["sen", "ols"] | None = None
    basis: Literal["adjusted", "raw"] | None = None
    selected_cell_id: str | None = Field(None, pattern=_CELL_ID)


class RegionalReference(BaseModel):
    variable: str | None = Field(None, max_length=40)
    start_year: int | None = None
    end_year: int | None = None
    coverage_threshold: float | None = None
    area: AreaReference | None = None
    job_id: str | None = Field(None, pattern=_JOB_ID)
    spatial: SpatialReference | None = None


class JobReference(BaseModel):
    job_id: str = Field(..., pattern=_JOB_ID)


class LearnReference(BaseModel):
    topic: str | None = Field(None, max_length=120)


class AiChatRequest(BaseModel):
    message: str = Field("", max_length=20_000)
    action: Literal["ask", "summarize"] = "ask"
    page_type: PageType = "other"
    reference: dict[str, Any] | None = Field(None, description="Analysis reference for page_type (see the *Reference models)")
    history: list[ChatTurn] = Field(default_factory=list, max_length=200)
    earlier_summary: str | None = Field(None, max_length=20_000, description="Client-side digest of turns older than the history window")


class AiUsage(BaseModel):
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class AiChatResponse(BaseModel):
    reply: str
    context_id: str | None = Field(None, description="Stable id of the analysis the answer was based on")
    context_label: str | None = None
    has_results: bool = False
    model: str | None = None
    usage: AiUsage | None = None
    generated: bool = Field(True, description="False when Earth Scope answered without calling Gemini (e.g. nothing to summarize)")


class AiLimits(BaseModel):
    max_message_chars: int
    max_history_messages: int
    requests_per_minute: int
    requests_per_hour: int


class AiStatusResponse(BaseModel):
    enabled: bool
    configured: bool
    available: bool
    reason: str
    model: str | None = Field(None, description="Configured model id, or 'auto' (never secrets)")
    model_rotation: bool = Field(True, description="Whether exhausted / failing models rotate to the next model")
    resting_models: dict[str, int] = Field(default_factory=dict, description="Models cooling down → seconds left")
    message: str
    limits: AiLimits
    privacy_notice: str
