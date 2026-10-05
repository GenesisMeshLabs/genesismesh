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
from ..models.context import BoundaryDecision
from ..models.mediation import (
    ExecutionMediationRequest,
    MediatedExecutionReceipt,
    MediationRejection,
)
from .support import ensure_parent


@click.group("guard")
def guard() -> None:
    """GenesisGuard — process-level execution mediation sidecar."""


# ---------------------------------------------------------------------------
# request
# ---------------------------------------------------------------------------


@guard.command("request")
@click.option("--capability", "capability", required=True)
@click.option("--decision", "decision_path", required=True, type=click.Path(exists=True))
@click.option("--token", "token_path", default=None, type=click.Path(exists=True),
              help="The agent's signed InvocationToken. Required: the guard will not "
                   "mediate a request that does not carry one.")
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

    sk = load_private_key(key_path)
    decision = BoundaryDecision.model_validate_json(
        Path(decision_path).read_text(encoding="utf-8")
    )
    # F-01: the guard needs the whole signed token, not just its id -- the token
    # is what names the bearer and the capabilities it grants.
    token = None
    if token_path:
        from ..models.invocation_token import InvocationToken  # noqa: PLC0415
        token = InvocationToken.model_validate_json(
            Path(token_path).read_text(encoding="utf-8")
        )
    else:
        raise click.ClickException(
            "--token is required: the guard will not mediate a request without a "
            "signed InvocationToken naming the requesting agent as bearer."
        )

    req = ExecutionMediationRequest(
        agent_sovereign_id=token.bearer_sovereign_id,
        requested_capability=capability,
        decision_id=decision.decision_id,
        token_id=token.token_id,
        invocation_token=token,
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

    ensure_parent(output_path).write_text(response_raw.decode(), encoding="utf-8")

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
              help="Guard's Ed25519 public key: base64 or path to a public key file.")
@click.option("--format", "fmt", type=click.Choice(["human", "json"]), default="human")
def verify_cmd(receipt_path: str, guard_key_b64: str, fmt: str) -> None:
    """Verify a signed MediatedExecutionReceipt."""
    text = Path(receipt_path).read_text(encoding="utf-8")
    try:
        receipt = MediatedExecutionReceipt.model_validate_json(text)
    except ValueError as exc:
        # A refused request writes its rejection to the output file, not a
        # receipt: report that rather than a validation trace (v1.0.2).
        try:
            refused = json.loads(text)
        except ValueError:
            refused = None
        if isinstance(refused, dict) and "rejection_id" in refused:
            if fmt != "json":
                click.echo(f"The file holds a rejection, not a receipt: {refused.get('reason')}", err=True)
            _fail(fmt, "not_a_receipt")
        else:
            _fail(fmt, "malformed_receipt")
        raise SystemExit(1) from exc
    if receipt.signature is None:
        _fail(fmt, "missing_signature")
        raise SystemExit(1)

    pub = nacl.signing.VerifyKey(base64.b64decode(_key_text(guard_key_b64)))
    if not verify_model_signature(receipt, receipt.signature, pub):
        _fail(fmt, "invalid_signature")
        raise SystemExit(1)

    if fmt == "json":
        click.echo(json.dumps({"valid": True, "reason": "valid"}, indent=2))
    else:
        click.echo(f"[OK] valid — {receipt.receipt_id}")


def _key_text(value: str) -> str:
    """A base64 key given inline or as a key file (comment lines ignored)."""
    path = Path(value)
    if path.is_file():
        return "".join(line.strip() for line in path.read_text(encoding="utf-8").splitlines()
                       if line.strip() and not line.startswith("#"))
    return value


def _fail(fmt: str, reason: str) -> None:
    if fmt == "json":
        click.echo(json.dumps({"valid": False, "reason": reason}, indent=2))
    else:
        click.echo(f"[FAIL] {reason}", err=True)


# ---------------------------------------------------------------------------
# start (foreground, for use as a service wrapper)
# ---------------------------------------------------------------------------


def _parse_issuer_keys(specs: tuple[str, ...], option: str = "--token-issuer-key") -> dict[str, list[str]]:
    """Parse ``issuer-id=key-or-path`` specs into the guard's issuer-key map.

    Mirrors the shape used for operator keys elsewhere; a value that names an
    existing file is read from disk, ignoring comment lines.
    """
    keys: dict[str, list[str]] = {}
    for spec in specs:
        if "=" not in spec:
            raise click.ClickException(f"{option} must use id=key-or-path, got {spec!r}")
        issuer_id, value = spec.split("=", 1)
        issuer_id, value = issuer_id.strip(), value.strip()
        if not issuer_id or not value:
            raise click.ClickException(f"{option} id and value must be non-empty")
        path = Path(value)
        if path.exists():
            value = "".join(
                line.strip()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")
            )
        keys.setdefault(issuer_id, []).append(value)
    return keys


@guard.command("start")
@click.option("--guard-sovereign", "guard_id", required=True)
@click.option("--signing-key", "key_path", required=True, type=click.Path(exists=True))
@click.option("--port", "port", type=int, default=0)
@click.option("--host", "host", default="127.0.0.1")
@click.option("--token-issuer-key", "token_issuer_keys", multiple=True,
              help="Invocation-token issuer key as issuer-id=base64-public-key or "
                   "issuer-id=path. Repeatable. Required to mediate any request.")
@click.option("--command-allowlist", "allowlist", multiple=True, required=True,
              help="Allowed command line (pass once per command). Matched against the "
                   "whole command, not the program name. End an entry with '...' to "
                   "allow a variable tail, e.g. 'python /opt/report.py ...'.")
@click.option("--agent-key", "agent_keys", multiple=True,
              help="Agent whose requests the guard accepts, as agent-id=base64-public-key or "
                   "agent-id=path. Repeatable. Required to mediate any request.")
@click.option("--operator-key", "operator_keys", multiple=True,
              help="Operator whose BoundaryDecisions the guard accepts, as operator-id=key-or-path. "
                   "Repeatable. Required to mediate any request.")
@click.option("--decision", "decision_files", multiple=True, type=click.Path(exists=True, dir_okay=False),
              help="Signed BoundaryDecision JSON to load at start. Repeatable.")
@click.option("--decision-dir", "decision_dir", type=click.Path(exists=True, file_okay=False),
              help="Directory of signed BoundaryDecision JSON files, read when a request names "
                   "a decision the guard has not loaded.")
def start_cmd(guard_id: str, key_path: str, port: int, host: str,
              token_issuer_keys: tuple[str, ...], allowlist: tuple[str, ...],
              agent_keys: tuple[str, ...], operator_keys: tuple[str, ...],
              decision_files: tuple[str, ...], decision_dir: str | None) -> None:
    """Start GenesisGuard daemon (foreground; Ctrl-C to stop)."""
    from ..guard.daemon import GenesisGuardDaemon  # noqa: PLC0415

    sk = load_private_key(key_path)
    decisions: dict[str, BoundaryDecision] = {}
    for path in decision_files:
        try:
            decision = BoundaryDecision.model_validate_json(Path(path).read_text(encoding="utf-8"))
        except ValueError as exc:
            raise click.ClickException(f"{path} is not a BoundaryDecision: {exc}") from exc
        decisions[decision.decision_id] = decision
    agents = _parse_issuer_keys(agent_keys, option="--agent-key")
    operators = _parse_issuer_keys(operator_keys, option="--operator-key")
    try:
        daemon = GenesisGuardDaemon(
            guard_sovereign_id=guard_id,
            signing_key=sk,
            decision_store=decisions,
            agent_public_keys=agents,
            operator_public_keys=operators,
            token_issuer_public_keys=_parse_issuer_keys(token_issuer_keys),
            command_allowlist=list(allowlist),
            host=host,
            port=port,
            decision_dir=decision_dir,
        )
    except ValueError as exc:
        click.echo(f"[FAIL] {exc}", err=True)
        raise SystemExit(1) from exc
    # The guard fails closed: without these it can only reject (v1.0.2).
    for missing, option in ((not agents, "--agent-key"), (not operators, "--operator-key"),
                            (not token_issuer_keys, "--token-issuer-key"),
                            (not decisions and not decision_dir, "--decision or --decision-dir")):
        if missing:
            click.echo(f"[WARN] no {option}: the guard will reject every request", err=True)
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
