"""Client-side helpers for agent discovery / service registration.

Applications use these helpers to:

- build a signed ``AgentDescriptor`` with the node's join-certificate key
- POST it to the Network Authority's ``/agents`` endpoint
- refresh it on a periodic schedule
- discover other agents by capability

The Network Authority is the system of record. Clients do not need to keep
local registry state — they just announce themselves and query when needed.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import nacl.signing
import requests

from ..crypto import sign_data, sign_model
from ..models import AgentDescriptor, AgentEndpoint


logger = logging.getLogger(__name__)


DEFAULT_TTL_SECONDS = 600          # 10 minutes
DEFAULT_REFRESH_SECONDS = 300      # refresh halfway through the TTL


def build_signed_descriptor(
    *,
    agent_id: str,
    node_public_key: str,
    network_name: str,
    capabilities: list[str],
    host: str,
    port: int,
    private_key: nacl.signing.SigningKey,
    scheme: str = "ws",
    metadata: Optional[dict] = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> AgentDescriptor:
    """Construct an ``AgentDescriptor`` and sign it with the node's private key."""
    now = datetime.now(timezone.utc)
    descriptor = AgentDescriptor(
        agent_id=agent_id,
        node_public_key=node_public_key,
        network_name=network_name,
        capabilities=list(capabilities),
        endpoint=AgentEndpoint(host=host, port=port, scheme=scheme),
        registered_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
        metadata=metadata or {},
    )
    descriptor.signatures.append(
        sign_model(descriptor, private_key, key_id=node_public_key)
    )
    return descriptor


def register_descriptor(na_endpoint: str, descriptor: AgentDescriptor, timeout: float = 10.0) -> dict:
    """POST a signed descriptor to the NA. Raises on non-2xx."""
    url = f"{na_endpoint.rstrip('/')}/agents"
    payload = descriptor.model_dump(mode="json")
    response = requests.post(url, json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def deregister(
    *,
    na_endpoint: str,
    node_public_key: str,
    private_key: nacl.signing.SigningKey,
    timeout: float = 10.0,
) -> bool:
    """Voluntary deregistration — signs a small envelope and DELETEs the entry."""
    signed_at = datetime.now(timezone.utc).isoformat()
    envelope = f"delete-agent|v1|{node_public_key}|{signed_at}".encode("utf-8")
    signature = sign_data(envelope, private_key)
    url = f"{na_endpoint.rstrip('/')}/agents/{node_public_key}"
    response = requests.delete(
        url,
        json={"version": "v1", "signed_at": signed_at, "signature": signature},
        timeout=timeout,
    )
    if response.status_code == 404:
        return False
    response.raise_for_status()
    return True


def discover(
    na_endpoint: str,
    capability: Optional[str] = None,
    timeout: float = 10.0,
) -> list[AgentDescriptor]:
    """Query the NA for live registrations, optionally filtered by capability."""
    url = f"{na_endpoint.rstrip('/')}/agents"
    params = {"capability": capability} if capability else {}
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return [AgentDescriptor.model_validate(entry) for entry in response.json().get("agents", [])]


async def run_registration_loop(
    *,
    na_endpoint: str,
    agent_id: str,
    node_public_key: str,
    network_name: str,
    capabilities: list[str],
    host: str,
    port: int,
    private_key: nacl.signing.SigningKey,
    scheme: str = "ws",
    metadata: Optional[dict] = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    refresh_seconds: int = DEFAULT_REFRESH_SECONDS,
) -> None:
    """Register once, then refresh on the configured interval until cancelled."""
    while True:
        descriptor = build_signed_descriptor(
            agent_id=agent_id,
            node_public_key=node_public_key,
            network_name=network_name,
            capabilities=capabilities,
            host=host,
            port=port,
            private_key=private_key,
            scheme=scheme,
            metadata=metadata,
            ttl_seconds=ttl_seconds,
        )
        try:
            await asyncio.to_thread(register_descriptor, na_endpoint, descriptor)
            logger.info(
                "Registered agent %s | capabilities=%s | expires_at=%s",
                agent_id,
                capabilities,
                descriptor.expires_at.isoformat(),
            )
        except Exception:
            logger.exception("Agent registration failed; will retry on next interval")

        try:
            await asyncio.sleep(refresh_seconds)
        except asyncio.CancelledError:
            break
