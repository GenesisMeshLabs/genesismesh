"""GenesisGuard daemon — local enforcement sidecar (v0.45).

Listens on a TCP localhost port (or Unix socket where available) for
ExecutionMediationRequests.  Validates authorization artifacts, spawns
subprocess with constrained environment, issues MediatedExecutionReceipt.

NOT an LLM.  Does not reason about requests.  Enforces mechanically.

IMPORTANT: See docs/examples/process-level-mediation.md for the distinction
between advisory mode and mandatory mediation mode.  This daemon alone does not
provide mandatory mediation — the deployment environment must also restrict
agent direct subprocess access.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import threading
from datetime import datetime, timezone
from typing import Any

import nacl.signing

from ..models.context import BoundaryDecision
from ..models.mediation import (
    ExecutionMediationRequest,
    MediatedExecutionReceipt,
    MediationRejection,
)
from ..trust.mediation import (
    EVAL_FLAGS,
    create_mediated_execution_receipt,
    parse_allowlist_entry,
    validate_command_allowlist,
    validate_mediation_request,
)

logger = logging.getLogger(__name__)

_RECV_SIZE = 65536


class GenesisGuardDaemon:
    """Local enforcement sidecar.  Non-LLM, deterministic, no network access.

    Listens on a TCP localhost port for ExecutionMediationRequests.
    Validates authorization artifacts, spawns subprocess with constrained
    environment, issues MediatedExecutionReceipt.
    """

    def __init__(
        self,
        guard_sovereign_id: str,
        signing_key: nacl.signing.SigningKey,
        decision_store: dict[str, BoundaryDecision],
        agent_public_keys: dict[str, list[str]],
        *,
        operator_public_keys: dict[str, list[str]] | None = None,
        token_issuer_public_keys: dict[str, list[str]] | None = None,
        command_allowlist: list[str] | None = None,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        # Refuse to start without an enforceable allowlist.  An absent allowlist
        # used to mean "allow anything"; it now means the guard does not run.
        validate_command_allowlist(command_allowlist)
        for entry in command_allowlist or []:
            fixed, is_prefix = parse_allowlist_entry(entry)
            if is_prefix and fixed[-1] in EVAL_FLAGS:
                logger.warning(
                    "Guard: allowlist entry %r is a prefix rule ending in %r, which "
                    "permits arbitrary code through that interpreter",
                    entry,
                    fixed[-1],
                )

        self.guard_sovereign_id = guard_sovereign_id
        self.signing_key = signing_key
        self.decision_store = decision_store
        self.agent_public_keys = agent_public_keys
        self.operator_public_keys = operator_public_keys or {}
        self.token_issuer_public_keys = token_issuer_public_keys or {}
        self.command_allowlist = command_allowlist
        # F-01: invocation-token use counts, keyed by token_id.  In-process
        # only: the guard has no durable store, so a token's max_invocations
        # budget is enforced for this guard's lifetime and the count resets
        # when it restarts.  Documented, not silently ignored.
        self._token_use_counts: dict[str, int] = {}
        self.host = host
        self.port = port
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self.host, self.port))
        self.port = self._server.getsockname()[1]  # capture actual port
        self._server.listen(5)
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        logger.info("GenesisGuard listening on %s:%d", self.host, self.port)

    def stop(self) -> None:
        self._running = False
        if self._server:
            self._server.close()
        logger.info("GenesisGuard stopped")

    def _serve(self) -> None:
        assert self._server is not None
        while self._running:
            try:
                conn, _ = self._server.accept()
            except OSError:
                break
            threading.Thread(target=self._handle_conn, args=(conn,), daemon=True).start()

    def _handle_conn(self, conn: socket.socket) -> None:
        with conn:
            try:
                raw = conn.recv(_RECV_SIZE)
                data = json.loads(raw)
                request = ExecutionMediationRequest.model_validate(data)
                response = self.handle_request(request)
                conn.sendall(response.model_dump_json().encode())
            except Exception as exc:  # noqa: BLE001
                logger.warning("Guard: request handling error: %s", exc)
                rejection = MediationRejection(
                    request_id=data.get("request_id", "unknown") if "data" in dir() else "unknown",
                    agent_sovereign_id="unknown",
                    rejected_at=datetime.now(timezone.utc),
                    reason="subprocess_blocked",
                    detail=str(exc),
                )
                try:
                    conn.sendall(rejection.model_dump_json().encode())
                except OSError:
                    pass

    def handle_request(
        self,
        request: ExecutionMediationRequest,
    ) -> MediatedExecutionReceipt | MediationRejection:
        """Validate and execute, or reject."""
        now = datetime.now(timezone.utc)
        decision = self.decision_store.get(request.decision_id)
        agent_keys = self.agent_public_keys.get(request.agent_sovereign_id, [])
        # Keyed by the operator the decision claims to be from, so the signature
        # is checked against that operator's key rather than any known key.
        operator_keys = (
            self.operator_public_keys.get(decision.operator_sovereign_id, [])
            if decision is not None
            else []
        )

        token = request.invocation_token
        use_count = self._token_use_counts.get(token.token_id, 0) if token else 0

        ok, reason = validate_mediation_request(
            request,
            decision,
            agent_keys,
            operator_public_keys=operator_keys,
            token_issuer_public_keys=self.token_issuer_public_keys,
            command_allowlist=self.command_allowlist,
            use_count=use_count,
            at_time=now,
        )

        if not ok:
            logger.warning(
                "Guard rejected %s for %s: %s",
                request.requested_capability,
                request.agent_sovereign_id,
                reason,
            )
            return MediationRejection(
                request_id=request.request_id,
                agent_sovereign_id=request.agent_sovereign_id,
                rejected_at=now,
                reason=reason or "subprocess_blocked",
            )

        # The request is authorised, so this counts against the token's budget.
        # Counted here rather than after the spawn: a command that starts and
        # then fails has still consumed an invocation.
        if token is not None:
            self._token_use_counts[token.token_id] = use_count + 1

        # Build constrained environment
        allowed = set(request.allowed_env_vars)
        env = {k: v for k, v in os.environ.items() if k in allowed}

        try:
            with subprocess.Popen(  # noqa: S603
                request.subprocess_command,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ) as proc:
                pid = proc.pid
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    return MediationRejection(
                        request_id=request.request_id,
                        agent_sovereign_id=request.agent_sovereign_id,
                        rejected_at=now,
                        reason="subprocess_blocked",
                        detail="subprocess timeout",
                    )
                exit_code = proc.returncode
            receipt = create_mediated_execution_receipt(
                request,
                subprocess_pid=pid,
                guard_sovereign_id=self.guard_sovereign_id,
                signing_key=self.signing_key,
                exit_code=exit_code,
                now=now,
            )
            logger.info(
                "Guard mediated %s for %s: pid=%d exit=%d",
                request.requested_capability,
                request.agent_sovereign_id,
                proc.pid,
                proc.returncode,
            )
            return receipt
        except Exception as exc:  # noqa: BLE001
            return MediationRejection(
                request_id=request.request_id,
                agent_sovereign_id=request.agent_sovereign_id,
                rejected_at=now,
                reason="subprocess_blocked",
                detail=str(exc),
            )
