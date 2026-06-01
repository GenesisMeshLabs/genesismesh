"""Tests for the agent-network example envelopes and router workflow helpers."""

from __future__ import annotations

import sys
from pathlib import Path


EXAMPLE_DIR = Path(__file__).resolve().parents[2] / "examples" / "agent-network"
sys.path.insert(0, str(EXAMPLE_DIR))

from agent_protocol import AgentRequest, AgentResponse, append_trace, parse_envelope  # noqa: E402
from router_agent import (  # noqa: E402
    KnowledgeTarget,
    build_forwarded_request,
    build_return_response,
    parse_keyword_rules,
    select_target,
)


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
