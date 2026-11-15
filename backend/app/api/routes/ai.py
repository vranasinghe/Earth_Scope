"""AI assistant endpoints: GET /api/ai/status, POST /api/ai/chat.

The Gemini key never leaves the server; neither endpoint returns configuration secrets.
The chat endpoint is stateless — the browser sends the bounded active conversation and the
server keeps nothing after replying.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.api.deps import ClientDep, SettingsDep
from app.api.routes.areas import BodyLimit
from app.models.ai_schemas import AiChatRequest, AiChatResponse, AiStatusResponse
from app.models.schemas import ErrorResponse
from app.services import ai_chat

router = APIRouter(prefix="/ai", tags=["ai assistant"])

ERRORS = {code: {"model": ErrorResponse} for code in (404, 422, 429, 502, 503, 504)}


@router.get("/status", response_model=AiStatusResponse, summary="Whether the AI assistant is configured (never returns secrets)")
def status(settings: SettingsDep, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return ai_chat.status_payload(settings)


@router.post("/chat", response_model=AiChatResponse, responses=ERRORS,
             summary="Ask Earth Scope AI about the analysis on the current page")
def chat(req: AiChatRequest, request: Request, response: Response, client: ClientDep, settings: SettingsDep,
         _: BodyLimit) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return ai_chat.chat(req, client=client, settings=settings, request=request)
