"""Edge nodes (v1.7.0, Stage 6, beta): NA application logic for the edge agent.

An operator creates an edge invite naming the node's sovereign ID and the
resource prefix its executor key may act on. The node redeems it at /join
with a node key and an executor key; the executor key co-signs the request
(proof of possession) and the NA registers it, as an operator registering
an executor key would. The node then calls the node-scoped routes
(``/node/boundary/evaluate``, ``/node/state``, ``/node/evidence/resource-head``)
with requests its node key signs, bound to a ``purpose`` and the NA
(``audience``). Revoking any certificate of an edge node revokes all of them
in one CRL, retires its executor key and so revokes the grants it bears.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional

from flask import request

from ...crypto import verify_signature
from ...crypto.node_auth import decode_ed25519_public_key, executor_key_id, executor_proof_payload
from ...models import InviteToken, JoinCertificate
from ..auth import _audit_auth_failure, verify_node_request_signature
from ..errors import (
    ApiError,
    BadRequestError,
    ConflictError,
    ForbiddenError,
    UnauthorizedError,
)

if TYPE_CHECKING:
    from ...models.context import BoundaryDecision
    from ..server import NetworkAuthorityService

logger = logging.getLogger(__name__)

#: An edge node's sovereign ID.
NODE_SOVEREIGN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
#: The agent block of a heartbeat: what the NA keeps of it (anything else is dropped).
AGENT_VERSION_MAX = 32
#: A node counts as online while its newest heartbeat is younger than this (as for /nodes).
ONLINE_SECONDS = 300
#: Grants /node/state returns at most, newest first.
STATE_GRANT_LIMIT = 100
#: Edge nodes /admin/edge-nodes lists at most per page, and by default.
MAX_PAGE = 500
DEFAULT_PAGE = 100
EDGE_STATUSES = ("online", "offline", "revoked")
#: The migration that adds edge nodes (019_edge_nodes.sql).
EDGE_SCHEMA_VERSION = 19


def parse_db_datetime(value: str) -> datetime:
    """Parse a persisted ISO datetime and normalize it to UTC."""
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def certificate_time_rejection(existing: dict) -> tuple[str, str] | None:
    """Return an error/reason pair when a persisted certificate is not currently valid."""
    now = datetime.now(timezone.utc)
    issued_at = parse_db_datetime(existing["issued_at"])
    expires_at = parse_db_datetime(existing["expires_at"])
    if issued_at > now:
        return "Certificate is not yet valid", "certificate_not_yet_valid"
    if expires_at <= now:
        return "Certificate expired; re-enrollment required", "certificate_expired"
    # F-20: a renewed certificate's predecessor stays usable for a grace window,
    # then stops being accepted here at the same instant it enters the CRL.
    revoke_after = existing.get("revoke_after")
    if revoke_after and parse_db_datetime(revoke_after) <= now:
        return (
            "Certificate superseded by renewal; use the renewed certificate",
            "certificate_superseded",
        )
    return None


def _stamp(at: datetime) -> str:
    return at.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _has_control_characters(value: str) -> bool:
    return any(ord(ch) < 0x20 or 0x7F <= ord(ch) < 0xA0 for ch in value)


def _count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


@dataclass(frozen=True)
class EdgeJoin:
    """An edge /join that passed its checks, before the invite is consumed."""

    node_public_key: str
    node_sovereign_id: str
    resource_prefix: str
    executor_public_key: str
    executor_key_id: str
    agent_version: Optional[str]


class EdgeService:
    """NA application logic for edge nodes."""

    def __init__(self, service: "NetworkAuthorityService") -> None:
        self._na = service
        # Only a test that stops the migrations early runs without the edge tables.
        self._ready = service.db.schema_version() >= EDGE_SCHEMA_VERSION

    @property
    def _db(self) -> Any:
        return self._na.db

    @property
    def audience(self) -> str:
        """What a node-scoped request names as its ``audience``: this NA's public key."""
        return str(self._na.genesis_block.network_authority.public_key)

    def _remote_addr(self) -> str:
        return request.remote_addr or "unknown"

    # -- edge invites -----------------------------------------------------------

    @staticmethod
    def is_edge_invite(data: dict[str, Any]) -> bool:
        """Whether an invite request asks for an edge invite (it then needs the privileged tier)."""
        return data.get("node_sovereign_id") is not None or data.get("executor_resource_prefix") is not None

    def invite_fields(self, data: dict[str, Any]) -> tuple[str, str]:
        """The checked sovereign ID and resource prefix of an edge invite request."""
        sovereign = data.get("node_sovereign_id")
        prefix = data.get("executor_resource_prefix")
        if sovereign is None or prefix is None:
            raise BadRequestError(
                "An edge invite needs both node_sovereign_id and executor_resource_prefix",
                code="invalid_edge_invite",
            )
        if not isinstance(sovereign, str) or not NODE_SOVEREIGN_ID.match(sovereign):
            raise BadRequestError(
                "node_sovereign_id must match ^[a-z0-9][a-z0-9._-]{0,63}$",
                code="invalid_node_sovereign_id",
            )
        if not isinstance(prefix, str) or not 1 <= len(prefix) <= 256 or _has_control_characters(prefix):
            raise BadRequestError(
                "executor_resource_prefix must be a string of 1 to 256 characters without control characters",
                code="invalid_resource_prefix",
            )
        if not self._na.out_of_band_service.enabled:
            raise ConflictError(
                "Edge invites need the evidence store and out-of-band recording "
                "(EVIDENCE_STORE=on, EVIDENCE_OUT_OF_BAND=on)",
                code="edge_requires_evidence_store",
            )
        if self._db.get_active_edge_node_by_sovereign(sovereign) is not None:
            raise ConflictError("An active edge node already has this sovereign ID", code="node_sovereign_in_use")
        return sovereign, prefix

    # -- /join ------------------------------------------------------------------

    def check_join(self, data: dict[str, Any], token: InviteToken, node_public_key: str) -> Optional[EdgeJoin]:
        """The checks of an edge /join that come before its invite is consumed, so a refused request
        never burns the token. None for a plain invite without executor fields."""
        executor_public_key = data.get("executor_public_key")
        sends_executor = executor_public_key is not None or data.get("executor_signature") is not None
        if token.node_sovereign_id is None:
            if sends_executor:
                raise ForbiddenError("This invite is not an edge invite", code="invite_not_for_edge_node")
            return None
        if executor_public_key is None:
            raise BadRequestError("An edge invite needs executor_public_key", code="executor_key_required")
        try:
            decode_ed25519_public_key(executor_public_key)
        except ValueError:
            raise BadRequestError(
                "executor_public_key must be a base64 32-byte Ed25519 key", code="invalid_executor_public_key"
            ) from None
        if executor_public_key == node_public_key:
            raise BadRequestError("The executor key must differ from the node key", code="executor_key_is_node_key")
        signature = data.get("executor_signature")
        if not isinstance(signature, str) or not signature or not verify_signature(
            executor_proof_payload(data), signature, executor_public_key
        ):
            raise UnauthorizedError("The executor key's proof of possession failed", code="executor_proof_failed")
        key_id = executor_key_id(executor_public_key)
        if self._db.get_executor_key(key_id) is not None:
            raise ConflictError("This executor key is already registered", code="executor_key_exists")
        if self._db.get_edge_node(node_public_key) is not None:
            raise ConflictError("This node key already belongs to an edge node", code="edge_node_already_enrolled")
        if self._db.get_active_edge_node_by_sovereign(token.node_sovereign_id) is not None:
            raise ConflictError("An active edge node already has this sovereign ID", code="node_sovereign_in_use")
        self._na.evidence_store_service.require_enabled()
        version = data.get("agent_version")
        return EdgeJoin(
            node_public_key=node_public_key,
            node_sovereign_id=token.node_sovereign_id,
            resource_prefix=str(token.executor_resource_prefix),
            executor_public_key=executor_public_key,
            executor_key_id=key_id,
            agent_version=version if isinstance(version, str) and len(version) <= AGENT_VERSION_MAX else None,
        )

    def enrol(self, join: EdgeJoin, cert: JoinCertificate) -> dict[str, Any]:
        """Register the executor key of a node just issued ``cert`` and record the edge node; returns
        the response's ``edge`` block. All or nothing: when a step fails, the certificate is revoked
        (``unspecified``) and the error returned."""
        try:
            try:
                self._db.insert_edge_node({
                    "node_public_key": join.node_public_key, "node_sovereign_id": join.node_sovereign_id,
                    "executor_key_id": join.executor_key_id, "resource_prefix": join.resource_prefix,
                    "enrolled_cert_id": cert.cert_id, "enrolled_at": _stamp(cert.issued_at),
                })
            except self._db.integrity_errors:
                # Another request enrolled the node key or the sovereign ID first.
                if self._db.get_edge_node(join.node_public_key) is not None:
                    raise ConflictError("This node key already belongs to an edge node",
                                        code="edge_node_already_enrolled") from None
                raise ConflictError("An active edge node already has this sovereign ID",
                                    code="node_sovereign_in_use") from None
            try:
                self._na.evidence_store_service.register_executor_key({
                    "key_id": join.executor_key_id, "public_key": join.executor_public_key,
                    "executor_sovereign_id": join.node_sovereign_id, "role": "executor",
                    "resource_prefix": join.resource_prefix,
                }, registered_by=f"node-join:{cert.cert_id}")
            except BaseException:
                self._db.delete_edge_node(join.node_public_key)
                raise
        except BaseException as exc:
            self._undo_certificate(cert, join, exc)
            raise
        self._db.add_audit_event("edge_node_enrolled", {
            "cert_id": cert.cert_id, "node_public_key": join.node_public_key,
            "node_sovereign_id": join.node_sovereign_id, "executor_key_id": join.executor_key_id,
            "resource_prefix": join.resource_prefix, "agent_version": join.agent_version,
        })
        block = self.edge_block(join.node_public_key)
        assert block is not None
        return block

    def _undo_certificate(self, cert: JoinCertificate, join: EdgeJoin, exc: BaseException) -> None:
        reason = exc.code if isinstance(exc, ApiError) else type(exc).__name__
        try:
            self._na.publish_crl(
                lambda: self._db.revoke_cert(cert_id=cert.cert_id, reason="unspecified", issuer=self._na.key_id)
            )
        except Exception as undo_exc:  # noqa: BLE001 -- the original failure is what the caller sees
            logger.error("could not revoke certificate %s after a failed edge enrolment: %s",
                         cert.cert_id, undo_exc)
        self._db.add_audit_event("edge_node_enrollment_failed", {
            "cert_id": cert.cert_id, "node_public_key": join.node_public_key,
            "node_sovereign_id": join.node_sovereign_id, "executor_key_id": join.executor_key_id,
            "reason": reason,
        })

    def _executor_key(self, key_id: str) -> Optional[dict[str, Any]]:
        row = self._db.get_executor_key(key_id)
        if row is None:
            return None
        names = set(row.keys())
        return {
            "key_id": row["key_id"], "public_key": row["public_key"],
            "executor_sovereign_id": row["executor_sovereign_id"],
            "role": (row["key_role"] if "key_role" in names and row["key_role"] else "executor"),
            "resource_prefix": row["resource_prefix"] if "resource_prefix" in names else None,
            "registered_at": row["registered_at"], "retired_at": row["retired_at"],
        }

    def edge_block(self, node_public_key: str) -> Optional[dict[str, Any]]:
        """The ``edge`` block of a /join or /renew response; None for a node that is not an edge node."""
        edge = self._db.get_edge_node(node_public_key) if self._ready else None
        if edge is None:
            return None
        return {"node_sovereign_id": edge["node_sovereign_id"],
                "executor_key": self._executor_key(edge["executor_key_id"])}

    # -- /heartbeat ---------------------------------------------------------------

    def record_agent_status(self, node_public_key: str, agent: Any) -> None:
        """Keep the known, well-typed fields of a heartbeat's ``agent`` block for an edge node.
        Anything else is dropped, never refused, so a newer agent never breaks heartbeats."""
        if not isinstance(agent, dict) or not self._ready:
            return
        edge = self._db.get_edge_node(node_public_key)
        if edge is None or edge["retired_at"]:
            return
        status: dict[str, Any] = {}
        version = agent.get("version")
        if isinstance(version, str) and len(version) <= AGENT_VERSION_MAX:
            status["version"] = version
        age = agent.get("snapshot_age_seconds", ...)
        if age is None or _count(age):
            status["snapshot_age_seconds"] = age
        for name in ("pending_uploads", "dead_letters"):
            if _count(agent.get(name)):
                status[name] = agent[name]
        self._db.set_edge_agent_status(node_public_key, json.dumps(status, sort_keys=True),
                                       _stamp(datetime.now(timezone.utc)))

    # -- node-scoped requests -------------------------------------------------------

    def _refused(self, event: str, details: dict[str, Any]) -> None:
        self._db.add_audit_event(event, {**details, "remote_addr": self._remote_addr()})

    def authenticate(self, data: dict[str, Any], purpose: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """Authenticate a node-scoped request: ``(certificate row, edge node row)``. The checks run in
        the order of /heartbeat, then ``purpose`` and ``audience``, then the edge node."""
        cert_id = data.get("cert_id")
        node_public_key = data.get("node_public_key")
        if not isinstance(cert_id, str) or not cert_id or not isinstance(node_public_key, str) or not node_public_key:
            raise BadRequestError("cert_id and node_public_key required", code="missing_certificate_identity")
        cert = self._db.get_cert(cert_id)
        if not cert:
            raise ForbiddenError("Unknown certificate", code="certificate_not_found")
        if cert.get("node_public_key") != node_public_key:
            raise ForbiddenError("Public key does not match certificate", code="certificate_key_mismatch")
        if cert.get("status") == "revoked":
            self._refused("node_request_refused", {
                "cert_id": cert_id, "purpose": purpose, "reason": cert.get("revocation_reason") or "revoked"})
            raise ForbiddenError("Certificate revoked", code="certificate_revoked")
        ok, error = verify_node_request_signature(self._na, data, node_public_key)
        if not ok:
            raise UnauthorizedError(error or "Unauthorized", code="node_auth_failed")
        # The nonce is spent: a request signed for another route or NA is refused, never retried.
        for field, expected, reason in (("purpose", purpose, "purpose_mismatch"),
                                        ("audience", self.audience, "audience_mismatch")):
            if data.get(field) != expected:
                _audit_auth_failure(self._na, "node_auth_failed",
                                    {"scope": f"node:{node_public_key}", "reason": reason})
                raise UnauthorizedError(f"The request is not signed for this {field}", code="node_auth_failed")
        rejection = certificate_time_rejection(cert)
        if rejection is not None:
            message, reason = rejection
            self._refused("node_request_refused", {"cert_id": cert_id, "purpose": purpose, "reason": reason})
            raise ForbiddenError(message, code=reason)
        edge = self._db.get_edge_node(node_public_key) if self._ready else None
        if edge is None:
            raise ForbiddenError("This node is not an enrolled edge node", code="edge_node_not_enrolled")
        if edge["retired_at"]:
            raise ForbiddenError("This edge node has been revoked", code="edge_node_retired")
        return cert, edge

    def _issued_to(self, attestation: Any, edge: dict[str, Any]) -> bool:
        """An attestation is issued to a node: this NA issued it, to the node's sovereign ID, with no
        subject key or the node's key."""
        return (attestation.issuer_sovereign_id == self._na.genesis_block.network_name
                and attestation.subject_id == edge["node_sovereign_id"]
                and attestation.subject_public_key in (None, edge["node_public_key"]))

    def evaluate(self, data: dict[str, Any], edge: dict[str, Any]) -> tuple["BoundaryDecision", Any]:
        """``POST /node/boundary/evaluate``: a decision under an attestation issued to the node, with
        the node's sovereign ID as the requester."""
        if "agreement" in data:
            raise BadRequestError("A node evaluates under an attestation only", code="node_basis_unsupported")
        attestation_id = data.get("attestation_id")
        if not isinstance(attestation_id, str) or not attestation_id:
            raise BadRequestError("attestation_id must be a non-empty string", code="invalid_attestation_id")
        capability = data.get("requested_capability")
        if not capability or not isinstance(capability, str):
            raise BadRequestError("requested_capability is required", code="missing_boundary_fields")
        ctx = data.get("context") or {}
        if not isinstance(ctx, dict):
            raise BadRequestError("context must be an object", code="invalid_context")
        sovereign = edge["node_sovereign_id"]
        details = {"node_public_key": edge["node_public_key"], "executor_key_id": edge["executor_key_id"],
                   "attestation_id": attestation_id, "requested_capability": capability}
        requester = ctx.get("requester_sovereign_id")
        if requester is not None and requester != sovereign:
            self._refused("node_request_refused", {**details, "reason": "node_requester_mismatch"})
            raise ForbiddenError("A node requests as its own sovereign ID only", code="node_requester_mismatch")
        row = self._db.get_membership_attestation(attestation_id)
        if row is None or not self._issued_to(row["attestation"], edge):
            self._refused("node_request_refused", {**details, "reason": "node_attestation_foreign"})
            raise ForbiddenError("The attestation was not issued to this node", code="node_attestation_foreign")

        policies = self._na.boundary_policies
        basis, requester_id = policies.assess_attestation(attestation_id, sovereign)
        context = policies.build_attestation_context(data, attestation_id, requester_id)
        decision, proof = policies.evaluate_attestation(context, basis)
        self._na.evidence_store_service.record_decision(
            decision, context, proof, requested_by=f"node:{edge['executor_key_id']}")
        binding = decision.policy_binding
        self._db.add_audit_event("node_boundary_decision_made", {
            "decision_id": decision.decision_id, "context_id": context.context_id,
            "node_public_key": edge["node_public_key"], "executor_key_id": edge["executor_key_id"],
            "attestation_id": attestation_id, "requester_sovereign_id": requester_id,
            "requested_capability": capability, "authorized": decision.authorized,
            "denial_reason": decision.denial_reason,
            "applied_policies": [f"{p.policy_id}@{p.version}" for p in (binding.policies if binding else [])],
            "failed_gates": [gr.gate_name for gr in decision.gate_results if not gr.passed],
        })
        return decision, proof

    def _newest_valid_cert(self, node_public_key: str) -> Optional[dict[str, Any]]:
        valid = [c for c in self._db.get_certs_by_node_key(node_public_key)
                 if c.get("status") != "revoked" and certificate_time_rejection(c) is None]
        return max(valid, key=lambda c: parse_db_datetime(c["issued_at"])) if valid else None

    def state(self, cert: dict[str, Any], edge: dict[str, Any]) -> dict[str, Any]:
        """``POST /node/state``: the node, its executor key, the attestations issued to it and the grants
        its executor key bears."""
        now = datetime.now(timezone.utc)
        newest = self._newest_valid_cert(edge["node_public_key"]) or cert
        attestations = []
        for row in self._db.list_membership_attestations(
                issuer_sovereign_id=self._na.genesis_block.network_name,
                subject_id=edge["node_sovereign_id"], status="active"):
            attestation = row["attestation"]
            if self._issued_to(attestation, edge) and attestation.expires_at > now:
                attestations.append({"attestation": json.loads(attestation.model_dump_json()), "status": "active"})
        grants: list[dict[str, Any]] = []
        service = self._na.grant_service
        if service.enabled:
            rows = self._db.list_grant_rows(status="active", bearer_key_id=edge["executor_key_id"],
                                            now=service._now(), limit=STATE_GRANT_LIMIT)
            grants = [service._grant(r).to_wire() for r in rows]
        return {
            "server_time": now.isoformat(),
            "node": {"node_public_key": edge["node_public_key"], "node_sovereign_id": edge["node_sovereign_id"],
                     "cert_id": newest["cert_id"], "cert_expires_at": newest["expires_at"],
                     "roles": json.loads(newest.get("roles_json") or "[]")},
            "executor_key": self._executor_key(edge["executor_key_id"]),
            "attestations": attestations,
            "grants": grants,
        }

    def resource_head(self, data: dict[str, Any], edge: dict[str, Any]) -> dict[str, Any]:
        """``POST /node/evidence/resource-head``: the head of a resource under the node's prefix."""
        resource_id = data.get("resource_id")
        if not isinstance(resource_id, str) or not resource_id.startswith(edge["resource_prefix"]):
            self._refused("node_request_refused", {
                "node_public_key": edge["node_public_key"], "executor_key_id": edge["executor_key_id"],
                "reason": "node_resource_out_of_scope"})
            raise ForbiddenError("The resource is outside this node's resource prefix",
                                 code="node_resource_out_of_scope")
        head: dict[str, Any] = self._na.evidence_store_service.resource_head(resource_id)
        return head

    # -- operators: /admin/edge-nodes ---------------------------------------------

    def list_edge_nodes(self, status: Optional[str], limit_text: Optional[str], before: Optional[str],
                        node_sovereign_id: Optional[str]) -> dict[str, Any]:
        """``GET /admin/edge-nodes``: edge nodes, newest enrolment first."""
        if status is not None and status not in EDGE_STATUSES:
            raise BadRequestError("status must be online, offline or revoked", code="invalid_edge_status")
        try:
            limit = int(limit_text) if limit_text else DEFAULT_PAGE
        except ValueError:
            raise BadRequestError("limit must be an integer", code="invalid_page") from None
        if not 1 <= limit <= MAX_PAGE:
            raise BadRequestError(f"limit must be 1..{MAX_PAGE}", code="invalid_page")
        after: Optional[tuple[str, str]] = None
        if before:
            cursor = self._db.get_edge_node(before)
            if cursor is None:
                raise BadRequestError("before must be the node_public_key of an edge node (next_before)",
                                      code="invalid_page")
            after = (cursor["enrolled_at"], cursor["node_public_key"])
        retired = None if status is None else status == "revoked"
        now = datetime.now(timezone.utc)
        usage = self._grant_usage()
        nodes: list[dict[str, Any]] = []
        while len(nodes) < limit:
            batch = self._db.edge_nodes_page(retired=retired, node_sovereign_id=node_sovereign_id or None,
                                             after=after, limit=limit)
            for row in batch:
                after = (row["enrolled_at"], row["node_public_key"])
                view = self._view(row, now, usage)
                if status is None or view["status"] == status:
                    nodes.append(view)
                    if len(nodes) == limit:
                        break
            if len(batch) < limit:
                break
        return {"count": len(nodes), "next_before": nodes[-1]["node_public_key"] if len(nodes) == limit else None,
                "edge_nodes": nodes}

    def _grant_usage(self) -> Optional[dict[str, tuple[int, int]]]:
        """Usable grants and their admitted uses, by bearer key; None with grants off."""
        service = self._na.grant_service
        if not service.enabled:
            return None
        usage: dict[str, tuple[int, int]] = {}
        for row in self._db.usable_grant_rows(service._now()):
            count, uses = usage.get(row["bearer_key_id"], (0, 0))
            usage[row["bearer_key_id"]] = (count + 1, uses + int(row["uses"]))
        return usage

    def _break_glass(self, edge: dict[str, Any]) -> Optional[dict[str, Any]]:
        if not self._na.evidence_store_service.enabled:
            return None
        since = parse_db_datetime(edge["enrolled_at"])
        records, last = 0, None
        for row in self._db.break_glass_entries_of(edge["node_sovereign_id"]):
            if parse_db_datetime(row["recorded_at"]) < since:
                continue
            records += 1
            executed = json.loads(row["payload_json"]).get("executed_at")
            if isinstance(executed, str) and (last is None or parse_db_datetime(executed) > parse_db_datetime(last)):
                last = executed
        return {"records": records, "last_executed_at": last}

    def _view(self, edge: dict[str, Any], now: datetime,
              usage: Optional[dict[str, tuple[int, int]]]) -> dict[str, Any]:
        certs = self._db.get_certs_by_node_key(edge["node_public_key"])
        newest = max(certs, key=lambda c: parse_db_datetime(c["issued_at"])) if certs else None
        seen = [c for c in certs if c.get("last_heartbeat")]
        last = max(seen, key=lambda c: parse_db_datetime(c["last_heartbeat"])) if seen else None
        if edge["retired_at"]:
            status = "revoked"
        elif last is not None and (now - parse_db_datetime(last["last_heartbeat"])).total_seconds() < ONLINE_SECONDS:
            status = "online"
        else:
            status = "offline"
        agent = None
        if edge.get("agent_status_json"):
            reported = json.loads(edge["agent_status_json"])
            agent = {name: reported.get(name) for name in
                     ("version", "snapshot_age_seconds", "pending_uploads", "dead_letters")}
            agent["reported_at"] = edge["agent_status_at"]
        grants = None
        if usage is not None:
            count, uses = usage.get(edge["executor_key_id"], (0, 0))
            grants = {"usable": count, "admitted_uses": uses}
        return {
            "node_public_key": edge["node_public_key"], "node_sovereign_id": edge["node_sovereign_id"],
            "executor_key_id": edge["executor_key_id"], "resource_prefix": edge["resource_prefix"],
            "roles": json.loads(newest.get("roles_json") or "[]") if newest else [],
            "status": status, "enrolled_at": edge["enrolled_at"],
            "cert_id": newest["cert_id"] if newest else None,
            "cert_expires_at": newest["expires_at"] if newest else None,
            "last_seen_at": last["last_heartbeat"] if last else None,
            "remote_addr": last.get("remote_addr") if last else None,
            "agent": agent, "grants": grants, "break_glass": self._break_glass(edge),
            "revoked_at": edge["retired_at"], "revocation_reason": edge["retired_reason"],
        }

    # -- operators: /admin/revoke ----------------------------------------------------

    def revoke(self, cert: dict[str, Any], reason: str, retired_by: str) -> Optional[tuple[Any, dict[str, Any]]]:
        """Revoke an edge node from one of its certificates: every certificate of the node in one CRL,
        then its executor key (which revokes the grants it bears). Returns (CRL, ``edge_node``
        block), or None when the certificate is not an edge node's. Idempotent."""
        node_public_key = cert["node_public_key"]
        edge = self._db.get_edge_node(node_public_key) if self._ready else None
        if edge is None:
            return None
        unrevoked = [c["cert_id"] for c in self._db.get_certs_by_node_key(node_public_key)
                     if c.get("status") != "revoked"]
        cert_ids = list(dict.fromkeys([cert["cert_id"], *unrevoked]))
        crl = self._na.publish_crl(lambda: self._db.revoke_certs(cert_ids, reason, issuer=self._na.key_id))
        assert crl is not None
        for cert_id in unrevoked:
            if cert_id in self._na.connected_nodes:
                self._na.connected_nodes[cert_id]["status"] = "revoked"
                self._na.connected_nodes[cert_id]["revocation_reason"] = reason
        if edge["retired_at"]:
            retired, grants_revoked = True, 0
        else:
            retired, grants_revoked = self._retire(edge, reason, retired_by)
        block = {"node_public_key": node_public_key, "executor_key_id": edge["executor_key_id"],
                 "revoked_cert_ids": unrevoked, "executor_key_retired": retired, "grants_revoked": grants_revoked}
        self._db.add_audit_event("edge_node_revoked", {
            "node_public_key": node_public_key, "executor_key_id": edge["executor_key_id"],
            "revoked_cert_ids": unrevoked, "reason": reason, "grants_revoked": grants_revoked,
            "executor_key_retired": retired, "crl_sequence": crl.sequence,
        })
        return crl, block

    def _retire(self, edge: dict[str, Any], reason: str, retired_by: str) -> tuple[bool, int]:
        """Retire an edge node's executor key, then mark the node revoked. (retired, grants revoked);
        on failure the node stays unrevoked, so ``ensure_retired`` retires it at the next start."""
        grants_revoked = 0
        try:
            grants_revoked = self._na.evidence_store_service.retire_executor_key_counted(
                edge["executor_key_id"], retired_by)
        except ConflictError as exc:
            if exc.code != "executor_key_retired":
                return self._incomplete(edge, exc)
        except Exception as exc:  # noqa: BLE001 -- the certificates are revoked; the retirement is repeated
            return self._incomplete(edge, exc)
        self._db.retire_edge_node(edge["node_public_key"], _stamp(datetime.now(timezone.utc)), reason, retired_by)
        return True, grants_revoked

    def _incomplete(self, edge: dict[str, Any], exc: BaseException) -> tuple[bool, int]:
        logger.error("could not retire executor key %s of edge node %s: %s",
                     edge["executor_key_id"], edge["node_sovereign_id"], exc)
        self._db.add_audit_event("edge_node_revocation_incomplete", {
            "node_public_key": edge["node_public_key"], "executor_key_id": edge["executor_key_id"],
            "reason": exc.code if isinstance(exc, ApiError) else type(exc).__name__,
        })
        return False, 0

    def ensure_retired(self) -> int:
        """At start: retire the executor keys of edge nodes whose certificates are all revoked (a
        revocation whose retirement failed). Returns how many nodes it retired."""
        done = 0
        if not self._ready:
            return done
        for edge in self._db.unretired_edge_nodes():
            certs = self._db.get_certs_by_node_key(edge["node_public_key"])
            if not certs or any(c.get("status") != "revoked" for c in certs):
                continue
            newest = max(certs, key=lambda c: parse_db_datetime(c["issued_at"]))
            try:
                retired, grants_revoked = self._retire(
                    edge, newest.get("revocation_reason") or "unspecified", "na:start")
            except Exception as exc:  # noqa: BLE001 -- never stops the NA starting
                logger.error("could not retire edge node %s: %s", edge["node_sovereign_id"], exc)
                continue
            if retired:
                done += 1
                self._db.add_audit_event("edge_node_revoked", {
                    "node_public_key": edge["node_public_key"], "executor_key_id": edge["executor_key_id"],
                    "revoked_cert_ids": [], "reason": newest.get("revocation_reason") or "unspecified",
                    "grants_revoked": grants_revoked, "executor_key_retired": True, "crl_sequence": None,
                })
        return done

