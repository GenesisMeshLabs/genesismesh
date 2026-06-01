"""Planner agent that orchestrates capabilities across Genesis Mesh."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_protocol import (  # noqa: E402
    CapabilityRequest,
    CapabilityResponse,
    append_capability_step,
    parse_envelope,
)
from capability_providers import provider_uri, select_provider  # noqa: E402

from genesis_mesh.crypto import KeyPair, generate_keypair, load_private_key, save_keypair  # noqa: E402
from genesis_mesh.models import AgentDescriptor, GenesisBlock, JoinCertificate  # noqa: E402
from genesis_mesh.node.discovery_client import discover, run_registration_loop  # noqa: E402
from genesis_mesh.node.node import MeshNode  # noqa: E402
from genesis_mesh.node.runtime import MeshNodeRuntime  # noqa: E402


logger = logging.getLogger("agent.planner")


class CapabilityUnavailable(RuntimeError):
    """Raised when no trusted provider can satisfy a capability."""


class ProviderInvocationError(CapabilityUnavailable):
    """Raised when a selected provider cannot complete an invocation."""

    def __init__(self, provider: AgentDescriptor, reason: str):
        """Keep the selected provider available for deterministic retry."""
        super().__init__(f"{provider.agent_id} failed: {reason}")
        self.provider = provider
        self.reason = reason


async def run_planner_agent(
    na_endpoint: str,
    config_path: Path,
    listen_port: int,
    agent_id: str,
    invite_token: str | None,
    announce_host: str = "127.0.0.1",
    provider_timeout: float = 25.0,
):
    """Enroll, advertise ``planner.answer``, and orchestrate provider calls."""
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

    inbound: list[tuple[str, CapabilityRequest]] = []
    pending_provider_responses: dict[str, asyncio.Future[CapabilityResponse]] = {}

    async def on_data_received(message):
        envelope = parse_envelope(_decoded_payload(message))
        if isinstance(envelope, CapabilityRequest):
            if envelope.to_agent == agent_id and envelope.capability == "planner.answer":
                inbound.append((message.sender_id, envelope))
            return
        if isinstance(envelope, CapabilityResponse):
            future = pending_provider_responses.get(envelope.request_id)
            if future and not future.done():
                future.set_result(envelope)

    runtime = MeshNodeRuntime(
        node,
        na_endpoint,
        listen_host="0.0.0.0",
        listen_port=listen_port,
        on_data_received=on_data_received,
        max_peer_connections=100,
    )

    await runtime.start()
    logger.info(
        "Planner agent %s online | listening on :%s | identity prefix %s",
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
            capabilities=["planner.answer"],
            host=announce_host,
            port=runtime.bound_port or listen_port,
            private_key=node_keypair.private_key,
            metadata={"capabilities": [{"name": "planner.answer", "version": "1.0"}]},
        )
    )

    async def invoke_provider(
        capability: str,
        arguments: dict,
        trace: list[dict],
        exclude: set[str] | None = None,
    ) -> tuple[CapabilityResponse, AgentDescriptor]:
        """Discover, select, connect to, and invoke one provider."""
        descriptors = await asyncio.to_thread(discover, na_endpoint, capability)
        provider = select_provider(descriptors, capability, exclude_node_keys=exclude)
        try:
            await runtime._connect_endpoint(provider_uri(provider))
        except Exception as exc:
            raise ProviderInvocationError(provider, f"connect failed: {exc.__class__.__name__}") from exc

        request = CapabilityRequest(
            capability=capability,
            arguments=arguments,
            from_agent=agent_id,
            to_agent=provider.agent_id,
            trace=append_capability_step(
                trace,
                agent_id,
                "discovered",
                capability,
                f"selected provider {provider.agent_id}",
            ),
        )
        loop = asyncio.get_running_loop()
        future: asyncio.Future[CapabilityResponse] = loop.create_future()
        pending_provider_responses[request.request_id] = future
        ok = await runtime.router.send_to(provider.node_public_key, request.to_bytes())
        if not ok:
            pending_provider_responses.pop(request.request_id, None)
            raise ProviderInvocationError(provider, "no route")
        try:
            response = await asyncio.wait_for(future, timeout=provider_timeout)
        except Exception as exc:
            raise ProviderInvocationError(provider, exc.__class__.__name__) from exc
        finally:
            pending_provider_responses.pop(request.request_id, None)
        return response, provider

    async def answer(request: CapabilityRequest) -> CapabilityResponse:
        """Execute the narrow planner.answer flow."""
        question = str(request.arguments.get("question") or "")
        repo = str(request.arguments.get("repo") or "thaersaidi/genesismesh")
        trace = list(request.trace)

        repo_response: CapabilityResponse | None = None
        repo_provider: AgentDescriptor | None = None
        excluded_repo_providers: set[str] = set()
        last_error = ""
        for _ in range(2):
            try:
                repo_response, repo_provider = await invoke_provider(
                    "repo.summary",
                    {"repo": repo, "question": question},
                    trace,
                    exclude=excluded_repo_providers,
                )
                break
            except ProviderInvocationError as exc:
                last_error = exc.reason
                excluded_repo_providers.add(exc.provider.node_public_key)
            except Exception as exc:
                last_error = exc.__class__.__name__
        if repo_response is None:
            raise CapabilityUnavailable(f"repo.summary unavailable: {last_error}")

        llm_response, _ = await invoke_provider(
            "llm.chat",
            {
                "question": (
                    "Use the repository summary to answer this request. "
                    f"Question: {question}\n"
                    f"Repository summary: {repo_response.result.get('summary', '')}"
                ),
            },
            repo_response.provenance,
        )

        repo_summary = str(repo_response.result.get("summary", ""))
        llm_answer = str(llm_response.result.get("answer", ""))
        answer_text = (
            f"{repo_summary}\n\nPlanner synthesis: {llm_answer}"
            if repo_summary and llm_answer
            else repo_summary or llm_answer
        )
        provenance = append_capability_step(
            llm_response.provenance,
            agent_id,
            "combined",
            "planner.answer",
            "repo.summary + llm.chat",
        )
        return CapabilityResponse(
            capability="planner.answer",
            provider=agent_id,
            result={
                "answer": answer_text,
                "sources": [repo_response.provider, llm_response.provider],
            },
            from_agent=agent_id,
            to_agent=request.from_agent,
            request_id=request.request_id,
            provenance=provenance,
        )

    try:
        while True:
            while inbound:
                requester_node_id, request = inbound.pop(0)
                try:
                    response = await answer(request)
                except Exception as exc:
                    logger.warning("[%s] planner failed: %s", request.request_id, exc)
                    response = CapabilityResponse(
                        capability=request.capability,
                        provider=agent_id,
                        result={"error": exc.__class__.__name__, "message": str(exc)},
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
                ok = await runtime.router.send_to(requester_node_id, response.to_bytes())
                if ok:
                    logger.info("[%s] returned planner.answer to %s", request.request_id, requester_node_id[:16])
                else:
                    logger.warning("[%s] no route to requester; answer dropped", request.request_id)
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
    """Run the planner agent CLI."""
    parser = argparse.ArgumentParser(description="Planner capability orchestrator")
    parser.add_argument("--na", required=True, help="Network Authority URL")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--listen-port", type=int, default=7452)
    parser.add_argument("--agent-id", default="planner-1")
    parser.add_argument("--invite-token", default=None)
    parser.add_argument("--announce-host", default="127.0.0.1")
    parser.add_argument("--provider-timeout", type=float, default=25.0)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    asyncio.run(
        run_planner_agent(
            na_endpoint=args.na,
            config_path=args.config,
            listen_port=args.listen_port,
            agent_id=args.agent_id,
            invite_token=args.invite_token,
            announce_host=args.announce_host,
            provider_timeout=args.provider_timeout,
        )
    )


if __name__ == "__main__":
    main()
