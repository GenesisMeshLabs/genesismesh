"""Argparse entry point for enrolling and running a Genesis Mesh node."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging

from ..crypto import KeyPair, load_private_key
from ..models import GenesisBlock
from ..node.node import MeshNode
from ..node.runtime import MeshNodeRuntime
from ..observability import configure_logging


logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the node command parser."""
    parser = argparse.ArgumentParser(description="Genesis Mesh Node")
    parser.add_argument(
        "--genesis",
        required=True,
        help="Path to signed genesis block JSON",
    )
    parser.add_argument(
        "--node-key",
        help="Path to node private key (generates new if not provided)",
    )
    parser.add_argument(
        "--bootstrap",
        required=True,
        help="Network Authority endpoint for bootstrap",
    )
    parser.add_argument(
        "--role",
        action="append",
        dest="roles",
        help="Node roles (can be specified multiple times)",
    )
    parser.add_argument(
        "--validity-hours",
        type=int,
        default=168,
        help="Certificate validity hours",
    )
    parser.add_argument(
        "--invite-token",
        help="Invite token for permissioned enrollment",
    )
    parser.add_argument(
        "--listen-host",
        default="0.0.0.0",
        help="P2P listen host for persistent runtime",
    )
    parser.add_argument(
        "--listen-port",
        type=int,
        default=0,
        help="P2P listen port for persistent runtime",
    )
    parser.add_argument(
        "--persistent",
        action="store_true",
        help="Run in persistent mode with heartbeats",
    )
    parser.add_argument(
        "--heartbeat-interval",
        type=int,
        default=30,
        help="Heartbeat interval in seconds (default: 30)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode",
    )
    return parser


def _load_genesis(path: str) -> GenesisBlock:
    """Load a signed genesis block from disk."""
    with open(path, "r", encoding="utf-8") as f:
        return GenesisBlock(**json.load(f))


def _load_node_keypair(path: str | None) -> KeyPair | None:
    """Load an optional node keypair from a private-key file."""
    if not path:
        logger.info("Generating new node keypair")
        return None

    private_key = load_private_key(path)
    logger.info("Loaded node key from %s", path)
    return KeyPair(
        private_key=private_key,
        public_key=private_key.verify_key,
    )


def _normalize_roles(raw_roles: list[str] | None) -> list[str]:
    """Normalize role arguments to the `role:*` format."""
    if not raw_roles:
        return ["role:client"]
    return [
        role if role.startswith("role:") else f"role:{role}"
        for role in raw_roles
    ]


async def _run_runtime(node: MeshNode, args: argparse.Namespace) -> None:
    """Run the async mesh runtime until interrupted."""
    runtime = MeshNodeRuntime(
        node,
        na_endpoint=args.bootstrap,
        listen_host=args.listen_host,
        listen_port=args.listen_port,
    )
    await runtime.start()
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        await runtime.stop()


def main(argv: list[str] | None = None) -> int:
    """Run the node CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    configure_logging(debug=args.debug)

    genesis_block = _load_genesis(args.genesis)
    node = MeshNode(
        genesis_block=genesis_block,
        node_keypair=_load_node_keypair(args.node_key),
        roles=_normalize_roles(args.roles),
    )

    try:
        node.join_network(args.bootstrap, args.validity_hours, args.invite_token)
        node.fetch_policy(args.bootstrap)

        print("\n=== Node Status ===")
        for key, value in node.get_status().items():
            print(f"{key}: {value}")

        logger.info("Node successfully joined the network")

        if args.persistent:
            print("\n=== Running in persistent mode (Ctrl+C to stop) ===")
            asyncio.run(_run_runtime(node, args))
    except Exception as exc:
        logger.error("Failed to join network: %s", exc)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
