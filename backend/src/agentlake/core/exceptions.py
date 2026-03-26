"""Custom exception hierarchy and RFC 7807 error handlers."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


# ── Base Exception ───────────────────────────────────────────────────────────


class AgentLakeError(Exception):
    """Base exception for all AgentLake domain errors."""

    status_code: int = 500
    detail: str = "Internal server error"

    def __init__(self, detail: str | None = None, status_code: int | None = None) -> None:
        self.detail = detail or self.__class__.detail
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.detail)


# ── Concrete Exceptions ─────────────────────────────────────────────────────


class NotFoundError(AgentLakeError):
    """Resource not found."""

    status_code = 404
    detail = "Resource not found"


class ValidationError(AgentLakeError):
    """Request validation failed beyond Pydantic's built-in checks."""

    status_code = 422
    detail = "Validation error"


class AuthorizationError(AgentLakeError):
    """Authentication or authorization failure."""

    status_code = 403
    detail = "Forbidden"


class RateLimitError(AgentLakeError):
    """Client has exceeded the rate limit."""

    status_code = 429
    detail = "Rate limit exceeded"


class LLMGatewayError(AgentLakeError):
    """Communication with the LLM Gateway failed."""

    status_code = 502
    detail = "LLM Gateway error"


class ConflictError(AgentLakeError):
    """Resource conflict (duplicate, version mismatch, etc.)."""

    status_code = 409
    detail = "Conflict"


class StorageError(AgentLakeError):
    """Object storage (MinIO) operation failed."""

    status_code = 500
    detail = "Storage error"


# ── RFC 7807 Problem Details Handler ─────────────────────────────────────────


def _problem_detail_response(
    request: Request, status: int, title: str, detail: str
) -> JSONResponse:
    """Build an RFC 7807 Problem Details JSON response.

    Args:
        request: The incoming request (used for ``instance``).
        status: HTTP status code.
        title: Short human-readable summary.
        detail: Longer explanation.

    Returns:
        JSONResponse with ``application/problem+json`` content type.
    """
    return JSONResponse(
        status_code=status,
        content={
            "type": "about:blank",
            "title": title,
            "status": status,
            "detail": detail,
            "instance": str(request.url.path),
        },
        media_type="application/problem+json",
    )


async def _agentlake_error_handler(
    request: Request, exc: AgentLakeError
) -> JSONResponse:
    """Handle any AgentLakeError subclass."""
    return _problem_detail_response(
        request,
        status=exc.status_code,
        title=exc.__class__.__name__.replace("Error", " Error"),
        detail=exc.detail,
    )


async def _unhandled_error_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Catch-all for unexpected exceptions (500)."""
    return _problem_detail_response(
        request,
        status=500,
        title="Internal Server Error",
        detail="An unexpected error occurred",
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register all custom exception handlers on the FastAPI app.

    Args:
        app: The FastAPI application instance.
    """
    app.add_exception_handler(AgentLakeError, _agentlake_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_error_handler)  # type: ignore[arg-type]
