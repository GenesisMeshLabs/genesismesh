"""LLM-backed responder agent for Genesis Mesh.

The mesh layer is unchanged from ``knowledge_base.py``: enrol once, listen on
a peer WebSocket port, receive ``AgentRequest`` envelopes, return
``AgentResponse`` envelopes. The only difference is the answer function — it
calls an LLM via `LiteLLM <https://docs.litellm.ai/>`_ instead of looking up
a JSON file.

LiteLLM gives a single async interface across ~100 providers. The provider
is selected entirely through environment variables; this agent has no
provider-specific code at all.

Required env vars:

  LLM_MODEL          Provider-prefixed model name, e.g.
                     - ``openai/gpt-4o-mini``           (OpenAI)
                     - ``azure/gpt-4o-mini``            (Azure OpenAI v1 endpoint)
                     - ``anthropic/claude-sonnet-4-6``  (Anthropic)
                     - ``ollama/llama3.1``              (local Ollama, no key)
                     - ``mistral/mistral-small-latest`` (Mistral)
                     - ``groq/llama-3.1-70b-versatile`` (Groq)
                     - ``openai/<model>`` with ``LLM_BASE_URL`` for vLLM, LM Studio, Together, etc.

Optional env vars:

  LLM_API_KEY        Required for any cloud provider; unset for Ollama.
  LLM_BASE_URL       Override for non-default endpoints (Azure, local, proxy).
  LLM_MAX_TOKENS     Default: 1024
  LLM_TEMPERATURE    Default: 0.7
  LLM_SYSTEM_PROMPT  Default: "You are an agent on a Genesis Mesh network. Be concise and factual."

Adding a new provider means changing ``LLM_MODEL`` and (sometimes)
``LLM_BASE_URL`` — no code change.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Make sibling modules importable when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_protocol import (  # noqa: E402
    AgentRequest,
    AgentResponse,
    CapabilityRequest,
    CapabilityResponse,
    append_capability_step,
    append_trace,
    parse_envelope,
)

from genesis_mesh.crypto import KeyPair, generate_keypair, load_private_key, save_keypair  # noqa: E402
from genesis_mesh.models import GenesisBlock, JoinCertificate  # noqa: E402
from genesis_mesh.node.discovery_client import run_registration_loop  # noqa: E402
from genesis_mesh.node.node import MeshNode  # noqa: E402
from genesis_mesh.node.runtime import MeshNodeRuntime  # noqa: E402


logger = logging.getLogger("agent.llm")

DEFAULT_SYSTEM_PROMPT = (
    "You are an agent on a Genesis Mesh network. Be concise and factual."
)


def _llm_config_from_env() -> dict:
    """Read LiteLLM configuration from environment variables.

    Raises SystemExit with a clear message if the required vars are missing.
    """
    model = os.environ.get("LLM_MODEL")
    if not model:
        raise SystemExit(
            "LLM_MODEL is not set. Example values: 'openai/gpt-4o-mini', "
            "'azure/gpt-4o-mini', 'anthropic/claude-sonnet-4-6', 'ollama/llama3.1'."
        )
    config: dict = {
        "model": model,
        "max_tokens": int(os.environ.get("LLM_MAX_TOKENS", "1024")),
        "temperature": float(os.environ.get("LLM_TEMPERATURE", "0.7")),
        "system_prompt": os.environ.get("LLM_SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT),
    }
    if os.environ.get("LLM_API_KEY"):
        config["api_key"] = os.environ["LLM_API_KEY"]
    if os.environ.get("LLM_BASE_URL"):
        config["api_base"] = os.environ["LLM_BASE_URL"]
    return config


async def ask_llm(question: str, llm_config: dict) -> tuple[str, str]:
    """Send a question to the configured LLM and return (answer, source_label).

    The source label is provider-prefixed (e.g. ``llm:azure/gpt-4o-mini``) so
    the receiving agent can record provenance without inspecting headers.
    """
    import litellm

    response = await litellm.acompletion(
        model=llm_config["model"],
        messages=[
            {"role": "system", "content": llm_config["system_prompt"]},
            {"role": "user", "content": question},
        ],
        api_key=llm_config.get("api_key"),
        api_base=llm_config.get("api_base"),
        max_tokens=llm_config["max_tokens"],
        temperature=llm_config["temperature"],
    )
    answer = response.choices[0].message.content or ""
    return answer.strip(), f"llm:{llm_config['model']}"


async def run_llm_agent(
    na_endpoint: str,
    config_path: Path,
    listen_port: int,
    agent_id: str,
    invite_token: str | None,
    announce_host: str = "127.0.0.1",
    capabilities: list[str] | None = None,
):
    """Enrol if needed, start the peer runtime, answer questions via LiteLLM."""
    llm_config = _llm_config_from_env()
    logger.info(
        "LLM ready | model=%s | base=%s | max_tokens=%d",
        llm_config["model"],
        llm_config.get("api_base") or "<provider default>",
        llm_config["max_tokens"],
    )

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
        genesis_path.write_text(__import__("json").dumps(resp.json(), indent=2), encoding="utf-8")
    genesis = GenesisBlock(
        **__import__("json").loads(genesis_path.read_text(encoding="utf-8"))
    )

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

    # Pending work queued from inbound callbacks, processed in the main loop.
    pending_work: list[tuple[str, AgentRequest | CapabilityRequest]] = []

    async def on_data_received(message):
        envelope = parse_envelope(_decoded_payload(message))
        if envelope is None or not isinstance(envelope, (AgentRequest, CapabilityRequest)):
            return
        if envelope.to_agent != agent_id:
            logger.info("Ignored request addressed to %s (we are %s)", envelope.to_agent, agent_id)
            return
        question = (
            envelope.question
            if isinstance(envelope, AgentRequest)
            else str(envelope.arguments.get("question") or envelope.arguments.get("prompt") or "")
        )
        logger.info(
            "[%s] received request from %s: %r",
            envelope.request_id,
            envelope.from_agent,
            question,
        )
        pending_work.append((message.sender_id, envelope))

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

    # Announce this agent's capabilities to the NA so peers can discover it.
    effective_capabilities = list(
        capabilities or ["llm.chat", "llm:chat", f"llm:{llm_config['model']}"]
    )
    registration_task = asyncio.create_task(
        run_registration_loop(
            na_endpoint=na_endpoint,
            agent_id=agent_id,
            node_public_key=runtime.node_id,
            network_name=genesis.network_name,
            capabilities=effective_capabilities,
            host=announce_host,
            port=runtime.bound_port or listen_port,
            private_key=node_keypair.private_key,
            metadata={
                "model": llm_config["model"],
                "capabilities": [{"name": "llm.chat", "version": "1.0"}],
            },
        )
    )

    try:
        while True:
            while pending_work:
                recipient_id, request = pending_work.pop(0)
                question = (
                    request.question
                    if isinstance(request, AgentRequest)
                    else str(request.arguments.get("question") or request.arguments.get("prompt") or "")
                )
                try:
                    answer, source = await ask_llm(question, llm_config)
                except Exception as exc:
                    logger.exception("LLM call failed for %s", request.request_id)
                    answer = f"LLM provider error: {exc.__class__.__name__}"
                    source = f"llm:{llm_config['model']}:error"

                if isinstance(request, CapabilityRequest):
                    response = CapabilityResponse(
                        capability=request.capability,
                        provider=agent_id,
                        result={"answer": answer, "source": source},
                        from_agent=agent_id,
                        to_agent=request.from_agent,
                        request_id=request.request_id,
                        provenance=append_capability_step(
                            request.trace,
                            agent_id,
                            "executed",
                            request.capability,
                            source,
                        ),
                    )
                else:
                    response = AgentResponse(
                        answer=answer,
                        from_agent=agent_id,
                        to_agent=request.from_agent,
                        request_id=request.request_id,
                        source=source,
                        provenance=append_trace(request.trace, agent_id, "answered", source),
                    )
                ok = await runtime.router.send_to(recipient_id, response.to_bytes())
                if ok:
                    logger.info(
                        "[%s] sent answer to %s (source=%s)",
                        response.request_id,
                        recipient_id[:16],
                        source,
                    )
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
    """Run the LLM-backed responder agent CLI."""
    parser = argparse.ArgumentParser(description="LLM-backed responder agent for Genesis Mesh")
    parser.add_argument("--na", required=True, help="Network Authority URL")
    parser.add_argument("--config", required=True, type=Path, help="Path to per-agent config TOML")
    parser.add_argument("--listen-port", type=int, default=7448, help="Peer WebSocket port")
    parser.add_argument("--agent-id", default="llm-1", help="Identifier used inside agent envelopes")
    parser.add_argument(
        "--invite-token",
        default=None,
        help="Invite token (only for first enrollment)",
    )
    parser.add_argument(
        "--announce-host",
        default="127.0.0.1",
        help="Host other peers should connect to when discovering this agent",
    )
    parser.add_argument(
        "--capability",
        action="append",
        default=None,
        help="Capability tag to advertise (repeatable). Default: llm:chat + llm:<model>",
    )
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    asyncio.run(
        run_llm_agent(
            na_endpoint=args.na,
            config_path=args.config,
            listen_port=args.listen_port,
            agent_id=args.agent_id,
            invite_token=args.invite_token,
            announce_host=args.announce_host,
            capabilities=args.capability,
        )
    )


if __name__ == "__main__":
    main()
