from fastapi import APIRouter

from app.api.deps import ClientDep, QueryDep, SettingsDep
from app.models.schemas import DataResponse, ErrorResponse
from app.services.analysis_service import build_data_response

router = APIRouter(tags=["data"])

ERRORS = {code: {"model": ErrorResponse} for code in (404, 422, 502, 503)}


@router.get(
    "/data",
    response_model=DataResponse,
    responses=ERRORS,
    summary="Retrieve and clean a NASA POWER monthly time series",
)
def get_data(query: QueryDep, client: ClientDep, settings: SettingsDep) -> DataResponse:
    result = build_data_response(query, client, settings)
    result.pop("_annual_df", None)
    return DataResponse.model_validate(result)
