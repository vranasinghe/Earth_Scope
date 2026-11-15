"""User-facing AI assistant errors (rendered by app.main's EarthScopeError handler).

Messages are friendly and never contain provider exception text, request bodies or secrets.
"""

from __future__ import annotations

from app.utils.errors import EarthScopeError


class AiNotConfiguredError(EarthScopeError):
    status_code = 503
    error = "AI_NOT_CONFIGURED"


class AiConfigurationError(EarthScopeError):
    status_code = 503
    error = "AI_CONFIGURATION_ERROR"


class AiUnavailableError(EarthScopeError):
    status_code = 503
    error = "AI_UNAVAILABLE"
    retryable = True


class AiTimeoutError(EarthScopeError):
    status_code = 504
    error = "AI_TIMEOUT"
    retryable = True


class AiQuotaExceededError(EarthScopeError):
    status_code = 429
    error = "AI_QUOTA_EXCEEDED"
    retryable = True


class AiRateLimitedError(EarthScopeError):
    status_code = 429
    error = "AI_RATE_LIMITED"
    retryable = True


class AiBusyError(EarthScopeError):
    status_code = 429
    error = "AI_BUSY"
    retryable = True


class AiBadResponseError(EarthScopeError):
    status_code = 502
    error = "AI_BAD_RESPONSE"
    retryable = True


class AiContextUnavailableError(EarthScopeError):
    status_code = 404
    error = "AI_CONTEXT_UNAVAILABLE"


class AiMessageTooLongError(EarthScopeError):
    status_code = 422
    error = "AI_MESSAGE_TOO_LONG"


UNAVAILABLE_MESSAGE = "AI Assistant is temporarily unavailable. Please try again."
NOT_CONFIGURED_MESSAGE = "AI Assistant is not configured yet."
CONTEXT_MESSAGE = "I couldn't access the results for this analysis."
