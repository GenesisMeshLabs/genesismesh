"""Researcher agent — sends one question over the mesh and prints the answer.

Run:

    python researcher.py \\
        --na https://na.genesismesh.connectorzzz.com \\
        --config ~/.genesis-mesh-researcher/config.toml \\
        --to-agent kb-1 \\
        --kb-key <KNOWLEDGE_BASE_NODE_PUBLIC_KEY> \\
        --via ws://4.223.130.190:7443 \\
        "what protocol secures peer sessions?"

The researcher enrols once (operator provides --invite-token on first run),
opens a Noise XX session through the given peer endpoint, sends an
``AgentRequest``, waits for the matching ``AgentResponse`` on the same
authenticated connection, and prints the answer.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_protocol import AgentRequest, AgentResponse, parse_envelope  # noqa: E402

from genesis_mesh.crypto import KeyPair, generate_keypair, load_private_key, save_keypair  # noqa: E402
from genesis_mesh.models import GenesisBlock, JoinCertificate  # noqa: E402
from genesis_mesh.node.node import MeshNode  # noqa: E402
from genesis_mesh.transport import connect_websocket_with_noise  # noqa: E402
from genesis_mesh.transport.noise_handshake import NoiseHandshake  # noqa: E402
from genesis_mesh.transport.protocol import MeshMessage, MessageType, create_data_message  # noqa: E402


logger = logging.getLogger("agent.researcher")


async def ask_one_question(
    na_endpoint: str,
    config_path: Path,
    to_agent: str,
    kb_node_public_key: str,
    via_peer_endpoint: str,
    question: str,
    agent_id: str,
    invite_token: str | None,
    timeout: float,
):
    """Ask one question and return the response, or raise on timeout."""

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
        private_key = node_keypair.private_key

    # Resolve genesis from the NA if we don't have one yet.
    genesis_path = home / "genesis.signed.json"
    if not genesis_path.exists():
        import requests
        resp = requests.get(f"{na_endpoint.rstrip('/')}/genesis", timeout=10)
        resp.raise_for_status()
        genesis_path.write_text(json.dumps(resp.json(), indent=2), encoding="utf-8")
    genesis = GenesisBlock(**json.loads(genesis_path.read_text(encoding="utf-8")))

    node = MeshNode(genesis_block=genesis, node_keypair=node_keypair, roles=["role:client"])

    if cert_path.exists():
        cert = JoinCertificate.model_validate_json(cert_path.read_text(encoding="utf-8"))
        node.join_certificate = cert
    else:
        if not invite_token:
            raise SystemExit(
                "No local certificate and no --invite-token. "
                "Get a token from `genesis-mesh admin invite` first."
            )
        cert = node.join_network(na_endpoint, validity_hours=24, invite_token=invite_token)
        cert_path.write_text(cert.model_dump_json(indent=2), encoding="utf-8")

    local_cert_b64 = base64.b64encode(cert.model_dump_json().encode()).decode()
    noise_keypair = NoiseHandshake.keypair_from_join_cert_key(private_key)

    uri = via_peer_endpoint if via_peer_endpoint.startswith("ws") else f"ws://{via_peer_endpoint}"
    logger.info("Opening Noise XX session to %s", uri)
    transport, _, _ = await connect_websocket_with_noise(uri, noise_keypair, local_cert_b64)

    request = AgentRequest(question=question, from_agent=agent_id, to_agent=to_agent)
    outbound = create_data_message(
        sender_id=node_keypair.public_key_b64,
        recipient_id=kb_node_public_key,
        data=request.to_bytes(),
    )
    logger.info("[%s] sending question to %s: %r",
                request.request_id, to_agent, question)
    await transport.send(outbound.to_bytes())

    response = await asyncio.wait_for(
        _wait_for_response(transport, request.request_id),
        timeout=timeout,
    )
    await transport.close()
    return response


async def _wait_for_response(transport, expected_request_id: str) -> AgentResponse:
    """Read inbound frames until we see an AgentResponse matching our request id."""
    while True:
        data = await transport.receive()
        if data is None:
            raise RuntimeError("Peer closed the connection before answering")
        try:
            mesh_message = MeshMessage.from_bytes(data)
        except Exception:
            continue
        if mesh_message.message_type != MessageType.DATA:
            continue
        encoded = mesh_message.payload.get("data", "")
        try:
            inner = base64.b64decode(encoded)
        except Exception:
            continue
        envelope = parse_envelope(inner)
        if isinstance(envelope, AgentResponse) and envelope.request_id == expected_request_id:
            return envelope


def main():
    parser = argparse.ArgumentParser(description="Researcher agent for Genesis Mesh")
    parser.add_argument("--na", required=True, help="Network Authority URL")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--to-agent", required=True, help="Logical id of the responder, e.g. kb-1")
    parser.add_argument(
        "--kb-key", required=True,
        help="Knowledge-base node's public key (base64, as it appears in /nodes)",
    )
    parser.add_argument(
        "--via", required=True,
        help="Peer WebSocket endpoint of any reachable router, e.g. ws://4.223.130.190:7443",
    )
    parser.add_argument("--agent-id", default="researcher-1")
    parser.add_argument("--invite-token", default=None)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("question", help="The question to ask")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    response = asyncio.run(
        ask_one_question(
            na_endpoint=args.na,
            config_path=args.config,
            to_agent=args.to_agent,
            kb_node_public_key=args.kb_key,
            via_peer_endpoint=args.via,
            question=args.question,
            agent_id=args.agent_id,
            invite_token=args.invite_token,
            timeout=args.timeout,
        )
    )

    print()
    print(f"Q: {args.question}")
    print(f"A: {response.answer}")
    print(f"  from:    {response.from_agent}")
    print(f"  source:  {response.source}")
    print(f"  request: {response.request_id}")


if __name__ == "__main__":
    main()
