"""Shared Network Authority API error contract tests."""

from __future__ import annotations

import pytest

from genesis_mesh.na_service.errors import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    RateLimitError,
    RequestValidationError,
    UnauthorizedError,
)


def _register_error_route(app, path: str, error_or_callable) -> None:
    def route():
        if callable(error_or_callable):
            error_or_callable()
        raise error_or_callable

    app.add_url_rule(path, endpoint=path, view_func=route)


def _assert_error_shape(resp, *, status: int, code: str, message: str | None = None) -> dict:
    assert resp.status_code == status
    payload = resp.get_json()
    assert set(payload) == {"error"}
    error = payload["error"]
    assert set(error) == {"code", "message", "details", "request_id"}
    assert error["code"] == code
    assert isinstance(error["message"], str)
    assert isinstance(error["details"], dict)
    assert isinstance(error["request_id"], str)
    assert resp.headers["X-Request-ID"] == error["request_id"]
    if message is not None:
        assert error["message"] == message
    return error


@pytest.mark.parametrize(
    ("path", "exception", "status", "code", "message"),
    [
        (
            "/_test/bad-request",
            BadRequestError("Bad request test", code="bad_request_test"),
            400,
            "bad_request_test",
            "Bad request test",
        ),
        (
            "/_test/unauthorized",
            UnauthorizedError("Unauthorized test", code="unauthorized_test"),
            401,
            "unauthorized_test",
            "Unauthorized test",
        ),
        (
            "/_test/not-found",
            NotFoundError("Not found test", code="not_found_test"),
            404,
            "not_found_test",
            "Not found test",
        ),
        (
            "/_test/conflict",
            ConflictError("Conflict test", code="conflict_test"),
            409,
            "conflict_test",
            "Conflict test",
        ),
        (
            "/_test/validation",
            RequestValidationError("Validation test", code="validation_test"),
            422,
            "validation_test",
            "Validation test",
        ),
        (
            "/_test/rate-limit",
            RateLimitError("Rate limit test", code="rate_limit_test"),
            429,
            "rate_limit_test",
            "Rate limit test",
        ),
    ],
)
def test_api_errors_share_response_shape(
    na_service,
    path,
    exception,
    status,
    code,
    message,
):
    """Typed API exceptions are translated into one public envelope."""
    _register_error_route(na_service.app, path, exception)

    resp = na_service.app.test_client().get(path, headers={"X-Request-ID": "req-test"})

    error = _assert_error_shape(resp, status=status, code=code, message=message)
    assert error["request_id"] == "req-test"


def test_unexpected_api_error_is_sanitized(na_service):
    """Unhandled exceptions never expose stack traces, secrets, or file paths."""

    def explode():
        raise RuntimeError(
            "private key leaked at C:/secrets/operator.key token=abc Traceback line 1"
        )

    _register_error_route(na_service.app, "/_test/unexpected", explode)

    resp = na_service.app.test_client().get("/_test/unexpected")

    error = _assert_error_shape(
        resp,
        status=500,
        code="internal_server_error",
        message="Internal server error",
    )
    serialized = str(error)
    assert "Traceback" not in serialized
    assert "token=abc" not in serialized
    assert "operator.key" not in serialized
    assert "C:/secrets" not in serialized
