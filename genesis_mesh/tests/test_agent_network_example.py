"""Tests for the agent-network example envelopes and router workflow helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


EXAMPLE_DIR = Path(__file__).resolve().parents[2] / "examples" / "agent-network"
sys.path.insert(0, str(EXAMPLE_DIR))

from agent_protocol import (  # noqa: E402
    AgentRequest,
    AgentResponse,
    CapabilityMetadata,
    CapabilityRequest,
    CapabilityResponse,
    append_capability_step,
    append_trace,
    parse_envelope,
)
from capability_providers import ProviderRegistry, select_provider  # noqa: E402
from genesis_mesh.models import AgentDescriptor, AgentEndpoint  # noqa: E402
from router_agent import (  # noqa: E402
    KnowledgeTarget,
    build_forwarded_request,
    build_return_response,
    parse_keyword_rules,
    select_target,
)


class EchoProvider:
    """Small provider used to test local dispatch."""

    metadata = CapabilityMetadata("echo.value")

    async def execute(self, arguments: dict) -> dict:
        """Return the input value."""
        return {"value": arguments["value"]}


def test_agent_request_and_response_preserve_trace_and_provenance():
    """Envelope roundtrips keep request trace and answer provenance."""
    trace = append_trace(None, "router-1", "routed", "researcher-1 -> kb-security")
    request = AgentRequest(
        question="how does revocation work?",
        from_agent="router-1",
        to_agent="kb-security",
        origin_agent="researcher-1",
        trace=trace,
        request_id="req-1",
    )

    parsed_request = parse_envelope(request.to_bytes())
    assert isinstance(parsed_request, AgentRequest)
    assert parsed_request.origin_agent == "researcher-1"
    assert parsed_request.trace[0]["agent"] == "router-1"

    response = AgentResponse(
        answer="Use a signed CRL.",
        from_agent="kb-security",
        to_agent="router-1",
        request_id="req-1",
        source="knowledge.json",
        provenance=append_trace(parsed_request.trace, "kb-security", "answered", "knowledge.json"),
    )

    parsed_response = parse_envelope(response.to_bytes())
    assert isinstance(parsed_response, AgentResponse)
    assert [step["agent"] for step in parsed_response.provenance] == [
        "router-1",
        "kb-security",
    ]


def test_router_selects_target_with_keyword_rules():
    """The router picks the matching knowledge agent and falls back deterministically."""
    targets = {
        "kb-security": KnowledgeTarget("kb-security", "node-security"),
        "kb-transport": KnowledgeTarget("kb-transport", "node-transport"),
    }
    rules = parse_keyword_rules(["revocation=kb-security", "noise=kb-transport"])

    assert select_target("how does revocation work?", targets, rules).agent_id == "kb-security"
    assert select_target("what secures Noise sessions?", targets, rules).agent_id == "kb-transport"
    assert select_target("unknown topic", targets, rules).agent_id == "kb-security"


def test_router_preserves_request_id_origin_and_answer_provenance():
    """A routed workflow keeps identity and provenance across both hops."""
    target = KnowledgeTarget("kb-security", "node-security")
    original = AgentRequest(
        question="how does revocation work?",
        from_agent="researcher-1",
        to_agent="router-1",
        request_id="req-42",
    )

    forwarded = build_forwarded_request(original, "router-1", target)
    assert forwarded.request_id == "req-42"
    assert forwarded.from_agent == "router-1"
    assert forwarded.to_agent == "kb-security"
    assert forwarded.origin_agent == "researcher-1"
    assert forwarded.trace[-1]["action"] == "routed"

    kb_response = AgentResponse(
        answer="The NA publishes a signed CRL.",
        from_agent="kb-security",
        to_agent="router-1",
        request_id="req-42",
        source="knowledge.json",
        provenance=append_trace(forwarded.trace, "kb-security", "answered", "knowledge.json"),
    )
    returned = build_return_response(kb_response, "researcher-1", "router-1")

    assert returned.request_id == "req-42"
    assert returned.from_agent == "kb-security"
    assert returned.to_agent == "researcher-1"
    assert [step["agent"] for step in returned.provenance] == [
        "router-1",
        "kb-security",
        "router-1",
    ]


def test_capability_request_and_response_roundtrip():
    """Capability envelopes roundtrip and preserve provenance."""
    request = CapabilityRequest(
        capability="planner.answer",
        arguments={"question": "why discovery?"},
        from_agent="researcher-1",
        to_agent="planner-1",
        request_id="cap-1",
        trace=append_capability_step(None, "researcher-1", "requested", "planner.answer"),
    )

    parsed_request = parse_envelope(request.to_bytes())
    assert isinstance(parsed_request, CapabilityRequest)
    assert parsed_request.capability == "planner.answer"
    assert parsed_request.arguments["question"] == "why discovery?"

    response = CapabilityResponse(
        capability="planner.answer",
        provider="planner-1",
        result={"answer": "Discovery removes hardcoded provider wiring."},
        from_agent="planner-1",
        to_agent="researcher-1",
        request_id="cap-1",
        provenance=append_capability_step(
            parsed_request.trace,
            "planner-1",
            "combined",
            "planner.answer",
        ),
    )

    parsed_response = parse_envelope(response.to_bytes())
    assert isinstance(parsed_response, CapabilityResponse)
    assert parsed_response.result["answer"].startswith("Discovery")
    assert [step["agent"] for step in parsed_response.provenance] == [
        "researcher-1",
        "planner-1",
    ]


def test_capability_metadata_normalizes_strings_and_dicts():
    """Capability metadata stays intentionally small in v0.8."""
    assert CapabilityMetadata.normalize("repo.summary").to_dict() == {
        "name": "repo.summary",
        "version": "1.0",
    }
    assert CapabilityMetadata.normalize({"name": "llm.chat", "version": "2"}).name == "llm.chat"


def test_capability_envelopes_reject_missing_required_fields():
    """Capability envelopes reject invalid required fields early."""
    bad_request = json.dumps(
        {
            "type": "capability_request",
            "version": 1,
            "capability": "",
            "arguments": {},
        }
    ).encode()
    bad_response = json.dumps(
        {
            "type": "capability_response",
            "version": 1,
            "capability": "planner.answer",
            "provider": "",
            "result": {},
        }
    ).encode()

    with pytest.raises(ValueError, match="requires capability"):
        parse_envelope(bad_request)
    with pytest.raises(ValueError, match="requires provider"):
        parse_envelope(bad_response)


async def test_provider_registry_dispatches_by_capability():
    """The example provider registry dispatches by capability name."""
    registry = ProviderRegistry.from_providers([EchoProvider()])

    assert registry.advertised_names() == ["echo.value"]
    assert registry.advertised_metadata() == [{"name": "echo.value", "version": "1.0"}]
    assert await registry.execute("echo.value", {"value": "ok"}) == {"value": "ok"}
    with pytest.raises(ValueError, match="unknown capability"):
        await registry.execute("unknown.value", {})


def _descriptor(agent_id: str, node_key: str, capabilities: list[str]) -> AgentDescriptor:
    """Build a minimal descriptor for deterministic selection tests."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    return AgentDescriptor(
        agent_id=agent_id,
        node_public_key=node_key,
        network_name="TEST",
        capabilities=capabilities,
        endpoint=AgentEndpoint(host="127.0.0.1", port=7443),
        registered_at=now,
        expires_at=now + timedelta(minutes=10),
    )


def test_select_provider_is_deterministic_and_filters_exclusions():
    """Multiple providers are selected by stable agent identity ordering."""
    providers = [
        _descriptor("repo-b", "node-b", ["repo.summary"]),
        _descriptor("repo-a", "node-a", ["repo.summary"]),
        _descriptor("llm-1", "node-llm", ["llm.chat"]),
    ]

    selected = select_provider(providers, "repo.summary")
    assert selected.agent_id == "repo-a"

    alternate = select_provider(providers, "repo.summary", exclude_node_keys={"node-a"})
    assert alternate.agent_id == "repo-b"

    with pytest.raises(ValueError, match="no provider available"):
        select_provider(providers, "repo.summary", exclude_node_keys={"node-a", "node-b"})
