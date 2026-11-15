from fastapi import APIRouter

from app.api.deps import SettingsDep
from app.core.catalog import POWER_MONTHLY_DOCS, POWER_PARAMETER_DOCS, VARIABLES
from app.models.schemas import VariableInfo, VariablesResponse

router = APIRouter(tags=["variables"])


@router.get("/variables", response_model=VariablesResponse, summary="List supported environmental variables")
def list_variables(settings: SettingsDep) -> VariablesResponse:
    return VariablesResponse(
        variables=[
            VariableInfo(
                id=v.id,
                name=v.name,
                parameter=v.parameter,
                community=v.community,
                category=v.category,
                description=v.description,
                purpose=v.purpose,
                expected_unit=v.expected_unit,
                unit_display=v.unit_display,
                rate_unit=v.rate_unit,
                source_note=v.source_note,
                spatial_resolution=v.spatial_resolution,
                notes=list(v.notes),
                data_source=v.data_source,
                supported_communities=list(v.supported_communities),
                available_temporal_resolutions=list(v.temporal_resolutions),
                coverage_start_year=v.coverage_start_year,
                geographic_coverage=v.geographic_coverage,
                land_only=v.land_only,
                alternatives=list(v.alternatives),
            )
            for v in VARIABLES
        ],
        min_year=settings.data_min_year,
        max_year=settings.max_year,
        default_start_year=settings.default_start_year,
        default_end_year=settings.default_end_year,
        min_year_span=settings.min_year_span,
        min_valid_months_per_year=settings.min_valid_months_per_year,
        min_annual_records=settings.min_annual_records,
        significance_alpha=settings.significance_alpha,
        documentation_url=POWER_MONTHLY_DOCS,
        parameter_docs_url=POWER_PARAMETER_DOCS,
    )
