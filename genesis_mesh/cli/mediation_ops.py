"""CLI commands for Process-Level Execution Mediation.

trust guard request  -- submit a mediation request to GenesisGuard
trust guard verify   -- verify a signed MediatedExecutionReceipt
trust guard start    -- start a GenesisGuard daemon
"""

from __future__ import annotations

import base64
import json
import socket
from datetime import datetime, timezone
from pathlib import Path

import click
import nacl.signing

from ..crypto import load_private_key, verify_model_signature
from ..models.mediation import (
    ExecutionMediationRequest,
    MediatedExecutionReceipt,
    MediationRejection,
)


@click.group("guard")
def guard() -> None:
    """GenesisGuard — process-level execution mediation sidecar."""


# ---------------------------------------------------------------------------
# request
# ---------------------------------------------------------------------------


@guard.command("request")
@click.option("--capability", "capability", required=True)
@click.option("--decision", "decision_path", required=True, type=click.Path(exists=True))
@click.option("--token", "token_path", default=None, type=click.Path(exists=True))
@click.option("--command", "command", required=True, multiple=True,
              help="Subprocess command (pass once per arg).")
@click.option("--allow-env", "allow_env", multiple=True,
              help="Env var key to allow in subprocess.")
@click.option("--signing-key", "key_path", required=True, type=click.Path(exists=True))
@click.option("--socket-host", "host", default="127.0.0.1")
@click.option("--socket-port", "port", type=int, required=True)
@click.option("--output", "output_path", required=True, type=click.Path())
def request_cmd(
    capability: str, decision_path: str, token_path: str | None,
    command: tuple[str, ...], allow_env: tuple[str, ...],
    key_path: str, host: str, port: int, output_path: str,
) -> None:
    """Submit an ExecutionMediationRequest to a running GenesisGuard daemon."""
    from ..crypto import sign_model  # noqa: PLC0415
    from ..models.context import BoundaryDecision  # noqa: PLC0415

    sk = load_private_key(key_path)
    decision = BoundaryDecision.model_validate_json(
        Path(decision_path).read_text(encoding="utf-8")
    )
    token_id: str | None = None
    if token_path:
        from ..models.invocation_token import InvocationToken  # noqa: PLC0415
        tok = InvocationToken.model_validate_json(
            Path(token_path).read_text(encoding="utf-8")
        )
        token_id = tok.token_id

    req = ExecutionMediationRequest(
        agent_sovereign_id=decision.operator_sovereign_id,
        requested_capability=capability,
        decision_id=decision.decision_id,
        token_id=token_id,
        subprocess_command=list(command),
        allowed_env_vars=list(allow_env),
        requested_at=datetime.now(timezone.utc),
    )
    sig = sign_model(req, sk, req.agent_sovereign_id)
    req = req.model_copy(update={"signature": sig})

    raw = req.model_dump_json().encode()
    with socket.create_connection((host, port), timeout=10) as sock:
        sock.sendall(raw)
        response_raw = b""
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            response_raw += chunk

    Path(output_path).write_text(response_raw.decode(), encoding="utf-8")

    # Determine response type
    try:
        receipt = MediatedExecutionReceipt.model_validate_json(response_raw)
        click.echo(f"[OK] MediatedExecutionReceipt {receipt.receipt_id}")
        click.echo(f"     Capability : {receipt.capability}")
        click.echo(f"     PID        : {receipt.subprocess_pid}")
        click.echo(f"     Exit code  : {receipt.subprocess_exit_code}")
    except Exception:  # noqa: BLE001
        rejection = MediationRejection.model_validate_json(response_raw)
        click.echo(f"[FAIL] Rejected: {rejection.reason}", err=True)
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------


@guard.command("verify")
@click.option("--receipt", "receipt_path", required=True, type=click.Path(exists=True))
@click.option("--guard-key", "guard_key_b64", required=True,
              help="Guard's Ed25519 public key (base64).")
@click.option("--format", "fmt", type=click.Choice(["human", "json"]), default="human")
def verify_cmd(receipt_path: str, guard_key_b64: str, fmt: str) -> None:
    """Verify a signed MediatedExecutionReceipt."""
    receipt = MediatedExecutionReceipt.model_validate_json(
        Path(receipt_path).read_text(encoding="utf-8")
    )
    if receipt.signature is None:
        _fail(fmt, "missing_signature")
        raise SystemExit(1)

    pub = nacl.signing.VerifyKey(base64.b64decode(guard_key_b64))
    if not verify_model_signature(receipt, receipt.signature, pub):
        _fail(fmt, "invalid_signature")
        raise SystemExit(1)

    if fmt == "json":
        click.echo(json.dumps({"valid": True, "reason": "valid"}, indent=2))
    else:
        click.echo(f"[OK] valid — {receipt.receipt_id}")


def _fail(fmt: str, reason: str) -> None:
    if fmt == "json":
        click.echo(json.dumps({"valid": False, "reason": reason}, indent=2))
    else:
        click.echo(f"[FAIL] {reason}", err=True)


# ---------------------------------------------------------------------------
# start (foreground, for use as a service wrapper)
# ---------------------------------------------------------------------------


@guard.command("start")
@click.option("--guard-sovereign", "guard_id", required=True)
@click.option("--signing-key", "key_path", required=True, type=click.Path(exists=True))
@click.option("--port", "port", type=int, default=0)
@click.option("--host", "host", default="127.0.0.1")
@click.option("--command-allowlist", "allowlist", default=None,
              help="Comma-separated list of allowed executable names.")
def start_cmd(guard_id: str, key_path: str, port: int, host: str,
              allowlist: str | None) -> None:
    """Start GenesisGuard daemon (foreground; Ctrl-C to stop)."""
    from ..guard.daemon import GenesisGuardDaemon  # noqa: PLC0415

    sk = load_private_key(key_path)
    cmd_list = allowlist.split(",") if allowlist else None
    daemon = GenesisGuardDaemon(
        guard_sovereign_id=guard_id,
        signing_key=sk,
        decision_store={},
        agent_public_keys={},
        command_allowlist=cmd_list,
        host=host,
        port=port,
    )
    daemon.start()
    click.echo(f"[OK] GenesisGuard listening on {host}:{daemon.port}")
    click.echo("     Press Ctrl-C to stop.")
    try:
        import time  # noqa: PLC0415
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        daemon.stop()
        click.echo("\n[OK] GenesisGuard stopped.")
