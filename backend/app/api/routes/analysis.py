from fastapi import APIRouter

from app.api.deps import ClientDep, QueryDep, SettingsDep
from app.models.schemas import AnalysisResponse, ErrorResponse
from app.services.analysis_service import build_analysis_response

router = APIRouter(tags=["analysis"])

ERRORS = {code: {"model": ErrorResponse} for code in (404, 422, 502, 503)}


@router.get(
    "/analyze",
    response_model=AnalysisResponse,
    responses=ERRORS,
    summary="Retrieve data and run regression, Mann-Kendall and Sen's slope analysis",
)
def analyze(query: QueryDep, client: ClientDep, settings: SettingsDep) -> AnalysisResponse:
    return AnalysisResponse.model_validate(build_analysis_response(query, client, settings))
