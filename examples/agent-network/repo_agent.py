"""Read-only repository summary capability provider for Genesis Mesh."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_protocol import (  # noqa: E402
    CapabilityMetadata,
    CapabilityRequest,
    CapabilityResponse,
    append_capability_step,
    parse_envelope,
)
from capability_providers import ProviderRegistry  # noqa: E402

from genesis_mesh.crypto import KeyPair, generate_keypair, load_private_key, save_keypair  # noqa: E402
from genesis_mesh.models import GenesisBlock, JoinCertificate  # noqa: E402
from genesis_mesh.node.discovery_client import run_registration_loop  # noqa: E402
from genesis_mesh.node.node import MeshNode  # noqa: E402
from genesis_mesh.node.runtime import MeshNodeRuntime  # noqa: E402


logger = logging.getLogger("agent.repo")


class RepoSummaryProvider:
    """Summarize a repository from a local read-only JSON fixture."""

    metadata = CapabilityMetadata(name="repo.summary", version="1.0")

    def __init__(self, fixture_path: Path):
        """Load deterministic repo summary data."""
        self.fixture_path = fixture_path
        self.fixture = json.loads(fixture_path.read_text(encoding="utf-8"))

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Return a repository summary result."""
        requested_repo = str(arguments.get("repo") or self.fixture.get("repo") or "unknown")
        return {
            "repo": requested_repo,
            "summary": self.fixture.get("summary", ""),
            "signals": list(self.fixture.get("signals", [])),
            "source": self.fixture_path.name,
        }


async def run_repo_agent(
    na_endpoint: str,
    config_path: Path,
    listen_port: int,
    agent_id: str,
    invite_token: str | None,
    fixture_path: Path,
    announce_host: str = "127.0.0.1",
):
    """Enroll, register ``repo.summary``, and answer capability requests."""
    provider = RepoSummaryProvider(fixture_path)
    registry = ProviderRegistry.from_providers([provider])

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

    pending: list[tuple[str, CapabilityRequest]] = []

    async def on_data_received(message):
        envelope = parse_envelope(_decoded_payload(message))
        if not isinstance(envelope, CapabilityRequest):
            return
        if envelope.to_agent != agent_id:
            return
        pending.append((message.sender_id, envelope))

    runtime = MeshNodeRuntime(
        node,
        na_endpoint,
        listen_host="0.0.0.0",
        listen_port=listen_port,
        on_data_received=on_data_received,
    )

    await runtime.start()
    logger.info(
        "Repo agent %s online | listening on :%s | identity prefix %s",
        agent_id,
        runtime.bound_port,
        runtime.node_id[:16],
    )

    registration_task = asyncio.create_task(
        run_registration_loop(
            na_endpoint=na_endpoint,
            agent_id=agent_id,
            node_public_key=runtime.node_id,
            network_name=genesis.network_name,
            capabilities=registry.advertised_names(),
            host=announce_host,
            port=runtime.bound_port or listen_port,
            private_key=node_keypair.private_key,
            metadata={"capabilities": registry.advertised_metadata()},
        )
    )

    try:
        while True:
            while pending:
                recipient_id, request = pending.pop(0)
                try:
                    result = await registry.execute(request.capability, request.arguments)
                    provenance = append_capability_step(
                        request.trace,
                        agent_id,
                        "executed",
                        request.capability,
                        result.get("source", fixture_path.name),
                    )
                    response = CapabilityResponse(
                        capability=request.capability,
                        provider=agent_id,
                        result=result,
                        from_agent=agent_id,
                        to_agent=request.from_agent,
                        request_id=request.request_id,
                        provenance=provenance,
                    )
                except Exception as exc:
                    response = CapabilityResponse(
                        capability=request.capability,
                        provider=agent_id,
                        result={"error": exc.__class__.__name__},
                        from_agent=agent_id,
                        to_agent=request.from_agent,
                        request_id=request.request_id,
                        provenance=append_capability_step(
                            request.trace,
                            agent_id,
                            "failed",
                            request.capability,
                            exc.__class__.__name__,
                        ),
                    )
                ok = await runtime.router.send_to(recipient_id, response.to_bytes())
                if ok:
                    logger.info("[%s] returned %s to %s", request.request_id, request.capability, recipient_id[:16])
                else:
                    logger.warning("[%s] no route to %s; response dropped", request.request_id, recipient_id[:16])
            await asyncio.sleep(0.05)
    except KeyboardInterrupt:
        logger.info("Shutting down")
    finally:
        registration_task.cancel()
        try:
            await registration_task
        except asyncio.CancelledError:
            pass
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
    """Run the repository summary provider CLI."""
    parser = argparse.ArgumentParser(description="Repository summary capability provider")
    parser.add_argument("--na", required=True, help="Network Authority URL")
    parser.add_argument("--config", required=True, type=Path, help="Path to per-agent config TOML")
    parser.add_argument("--listen-port", type=int, default=7450, help="Peer WebSocket port")
    parser.add_argument("--agent-id", default="repo-agent-1")
    parser.add_argument("--invite-token", default=None)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path(__file__).resolve().parent / "repo-summary.json",
    )
    parser.add_argument("--announce-host", default="127.0.0.1")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    asyncio.run(
        run_repo_agent(
            na_endpoint=args.na,
            config_path=args.config,
            listen_port=args.listen_port,
            agent_id=args.agent_id,
            invite_token=args.invite_token,
            fixture_path=args.fixture,
            announce_host=args.announce_host,
        )
    )


if __name__ == "__main__":
    main()
