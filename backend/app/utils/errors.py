"""Application exceptions that map cleanly to HTTP error responses.

Routes raise these; ``app.main`` converts them to JSON ``ErrorResponse``
bodies with a stable, machine-readable ``error`` code. Internal exception
details are never sent to the client.

Error codes
-----------
INVALID_REQUEST                 missing / malformed parameters
INVALID_COORDINATES             latitude / longitude outside valid ranges
TEMPORAL_RANGE_UNAVAILABLE      years outside NASA POWER coverage or too short
PARAMETER_NOT_AVAILABLE         variable not in the catalogue / rejected by NASA
LOCATION_NOT_SUPPORTED          variable not meaningful or rejected at this location
NO_VALID_DATA                   NASA returned only missing values
NASA_API_UNAVAILABLE            NASA POWER unreachable, failing or malformed
INSUFFICIENT_DATA_FOR_ANALYSIS  too few usable years for trend tests (reported in
                                the 200 analysis response, not as an HTTP error)
NO_VARIATION_IN_DATA            every usable annual value is identical, so no trend
                                can be estimated (also reported in the 200 response)
GEOCODER_UNAVAILABLE            location search service unreachable
INVALID_GEOMETRY                polygon / GeoJSON rejected (self-intersection, too few
                                vertices, zero area, bad coordinates, wrong type)
GEOMETRY_TOO_COMPLEX            too many vertices, parts or bytes in a geometry
COUNTRY_NOT_FOUND               unknown ISO 3166-1 alpha-3 code
BOUNDARY_SOURCE_UNAVAILABLE     the boundary provider could not be reached
ANALYSIS_TOO_LARGE              an area needs more cells / NASA requests than the budget
INCOMPLETE_TILE_RETRIEVAL       one or more NASA tiles failed; no partial result is produced
"""

from __future__ import annotations

INSUFFICIENT_DATA_FOR_ANALYSIS = "INSUFFICIENT_DATA_FOR_ANALYSIS"
NO_VARIATION_IN_DATA = "NO_VARIATION_IN_DATA"


class EarthScopeError(Exception):
    status_code = 500
    error = "INTERNAL_ERROR"
    retryable = False

    def __init__(
        self,
        message: str,
        details: list[str] | None = None,
        suggested_variables: list[str] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.details = details or []
        self.suggested_variables = suggested_variables or []


class InvalidRequestError(EarthScopeError):
    status_code = 422
    error = "INVALID_REQUEST"


class InvalidCoordinatesError(EarthScopeError):
    status_code = 422
    error = "INVALID_COORDINATES"


class TemporalRangeError(EarthScopeError):
    status_code = 422
    error = "TEMPORAL_RANGE_UNAVAILABLE"


class UnsupportedVariableError(EarthScopeError):
    status_code = 404
    error = "PARAMETER_NOT_AVAILABLE"


class LocationNotSupportedError(EarthScopeError):
    """The variable is not meaningful, or not offered, at this location."""

    status_code = 422
    error = "LOCATION_NOT_SUPPORTED"


class NasaPowerUnavailableError(EarthScopeError):
    """NASA POWER could not be reached, timed out, or returned a server error."""

    status_code = 503
    error = "NASA_API_UNAVAILABLE"
    retryable = True


class NasaPowerResponseError(EarthScopeError):
    """NASA POWER answered with something we could not interpret."""

    status_code = 502
    error = "NASA_API_UNAVAILABLE"
    retryable = True


class DataUnavailableError(EarthScopeError):
    """The response contained no usable data for the requested parameter."""

    status_code = 404
    error = "NO_VALID_DATA"


class GeocoderUnavailableError(EarthScopeError):
    status_code = 503
    error = "GEOCODER_UNAVAILABLE"
    retryable = True


class InvalidGeometryError(EarthScopeError):
    status_code = 422
    error = "INVALID_GEOMETRY"


class GeometryTooComplexError(EarthScopeError):
    status_code = 422
    error = "GEOMETRY_TOO_COMPLEX"


class CountryNotFoundError(EarthScopeError):
    status_code = 404
    error = "COUNTRY_NOT_FOUND"


class BoundarySourceUnavailableError(EarthScopeError):
    status_code = 503
    error = "BOUNDARY_SOURCE_UNAVAILABLE"
    retryable = True


class AnalysisTooLargeError(EarthScopeError):
    status_code = 422
    error = "ANALYSIS_TOO_LARGE"


class IncompleteTileRetrievalError(EarthScopeError):
    """Some NASA tiles failed after retries; a partial area must never be reported as complete."""

    status_code = 503
    error = "INCOMPLETE_TILE_RETRIEVAL"
    retryable = True


def nasa_rejection(messages: list[str]) -> EarthScopeError:
    """Classify a NASA POWER HTTP 4xx rejection by the messages it returned."""
    text = " ".join(messages).lower()
    if "latitude" in text or "longitude" in text or "coordinate" in text:
        cls: type[EarthScopeError] = LocationNotSupportedError
        msg = "NASA POWER does not accept this location."
    elif "date" in text or "start" in text or "end" in text or "year" in text:
        cls, msg = TemporalRangeError, "NASA POWER has no data for the requested time range."
    elif "parameter" in text or "community" in text:
        cls, msg = UnsupportedVariableError, "NASA POWER does not offer this variable for the request."
    else:
        cls, msg = InvalidRequestError, "NASA POWER could not fulfil this request."
    return cls(msg, messages)


class StatisticsError(Exception):
    """Raised by the analysis engine when a statistic cannot be computed."""

    def __init__(self, message: str, code: str = INSUFFICIENT_DATA_FOR_ANALYSIS):
        super().__init__(message)
        self.code = code
