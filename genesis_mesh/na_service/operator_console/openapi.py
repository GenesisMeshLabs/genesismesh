"""OpenAPI metadata generation for Network Authority surfaces."""

from __future__ import annotations

from typing import Any

from .surfaces import HTTP_SURFACES, Surface


def _openapi_operation(surface: Surface) -> dict[str, Any]:
    """Build a compact OpenAPI operation object for one surface."""
    operation: dict[str, Any] = {
        "summary": surface.title,
        "description": surface.purpose,
        "tags": [surface.group],
        "responses": {
            "200": {
                "description": "Successful response",
                "content": {"application/json": {"schema": {"type": "object"}}},
            }
        },
        "x-genesis-mesh-access": surface.access,
        "x-genesis-mesh-auth-hint": surface.auth_hint,
    }
    if surface.query_hint:
        operation["description"] = f"{surface.purpose} {surface.query_hint}"
    if surface.access == "operator_signed":
        operation["security"] = [{"OperatorSignature": []}]
    elif surface.access == "node_signed":
        operation["security"] = [{"NodeProof": []}]
    return operation


def build_swagger_spec(service, base_url: str) -> dict[str, Any]:
    """Generate OpenAPI-compatible metadata for HTTP surfaces."""
    paths: dict[str, dict[str, Any]] = {}
    for surface in HTTP_SURFACES:
        paths.setdefault(surface.target, {})[surface.method.lower()] = _openapi_operation(surface)

    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Genesis Mesh Network Authority API",
            "version": service.genesis_block.network_version,
            "description": "Read-only generated protocol surface metadata for this Network Authority.",
        },
        "servers": [{"url": base_url}],
        "paths": paths,
        "components": {
            "securitySchemes": {
                "OperatorSignature": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-Genesis-Operator-Signature",
                    "description": "Operator-signed request headers with replay-protected nonces.",
                },
                "NodeProof": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-Genesis-Node-Proof",
                    "description": "Node proof-of-possession or signed request body.",
                },
            }
        },
        "x-genesis-mesh-note": (
            "Generated reference only; this service does not expose browser "
            "try-it execution."
        ),
    }
