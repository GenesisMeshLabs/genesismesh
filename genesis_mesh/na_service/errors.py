"""Shared API error contract and Flask exception handlers."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from flask import Flask, g, jsonify, request
from pydantic import ValidationError as PydanticValidationError
from werkzeug.exceptions import HTTPException

from ..observability import redacted_exception_text

logger = logging.getLogger(__name__)
access_logger = logging.getLogger("genesis_mesh.na_service.access")


class ApiError(Exception):
    """Base class for API errors rendered through the shared envelope."""

    status_code = 500
    default_code = "internal_server_error"
    default_message = "Internal server error"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message or self.default_message)
        self.message = message or self.default_message
        self.code = code or self.default_code
        self.details = details or {}
        self.request_id = request_id

    def payload(self, request_id: str) -> dict[str, dict[str, Any]]:
        """Return the public JSON error envelope."""
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
                "request_id": self.request_id or request_id,
            }
        }


class BadRequestError(ApiError):
    status_code = 400
    default_code = "bad_request"
    default_message = "Bad request"


class UnauthorizedError(ApiError):
    status_code = 401
    default_code = "unauthorized"
    default_message = "Unauthorized"


class ForbiddenError(ApiError):
    status_code = 403
    default_code = "forbidden"
    default_message = "Forbidden"


class NotFoundError(ApiError):
    status_code = 404
    default_code = "not_found"
    default_message = "Not found"


class ConflictError(ApiError):
    status_code = 409
    default_code = "conflict"
    default_message = "Conflict"


class ValidationError(ApiError):
    status_code = 422
    default_code = "validation_failed"
    default_message = "Request validation failed"


class RequestValidationError(ValidationError):
    default_code = "request_validation_failed"


class RateLimitError(ApiError):
    status_code = 429
    default_code = "rate_limit_exceeded"
    default_message = "Rate limit exceeded"


class InternalServerError(ApiError):
    status_code = 500
    default_code = "internal_server_error"
    default_message = "Internal server error"


class ServiceUnavailableError(ApiError):
    status_code = 503
    default_code = "service_unavailable"
    default_message = "Service unavailable"


def current_request_id() -> str:
    """Return the request correlation ID for the current Flask request."""
    request_id = getattr(g, "request_id", None)
    if request_id:
        return request_id
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    g.request_id = request_id
    return request_id


def request_json_object(*, required: bool = False) -> dict[str, Any]:
    """Parse the request body as a JSON object using shared API errors."""
    data = request.get_json(silent=True)
    if data is None:
        if required:
            raise BadRequestError("request body must be valid JSON", code="invalid_json")
        return {}
    if not isinstance(data, dict):
        raise BadRequestError(
            "request body must be a JSON object",
            code="invalid_json_object",
        )
    return data


def positive_int_field(
    data: dict[str, Any],
    field: str,
    *,
    default: int,
    code: str,
    message: str | None = None,
) -> int:
    """Read a request field as a positive integer or raise a 400 error."""
    try:
        value = int(data.get(field, default))
    except (TypeError, ValueError):
        raise BadRequestError(
            message or f"{field} must be a positive integer",
            code=code,
        ) from None
    if value <= 0:
        raise BadRequestError(
            message or f"{field} must be a positive integer",
            code=code,
        )
    return value


def validation_details(exc: PydanticValidationError) -> dict[str, Any]:
    """Return sanitized Pydantic validation details."""
    errors = []
    for item in exc.errors():
        errors.append(
            {
                "loc": list(item.get("loc", ())),
                "msg": item.get("msg", "Invalid value"),
                "type": item.get("type", "value_error"),
            }
        )
    return {"errors": errors}


def _http_exception_to_api_error(exc: HTTPException) -> ApiError:
    code_name = (exc.name or "HTTP error").lower().replace(" ", "_")
    message = exc.description if exc.code and exc.code < 500 else "Internal server error"
    mapping: dict[int, type[ApiError]] = {
        400: BadRequestError,
        401: UnauthorizedError,
        403: ForbiddenError,
        404: NotFoundError,
        409: ConflictError,
        422: RequestValidationError,
        429: RateLimitError,
        503: ServiceUnavailableError,
    }
    if exc.code in mapping:
        return mapping[exc.code](message, code=code_name)
    if exc.code and exc.code < 500:
        error = ApiError(message, code=code_name)
        error.status_code = exc.code
        return error
    return InternalServerError()


def _log_api_error(error: ApiError, request_id: str) -> None:
    if error.status_code >= 500:
        if error.__cause__ is not None:
            logger.error(
                "API server error request_id=%s code=%s path=%s\n%s",
                request_id,
                error.code,
                request.path,
                redacted_exception_text(error.__cause__),
            )
        else:
            logger.error(
                "API server error request_id=%s code=%s path=%s",
                request_id,
                error.code,
                request.path,
            )
        return

    logger.warning(
        "API client error request_id=%s status=%s code=%s path=%s",
        request_id,
        error.status_code,
        error.code,
        request.path,
    )


def _render_api_error(error: ApiError):
    request_id = current_request_id()
    if error.status_code == 500:
        original_cause = getattr(error, "__cause__", None)
        error = InternalServerError(request_id=error.request_id or request_id)
        error.__cause__ = original_cause
    _log_api_error(error, request_id)
    response = jsonify(error.payload(request_id))
    response.status_code = error.status_code
    response.headers["X-Request-ID"] = request_id
    return response


def register_error_handlers(app: Flask) -> None:
    """Register shared API error handlers on a Flask app."""

    @app.before_request
    def _assign_request_id() -> None:
        g.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        g.request_started_at = time.perf_counter()

    @app.after_request
    def _attach_request_id_and_log_access(response):
        response.headers.setdefault("X-Request-ID", current_request_id())
        started_at = getattr(g, "request_started_at", None)
        duration_ms = 0.0
        if started_at is not None:
            duration_ms = (time.perf_counter() - started_at) * 1000
        access_logger.info(
            "API request request_id=%s method=%s path=%s status=%s duration_ms=%.2f remote_addr=%s",
            current_request_id(),
            request.method,
            request.path,
            response.status_code,
            duration_ms,
            request.remote_addr or "unknown",
        )
        return response

    @app.errorhandler(ApiError)
    def _handle_api_error(error: ApiError):
        return _render_api_error(error)

    @app.errorhandler(PydanticValidationError)
    def _handle_pydantic_validation(error: PydanticValidationError):
        return _render_api_error(
            RequestValidationError(
                "Request validation failed",
                code="request_validation_failed",
                details=validation_details(error),
            )
        )

    @app.errorhandler(HTTPException)
    def _handle_http_exception(error: HTTPException):
        return _render_api_error(_http_exception_to_api_error(error))

    @app.errorhandler(Exception)
    def _handle_unexpected(error: Exception):
        wrapped = InternalServerError()
        wrapped.__cause__ = error
        return _render_api_error(wrapped)
