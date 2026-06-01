"""Researcher agent: sends one question over the mesh and prints the answer.

Run:

    python researcher.py \\
        --na https://na.genesismesh.connectorzzz.com \\
        --config ~/.genesis-mesh-researcher/config.toml \\
        --to-agent kb-1 \\
        --destination-key <DESTINATION_NODE_PUBLIC_KEY> \\
        --via ws://4.223.130.190:7443 \\
        "what protocol secures peer sessions?"

The researcher enrolls once (operator provides --invite-token on first run),
opens a Noise XX session through the given peer endpoint, sends an
``AgentRequest``, waits for the matching ``AgentResponse`` on the same
authenticated connection, and prints the answer and provenance.
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


def _resolve_via_discovery(na_endpoint: str, capability: str) -> dict:
    """Query the NA discovery API for a live agent advertising ``capability``.

    Returns a flat dict with ``agent_id``, ``node_public_key``, ``endpoint_uri``,
    and ``capabilities``. Picks the most recently registered match.
    """
    import requests

    url = f"{na_endpoint.rstrip('/')}/agents"
    resp = requests.get(url, params={"capability": capability}, timeout=10)
    resp.raise_for_status()
    payload = resp.json()
    agents = payload.get("agents") or []
    if not agents:
        raise RuntimeError(f"no agent advertises capability {capability!r}")
    entry = agents[0]  # most-recently-registered first
    ep = entry.get("endpoint", {})
    scheme = ep.get("scheme", "ws")
    return {
        "agent_id": entry.get("agent_id"),
        "node_public_key": entry.get("node_public_key"),
        "endpoint_uri": f"{scheme}://{ep.get('host')}:{ep.get('port')}",
        "capabilities": entry.get("capabilities", []),
    }


async def ask_one_question(
    na_endpoint: str,
    config_path: Path,
    to_agent: str,
    destination_node_public_key: str,
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
        recipient_id=destination_node_public_key,
        data=request.to_bytes(),
    )
    logger.info(
        "[%s] sending question to %s: %r",
        request.request_id,
        to_agent,
        question,
    )
    await transport.send(outbound.to_bytes())

    response = await asyncio.wait_for(
        _wait_for_response(transport, request.request_id),
        timeout=timeout,
    )
    await transport.close()
    return response


async def _wait_for_response(transport, expected_request_id: str) -> AgentResponse:
    """Read inbound frames until an AgentResponse matches the request id."""
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


def _print_response(question: str, response: AgentResponse) -> None:
    """Print a response with the recorded workflow provenance."""
    print()
    print(f"Q: {question}")
    print(f"A: {response.answer}")
    print(f"  from:    {response.from_agent}")
    print(f"  source:  {response.source}")
    print(f"  request: {response.request_id}")
    if response.provenance:
        print("  provenance:")
        for step in response.provenance:
            print(
                "    - {agent}: {action} ({detail})".format(
                    agent=step.get("agent", "unknown"),
                    action=step.get("action", "step"),
                    detail=step.get("detail", ""),
                )
            )


def main():
    """Run the researcher CLI."""
    parser = argparse.ArgumentParser(description="Researcher agent for Genesis Mesh")
    parser.add_argument("--na", required=True, help="Network Authority URL")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument(
        "--to-agent",
        default=None,
        help=(
            "Logical id of the responder, e.g. kb-1. Optional when --capability is set "
            "(the discovered agent's id is used)."
        ),
    )
    parser.add_argument(
        "--destination-key",
        default=None,
        help="Destination node public key (base64, from the responder certificate)",
    )
    parser.add_argument(
        "--kb-key",
        default=None,
        help="Deprecated alias for --destination-key",
    )
    parser.add_argument(
        "--via",
        default=None,
        help=(
            "Peer WebSocket endpoint of any reachable router (e.g. ws://host:port). "
            "Optional when --capability is set — the NA discovery API will resolve it."
        ),
    )
    parser.add_argument(
        "--capability",
        default=None,
        help=(
            "Discover a responder advertising this capability. "
            "When provided, --to-agent / --destination-key / --via become optional."
        ),
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

    destination_key = args.destination_key or args.kb_key
    via_endpoint = args.via
    to_agent = args.to_agent

    if args.capability:
        try:
            resolved = _resolve_via_discovery(args.na, args.capability)
        except Exception as exc:
            parser.error(f"discovery for capability {args.capability!r} failed: {exc}")
        logger.info(
            "Discovered %s at %s (capabilities=%s)",
            resolved["agent_id"],
            resolved["endpoint_uri"],
            resolved["capabilities"],
        )
        destination_key = destination_key or resolved["node_public_key"]
        via_endpoint = via_endpoint or resolved["endpoint_uri"]
        to_agent = to_agent or resolved["agent_id"]

    if not destination_key:
        parser.error(
            "one of --destination-key / --kb-key / --capability is required"
        )
    if not via_endpoint:
        parser.error(
            "--via is required when --capability is not set (or did not return an endpoint)"
        )
    if not to_agent:
        parser.error("--to-agent is required when --capability is not set")

    response = asyncio.run(
        ask_one_question(
            na_endpoint=args.na,
            config_path=args.config,
            to_agent=to_agent,
            destination_node_public_key=destination_key,
            via_peer_endpoint=via_endpoint,
            question=args.question,
            agent_id=args.agent_id,
            invite_token=args.invite_token,
            timeout=args.timeout,
        )
    )

    _print_response(args.question, response)


if __name__ == "__main__":
    main()
