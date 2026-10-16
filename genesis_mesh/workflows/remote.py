"""Calls to a Network Authority shared by workflows and CLI commands.

Moved here from ``cli/support.py`` (which still exports them), so that
``workflows/*`` does not import ``cli/*``. They raise ``click`` errors, as
the CLI commands that run the workflows expect.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click
import requests

from ..crypto import load_private_key
from ..crypto.admin_auth import sign_admin_request


def _require_positive_int(name: str, value: int) -> None:
    """Raise a compact CLI error when an integer option must be positive."""
    if value <= 0:
        raise click.ClickException(f"{name} must be greater than zero")


_ADMIN_AUDIENCES_META_KEY = "genesis_mesh.admin_audiences"

def _admin_audience(base_url: str) -> str:
    """Return the audience admin requests to this Network Authority must name:
    its public key (``network_authority.public_key``), unique to it.

    Read from the public ``/sovereign.json`` once per endpoint and command.
    The cache lives in the command's click context, not in the process: a
    process that outlives one command (a test run, a program that invokes
    the CLI) may meet another Network Authority at the same address (v1.1.0).
    """
    base = base_url.rstrip("/")
    ctx = click.get_current_context(silent=True)
    audiences: dict[str, str] = (
        ctx.meta.setdefault(_ADMIN_AUDIENCES_META_KEY, {}) if ctx is not None else {}
    )
    if base not in audiences:
        payload = _request_json(
            requests.Session(), "GET", f"{base}/sovereign.json", label="sovereign metadata"
        )
        authority = payload.get("network_authority")
        public_key = authority.get("public_key") if isinstance(authority, dict) else None
        if not isinstance(public_key, str) or not public_key:
            raise click.ClickException(
                f"{base}/sovereign.json has no network_authority.public_key"
            )
        audiences[base] = public_key
    return audiences[base]

def _signed_admin_headers(
    key_id: str,
    key_path: Path,
    body: dict[str, Any],
    *,
    method: str,
    base_url: str,
    path: str,
    query: dict[str, Any] | None = None,
    audience: str | None = None,
) -> dict[str, str]:
    """Sign one admin request: method, path, query, audience and body (v1.0.2).

    ``audience`` is the target Network Authority's public key; when omitted
    it is read from ``<base_url>/sovereign.json``.
    """
    if not key_path.exists():
        raise click.ClickException(f"Operator private key not found: {key_path}")
    audience = audience or _admin_audience(base_url)
    try:
        return sign_admin_request(
            load_private_key(str(key_path)),
            key_id,
            method=method,
            path=path,
            audience=audience,
            body=body,
            query=query,
        )
    except Exception as exc:
        raise click.ClickException(
            f"Could not sign admin request with operator key {key_path}: {exc}"
        ) from exc


def _request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    expected_status: int = 200,
    label: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Run an HTTP request and raise compact Click errors on failure."""
    try:
        response = session.request(method, url, timeout=20, **kwargs)
    except requests.RequestException as exc:
        raise click.ClickException(f"{label} failed: {exc}") from exc

    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text[:500]}

    if response.status_code != expected_status:
        detail = _api_error_message(payload)
        if detail:
            raise click.ClickException(f"{label} failed: {response.status_code} {detail}")
        raise click.ClickException(f"{label} failed: {response.status_code} {payload}")
    return payload

def _api_error_message(payload: Any) -> str | None:
    """Return a compact message from legacy or envelope-style API errors."""
    if not isinstance(payload, dict) or "error" not in payload:
        return None
    error = payload["error"]
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        code = error.get("code")
        message = error.get("message")
        if code and message:
            return f"{code}: {message}"
        if message:
            return str(message)
        if code:
            return str(code)
    return str(error)
