"""Knowledge-base agent: a long-running mesh node that answers questions.

Run:

    python knowledge_base.py \\
        --na https://na.genesismesh.connectorzzz.com \\
        --config ~/.genesis-mesh-kb/config.toml \\
        --listen-port 7445 \\
        --agent-id kb-1 \\
        --knowledge ./knowledge.json

The agent enrolls (or reuses an existing certificate), starts a peer runtime,
and listens for AgentRequest messages addressed to it. Each request is matched
against a JSON knowledge file. The response is sent back over the mesh.

The default responder is a simple keyword lookup. Swap ``answer_question`` to
plug in an LLM call, a database query, or an MCP tool invocation. The mesh
layer does not change.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Make sibling modules importable when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_protocol import AgentRequest, AgentResponse, append_trace, parse_envelope  # noqa: E402

from genesis_mesh.crypto import KeyPair, generate_keypair, load_private_key, save_keypair  # noqa: E402
from genesis_mesh.models import GenesisBlock, JoinCertificate  # noqa: E402
from genesis_mesh.node.node import MeshNode  # noqa: E402
from genesis_mesh.node.runtime import MeshNodeRuntime  # noqa: E402


logger = logging.getLogger("agent.knowledge_base")


def answer_question(
    question: str,
    knowledge: dict,
    source_name: str = "knowledge.json",
) -> tuple[str, str]:
    """Match a question against the loaded knowledge file."""
    normalized = question.lower().strip().rstrip("?").strip()
    for key, value in knowledge.items():
        if key == "default answer":
            continue
        if key in normalized or normalized in key:
            return value, source_name
    return knowledge.get("default answer", "No answer available."), f"{source_name}:default"


async def run_knowledge_base(
    na_endpoint: str,
    config_path: Path,
    listen_port: int,
    agent_id: str,
    knowledge_path: Path,
    invite_token: str | None,
):
    """Enroll if needed, start the peer runtime, and answer AgentRequest messages."""
    knowledge = json.loads(knowledge_path.read_text(encoding="utf-8"))
    logger.info("Loaded %d knowledge entries from %s", len(knowledge), knowledge_path)

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

    pending_responses: list[tuple[str, AgentResponse]] = []

    async def on_data_received(message):
        envelope = parse_envelope(_decoded_payload(message))
        if envelope is None:
            logger.debug("Ignored DATA frame (not an agent envelope)")
            return
        if not isinstance(envelope, AgentRequest):
            return
        if envelope.to_agent != agent_id:
            logger.info(
                "Ignored question addressed to %s (we are %s)",
                envelope.to_agent,
                agent_id,
            )
            return

        logger.info(
            "[%s] received question from %s: %r",
            envelope.request_id,
            envelope.from_agent,
            envelope.question,
        )

        answer, source = answer_question(envelope.question, knowledge, knowledge_path.name)
        response = AgentResponse(
            answer=answer,
            from_agent=agent_id,
            to_agent=envelope.from_agent,
            request_id=envelope.request_id,
            source=source,
            provenance=append_trace(envelope.trace, agent_id, "answered", source),
        )
        pending_responses.append((message.sender_id, response))

    runtime = MeshNodeRuntime(
        node,
        na_endpoint,
        listen_host="0.0.0.0",
        listen_port=listen_port,
        on_data_received=on_data_received,
    )

    await runtime.start()
    logger.info(
        "Agent %s online | listening on :%s | identity prefix %s",
        agent_id,
        runtime.bound_port,
        runtime.node_id[:16],
    )

    try:
        while True:
            while pending_responses:
                recipient_id, response = pending_responses.pop(0)
                ok = await runtime.router.send_to(recipient_id, response.to_bytes())
                if ok:
                    logger.info("[%s] sent answer to %s", response.request_id, recipient_id[:16])
                else:
                    logger.warning(
                        "[%s] no route to %s; answer dropped",
                        response.request_id,
                        recipient_id[:16],
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
    """Run the knowledge-base agent CLI."""
    parser = argparse.ArgumentParser(description="Knowledge-base agent for Genesis Mesh")
    parser.add_argument("--na", required=True, help="Network Authority URL")
    parser.add_argument("--config", required=True, type=Path, help="Path to per-agent config TOML")
    parser.add_argument("--listen-port", type=int, default=7445, help="Peer WebSocket port")
    parser.add_argument("--agent-id", default="kb-1", help="Identifier used inside agent envelopes")
    parser.add_argument(
        "--knowledge",
        type=Path,
        default=Path(__file__).resolve().parent / "knowledge.json",
        help="Path to the JSON knowledge file",
    )
    parser.add_argument("--invite-token", default=None, help="Invite token (only for first enrollment)")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    asyncio.run(
        run_knowledge_base(
            na_endpoint=args.na,
            config_path=args.config,
            listen_port=args.listen_port,
            agent_id=args.agent_id,
            knowledge_path=args.knowledge,
            invite_token=args.invite_token,
        )
    )


if __name__ == "__main__":
    main()
