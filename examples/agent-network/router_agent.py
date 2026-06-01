"""Router agent: forwards questions to one of several knowledge agents.

The router proves a simple multi-agent pattern:

    researcher -> router -> knowledge agent -> router -> researcher

Each participant keeps its own mesh identity. The router preserves the original
request id and records the routing decision in the request trace. The knowledge
agent appends its answer provenance, and the router appends the return hop
before sending the answer back to the requester.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_protocol import (  # noqa: E402
    AgentRequest,
    AgentResponse,
    append_trace,
    parse_envelope,
)

from genesis_mesh.crypto import KeyPair, generate_keypair, load_private_key, save_keypair  # noqa: E402
from genesis_mesh.models import GenesisBlock, JoinCertificate  # noqa: E402
from genesis_mesh.node.node import MeshNode  # noqa: E402
from genesis_mesh.node.runtime import MeshNodeRuntime  # noqa: E402


logger = logging.getLogger("agent.router")


@dataclass(frozen=True)
class KnowledgeTarget:
    """A knowledge agent that can receive routed requests."""

    agent_id: str
    node_id: str


@dataclass(frozen=True)
class PendingRequest:
    """Original requester state kept while a routed request is in flight."""

    requester_node_id: str
    requester_agent_id: str


def parse_knowledge_targets(values: list[str]) -> dict[str, KnowledgeTarget]:
    """Parse repeated AGENT=NODE_KEY CLI values into router targets."""
    targets: dict[str, KnowledgeTarget] = {}
    for value in values:
        if "=" not in value:
            raise ValueError("--knowledge-agent must use AGENT=NODE_PUBLIC_KEY")
        agent_id, node_id = value.split("=", 1)
        agent_id = agent_id.strip()
        node_id = node_id.strip()
        if not agent_id or not node_id:
            raise ValueError("--knowledge-agent requires non-empty agent and node ids")
        targets[agent_id] = KnowledgeTarget(agent_id=agent_id, node_id=node_id)
    return targets


def parse_keyword_rules(values: list[str]) -> dict[str, str]:
    """Parse repeated KEYWORD=AGENT CLI values into routing rules."""
    rules: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError("--rule must use KEYWORD=AGENT")
        keyword, agent_id = value.split("=", 1)
        keyword = keyword.strip().lower()
        agent_id = agent_id.strip()
        if not keyword or not agent_id:
            raise ValueError("--rule requires non-empty keyword and agent id")
        rules[keyword] = agent_id
    return rules


def select_target(
    question: str,
    targets: dict[str, KnowledgeTarget],
    rules: dict[str, str],
) -> KnowledgeTarget:
    """Select a knowledge agent for a question using simple keyword rules."""
    if not targets:
        raise ValueError("At least one --knowledge-agent is required")

    normalized = question.lower()
    for keyword, agent_id in rules.items():
        if keyword in normalized and agent_id in targets:
            return targets[agent_id]

    first_key = sorted(targets)[0]
    return targets[first_key]


def build_forwarded_request(
    request: AgentRequest,
    router_agent_id: str,
    target: KnowledgeTarget,
) -> AgentRequest:
    """Create a request from the router to the selected knowledge agent."""
    origin_agent = request.origin_agent or request.from_agent
    return AgentRequest(
        question=request.question,
        from_agent=router_agent_id,
        to_agent=target.agent_id,
        origin_agent=origin_agent,
        trace=append_trace(
            request.trace,
            router_agent_id,
            "routed",
            f"{origin_agent} -> {target.agent_id}",
        ),
        request_id=request.request_id,
    )


def build_return_response(
    response: AgentResponse,
    requester_agent_id: str,
    router_agent_id: str,
) -> AgentResponse:
    """Create the response the router sends back to the original requester."""
    return AgentResponse(
        answer=response.answer,
        from_agent=response.from_agent,
        to_agent=requester_agent_id,
        request_id=response.request_id,
        source=response.source,
        provenance=append_trace(
            response.provenance,
            router_agent_id,
            "returned",
            f"{response.from_agent} -> {requester_agent_id}",
        ),
    )


async def run_router_agent(
    na_endpoint: str,
    config_path: Path,
    listen_port: int,
    agent_id: str,
    invite_token: str | None,
    targets: dict[str, KnowledgeTarget],
    rules: dict[str, str],
    bootstrap_peers: list[str] | None = None,
    max_peer_connections: int = 50,
):
    """Enroll if needed, start the runtime, and route agent requests."""
    home = config_path.parent
    home.mkdir(parents=True, exist_ok=True)
    node_key_path = home / "node.key"
    cert_path = home / "node.cert.json"

    if node_key_path.exists():
        private_key = load_private_key(str(node_key_path))
        node_keypair = KeyPair(private_key=private_key, public_key=private_key.verify_key)
    else:
        node_keypair = generate_keypair()
        save_keypair(node_keypair, str(node_key_path.with_suffix("")), agent_id)

    genesis_path = home / "genesis.signed.json"
    if not genesis_path.exists():
        import requests

        resp = requests.get(f"{na_endpoint.rstrip('/')}/genesis", timeout=10)
        resp.raise_for_status()
        genesis_path.write_text(json.dumps(resp.json(), indent=2), encoding="utf-8")
    genesis = GenesisBlock(**json.loads(genesis_path.read_text(encoding="utf-8")))

    node = MeshNode(genesis_block=genesis, node_keypair=node_keypair, roles=["role:anchor"])

    if cert_path.exists():
        node.join_certificate = JoinCertificate.model_validate_json(
            cert_path.read_text(encoding="utf-8")
        )
        logger.info("Reusing existing certificate %s", node.join_certificate.cert_id)
    else:
        if not invite_token:
            raise SystemExit(
                "No local certificate and no --invite-token. "
                "Get a token from `genesis-mesh admin invite` first."
            )
        cert = node.join_network(na_endpoint, validity_hours=168, invite_token=invite_token)
        cert_path.write_text(cert.model_dump_json(indent=2), encoding="utf-8")
        logger.info("Enrolled with new certificate %s", cert.cert_id)

    pending_requests: dict[str, PendingRequest] = {}
    outbound: list[tuple[str, AgentRequest | AgentResponse]] = []

    async def on_data_received(message):
        envelope = parse_envelope(_decoded_payload(message))
        if envelope is None:
            logger.debug("Ignored DATA frame (not an agent envelope)")
            return

        if isinstance(envelope, AgentRequest):
            if envelope.to_agent != agent_id:
                logger.info("Ignored request for %s (we are %s)", envelope.to_agent, agent_id)
                return
            target = select_target(envelope.question, targets, rules)
            pending_requests[envelope.request_id] = PendingRequest(
                requester_node_id=message.sender_id,
                requester_agent_id=envelope.from_agent,
            )
            forwarded = build_forwarded_request(envelope, agent_id, target)
            outbound.append((target.node_id, forwarded))
            logger.info(
                "[%s] routed %s -> %s for question %r",
                envelope.request_id,
                envelope.from_agent,
                target.agent_id,
                envelope.question,
            )
            return

        if isinstance(envelope, AgentResponse):
            pending = pending_requests.pop(envelope.request_id, None)
            if pending is None:
                logger.warning("[%s] response has no pending requester", envelope.request_id)
                return
            returned = build_return_response(
                envelope,
                requester_agent_id=pending.requester_agent_id,
                router_agent_id=agent_id,
            )
            outbound.append((pending.requester_node_id, returned))
            logger.info(
                "[%s] returned answer from %s to %s",
                envelope.request_id,
                envelope.from_agent,
                pending.requester_agent_id,
            )

    runtime = MeshNodeRuntime(
        node,
        na_endpoint,
        listen_host="0.0.0.0",
        listen_port=listen_port,
        bootstrap_peers=bootstrap_peers,
        on_data_received=on_data_received,
        max_peer_connections=max_peer_connections,
    )

    await runtime.start()
    logger.info(
        "Router agent %s online | listening on :%s | identity prefix %s",
        agent_id,
        runtime.bound_port,
        runtime.node_id[:16],
    )

    try:
        while True:
            while outbound:
                destination, envelope = outbound.pop(0)
                ok = await runtime.router.send_to(destination, envelope.to_bytes())
                if not ok:
                    logger.warning(
                        "[%s] no route to %s; routed envelope dropped",
                        envelope.request_id,
                        destination[:16],
                    )
            await asyncio.sleep(0.05)
    except KeyboardInterrupt:
        logger.info("Shutting down")
    finally:
        await runtime.stop()


def _decoded_payload(message) -> bytes:
    """Extract raw application bytes from the mesh DATA payload."""
    import base64

    encoded = message.payload.get("data", "")
    try:
        return base64.b64decode(encoded)
    except Exception:
        return b""


def main():
    """Run the router agent CLI."""
    parser = argparse.ArgumentParser(description="Router agent for Genesis Mesh")
    parser.add_argument("--na", required=True, help="Network Authority URL")
    parser.add_argument("--config", required=True, type=Path, help="Path to per-agent config TOML")
    parser.add_argument("--listen-port", type=int, default=7446, help="Peer WebSocket port")
    parser.add_argument("--agent-id", default="router-1", help="Identifier used inside agent envelopes")
    parser.add_argument(
        "--knowledge-agent",
        action="append",
        default=[],
        metavar="AGENT=NODE_KEY",
        help="Knowledge agent mapping. Repeat for each target.",
    )
    parser.add_argument(
        "--rule",
        action="append",
        default=[],
        metavar="KEYWORD=AGENT",
        help="Keyword routing rule. Repeat for each rule.",
    )
    parser.add_argument(
        "--peer",
        action="append",
        default=[],
        metavar="WS_ENDPOINT",
        help="Peer endpoint to connect during startup. Repeat for each knowledge agent.",
    )
    parser.add_argument("--invite-token", default=None, help="Invite token (only for first enrollment)")
    parser.add_argument(
        "--max-peer-connections",
        type=int,
        default=50,
        help="Maximum simultaneous peer connections for this router runtime",
    )
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    asyncio.run(
        run_router_agent(
            na_endpoint=args.na,
            config_path=args.config,
            listen_port=args.listen_port,
            agent_id=args.agent_id,
            invite_token=args.invite_token,
            targets=parse_knowledge_targets(args.knowledge_agent),
            rules=parse_keyword_rules(args.rule),
            bootstrap_peers=args.peer,
            max_peer_connections=args.max_peer_connections,
        )
    )


if __name__ == "__main__":
    main()
