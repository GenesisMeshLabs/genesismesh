"""Small JSON envelopes for agent-to-agent communication over Genesis Mesh.

The Genesis Mesh transport already provides authentication (Noise XX),
encryption (AESGCM session keys), and identity (Ed25519 join certificates).
This module only adds agent semantics on top of the DATA frame: request and
response envelopes, trace entries, and provenance fields.

There is no application-level signing here. The cryptographic guarantee
"this message arrived over an authenticated session with a peer whose join
certificate the Network Authority signed" is already provided by the mesh.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Optional


PROTOCOL_VERSION = 1


@dataclass
class AgentRequest:
    """A question or instruction from one agent to another."""

    question: str
    from_agent: str
    to_agent: str
    origin_agent: Optional[str] = None
    trace: list[dict[str, Any]] = field(default_factory=list)
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    sent_at: float = field(default_factory=time.time)
    version: int = PROTOCOL_VERSION
    type: str = "ask"

    def to_bytes(self) -> bytes:
        """Serialize the request as UTF-8 JSON."""
        return json.dumps(asdict(self)).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> AgentRequest:
        """Parse a request envelope from UTF-8 JSON bytes."""
        payload = json.loads(data.decode("utf-8"))
        if payload.get("type") != "ask":
            raise ValueError(f"Not an AgentRequest: type={payload.get('type')!r}")
        return cls(**{k: v for k, v in payload.items() if k in cls.__dataclass_fields__})


@dataclass
class AgentResponse:
    """A reply produced by the recipient agent."""

    answer: str
    from_agent: str
    to_agent: str
    request_id: str
    source: str
    provenance: list[dict[str, Any]] = field(default_factory=list)
    sent_at: float = field(default_factory=time.time)
    version: int = PROTOCOL_VERSION
    type: str = "answer"

    def to_bytes(self) -> bytes:
        """Serialize the response as UTF-8 JSON."""
        return json.dumps(asdict(self)).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> AgentResponse:
        """Parse a response envelope from UTF-8 JSON bytes."""
        payload = json.loads(data.decode("utf-8"))
        if payload.get("type") != "answer":
            raise ValueError(f"Not an AgentResponse: type={payload.get('type')!r}")
        return cls(**{k: v for k, v in payload.items() if k in cls.__dataclass_fields__})


@dataclass(frozen=True)
class CapabilityMetadata:
    """Minimal advertised metadata for an executable capability."""

    name: str
    version: str = "1.0"

    @classmethod
    def normalize(cls, value: str | dict[str, Any] | "CapabilityMetadata") -> "CapabilityMetadata":
        """Return metadata from a string, dict, or existing metadata object."""
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            name = value.strip()
            if not name:
                raise ValueError("Capability name cannot be empty")
            return cls(name=name)
        name = str(value.get("name", "")).strip()
        version = str(value.get("version", "1.0")).strip() or "1.0"
        if not name:
            raise ValueError("Capability metadata requires name")
        return cls(name=name, version=version)

    def to_advertised_name(self) -> str:
        """Return the capability tag used by the existing discovery registry."""
        return self.name

    def to_dict(self) -> dict[str, str]:
        """Return JSON-safe metadata."""
        return asdict(self)


@dataclass
class CapabilityRequest:
    """Request execution of a named capability from a trusted provider."""

    capability: str
    arguments: dict[str, Any]
    from_agent: str
    to_agent: str
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace: list[dict[str, Any]] = field(default_factory=list)
    sent_at: float = field(default_factory=time.time)
    version: int = PROTOCOL_VERSION
    type: str = "capability_request"

    def to_bytes(self) -> bytes:
        """Serialize the request as UTF-8 JSON."""
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> "CapabilityRequest":
        """Parse a capability request envelope from UTF-8 JSON bytes."""
        payload = json.loads(data.decode("utf-8"))
        if payload.get("type") != "capability_request":
            raise ValueError(f"Not a CapabilityRequest: type={payload.get('type')!r}")
        if not payload.get("capability"):
            raise ValueError("CapabilityRequest requires capability")
        if not isinstance(payload.get("arguments"), dict):
            raise ValueError("CapabilityRequest arguments must be an object")
        return cls(**{k: v for k, v in payload.items() if k in cls.__dataclass_fields__})


@dataclass
class CapabilityResponse:
    """Result produced by a capability provider with traceable provenance."""

    capability: str
    provider: str
    result: dict[str, Any]
    from_agent: str
    to_agent: str
    request_id: str
    provenance: list[dict[str, Any]] = field(default_factory=list)
    sent_at: float = field(default_factory=time.time)
    version: int = PROTOCOL_VERSION
    type: str = "capability_response"

    def to_bytes(self) -> bytes:
        """Serialize the response as UTF-8 JSON."""
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> "CapabilityResponse":
        """Parse a capability response envelope from UTF-8 JSON bytes."""
        payload = json.loads(data.decode("utf-8"))
        if payload.get("type") != "capability_response":
            raise ValueError(f"Not a CapabilityResponse: type={payload.get('type')!r}")
        if not payload.get("capability"):
            raise ValueError("CapabilityResponse requires capability")
        if not payload.get("provider"):
            raise ValueError("CapabilityResponse requires provider")
        if not isinstance(payload.get("result"), dict):
            raise ValueError("CapabilityResponse result must be an object")
        return cls(**{k: v for k, v in payload.items() if k in cls.__dataclass_fields__})


Envelope = AgentRequest | AgentResponse | CapabilityRequest | CapabilityResponse


def parse_envelope(data: bytes) -> Optional[Envelope]:
    """Return the right envelope type, or None if bytes are not an agent message."""
    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception:
        return None

    if payload.get("version") != PROTOCOL_VERSION:
        return None

    kind = payload.get("type")
    if kind == "ask":
        return AgentRequest.from_bytes(data)
    if kind == "answer":
        return AgentResponse.from_bytes(data)
    if kind == "capability_request":
        return CapabilityRequest.from_bytes(data)
    if kind == "capability_response":
        return CapabilityResponse.from_bytes(data)
    return None


def trace_step(agent_id: str, action: str, detail: str) -> dict[str, Any]:
    """Return a compact provenance entry for a workflow hop."""
    return {
        "agent": agent_id,
        "action": action,
        "detail": detail,
        "at": time.time(),
    }


def append_trace(
    existing: list[dict[str, Any]] | None,
    agent_id: str,
    action: str,
    detail: str,
) -> list[dict[str, Any]]:
    """Return a new trace list with one additional workflow step."""
    return list(existing or []) + [trace_step(agent_id, action, detail)]


def append_capability_step(
    existing: list[dict[str, Any]] | None,
    agent_id: str,
    action: str,
    capability: str,
    detail: str = "",
) -> list[dict[str, Any]]:
    """Return a new provenance list with one capability-aware step."""
    step: dict[str, Any] = {
        "agent": agent_id,
        "action": action,
        "capability": capability,
        "at": time.time(),
    }
    if detail:
        step["detail"] = detail
    return list(existing or []) + [step]
