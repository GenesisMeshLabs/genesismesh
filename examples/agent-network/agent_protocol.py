"""Small JSON envelope for agent-to-agent communication over Genesis Mesh.

The Genesis Mesh transport already provides authentication (Noise XX),
encryption (AESGCM session keys), and identity (Ed25519 join certificates).
This module only adds *agent semantics* on top of the DATA frame — a request
envelope and a response envelope — so the receiver knows what to do with the
bytes.

There is no application-level signing here. The cryptographic guarantee
"this message arrived over an authenticated session with a peer whose join
certificate the Network Authority signed" is already provided by the mesh.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Optional


PROTOCOL_VERSION = 1


@dataclass
class AgentRequest:
    """A question or instruction from one agent to another."""

    question: str
    from_agent: str
    to_agent: str
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    sent_at: float = field(default_factory=time.time)
    version: int = PROTOCOL_VERSION
    type: str = "ask"

    def to_bytes(self) -> bytes:
        return json.dumps(asdict(self)).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> AgentRequest:
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
    source: str  # how the responder produced the answer (e.g. "knowledge.json", "llm:claude-sonnet")
    sent_at: float = field(default_factory=time.time)
    version: int = PROTOCOL_VERSION
    type: str = "answer"

    def to_bytes(self) -> bytes:
        return json.dumps(asdict(self)).encode("utf-8")

    @classmethod
    def from_bytes(cls, data: bytes) -> AgentResponse:
        payload = json.loads(data.decode("utf-8"))
        if payload.get("type") != "answer":
            raise ValueError(f"Not an AgentResponse: type={payload.get('type')!r}")
        return cls(**{k: v for k, v in payload.items() if k in cls.__dataclass_fields__})


def parse_envelope(data: bytes) -> Optional[AgentRequest | AgentResponse]:
    """Return the right envelope type, or None if the bytes are not an agent message."""
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
    return None
