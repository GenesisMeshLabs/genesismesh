"""A deterministic sovereign across an NA key succession (v1.5.0), for audit vectors and the corpus.

Keys come from fixed seeds, every time and identifier is fixed and Ed25519
signatures are deterministic, so everything built here is byte-stable: the
``audit`` conformance suite, the verification corpus
(``scripts/export_reference_corpus.py --suite verification``) and the frozen
1.5.0 pack fixture (``conformance/fixtures/audit-pack-1.5.0``) are built from
it.

The world: a root key (seed ``f``), a genesis block naming the first NA key
(``c``); an executor (``b``) and an observer (``a``) registered in the store;
a policy, an attestation, a decision and its execution (signed by ``c``);
anchor 1; a succession to the NA key ``g`` (signed by the root key and
``c``); a second decision and execution (signed by ``g``), an observation of
that change and its judgement matching it; anchor 2; an archive record;
anchor 3.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import nacl.signing

SEEDS = {
    "a": bytes(range(32)),
    "b": bytes(range(32, 64)),
    "c": bytes(range(64, 96)),
    "f": bytes(range(160, 192)),
    "g": bytes(range(192, 224)),
}
KEYS = {k: nacl.signing.SigningKey(v) for k, v in SEEDS.items()}

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
SOVEREIGN = "sovereign-c"
EXECUTOR = "sovereign-b"
VENDOR = "vendor-acme"
RESOURCE = "kv:vault/api-key"
CAPABILITY = "secret.rotate"
SUCCESSION_AT = T0 + timedelta(days=10)


def pub(key: str) -> str:
    return base64.b64encode(bytes(KEYS[key].verify_key)).decode()


def uid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


@dataclass
class World:
    genesis: dict[str, Any]
    successions: list[dict[str, Any]]
    events: list[Any]
    anchors: list[Any]
    policies: list[dict[str, Any]]
    attestations: list[dict[str, Any]]
    records: dict[str, Any] = field(default_factory=dict)

    def keys_file(self) -> list[dict[str, Any]]:
        return [
            {"key_id": "executor-b", "public_key": pub("b"), "executor_sovereign_id": EXECUTOR, "role": "executor",
             "resource_prefix": None, "registered_at": T0.isoformat(), "retired_at": None},
            {"key_id": "observer-a", "public_key": pub("a"), "executor_sovereign_id": EXECUTOR, "role": "observer",
             "resource_prefix": None, "registered_at": T0.isoformat(), "retired_at": None},
        ]


def na_key_at(at: datetime) -> tuple[str, str]:
    """The NA key (seed, key ID) that signs at ``at``."""
    return ("c", "na-1") if at < SUCCESSION_AT else ("g", "na-2")


def build_world() -> World:
    from genesis_mesh.crypto import sign_model
    from genesis_mesh.models.audit_pack import ArchiveRecord
    from genesis_mesh.models.boundary_policy import AppliedPolicy, BoundaryPolicy, PolicyBinding, policy_set_digest
    from genesis_mesh.models.context import AttestationBinding, BoundaryDecision, ContextRecord
    from genesis_mesh.models.evidence_store import EvidenceEvent, StoreAnchor
    from genesis_mesh.models.execution import ExecutionEvidence
    from genesis_mesh.models.genesis import GenesisBlock, NetworkAuthority, PolicyManifestRef
    from genesis_mesh.models.key_succession import KeySuccessionRecord
    from genesis_mesh.models.out_of_band import JudgementRecord, ObservationRecord, RegistryRecord
    from genesis_mesh.models.sovereign import MembershipAttestation
    from genesis_mesh.trust.evidence_store import build_entry, decision_index, execution_index, sign_store_anchor
    from genesis_mesh.trust.key_succession import sign_succession
    from genesis_mesh.trust.out_of_band import entry_index

    def na_sign(model: Any, at: datetime) -> Any:
        seed, key_id = na_key_at(at)
        return sign_model(model, KEYS[seed], key_id)

    genesis = GenesisBlock(
        network_name=SOVEREIGN, network_version="v1", root_public_key=pub("f"),
        network_authority=NetworkAuthority(public_key=pub("c"), valid_from=T0, valid_to=T0 + timedelta(days=90)),
        policy_manifest=PolicyManifestRef(hash="sha256:conformance", url=None),
    )
    genesis.signatures.append(sign_model(genesis, KEYS["f"], "root"))
    issuer = {"issuer_sovereign_id": SOVEREIGN}

    policy = BoundaryPolicy(
        policy_id="secret-lifetime", version=1, description="cap secret lifetimes", valid_from=T0,
        valid_until=T0 + timedelta(days=365), selector={"capabilities": [CAPABILITY]},
        gates=[{"gate_id": "max-lifetime", "gate_type": "max_value.v1", "order": 0,
                "config": {"path": "request_parameters.lifetime_days", "max": 90}}],
        issued_at=T0, issued_by="na-1", issuer_sovereign_id=SOVEREIGN,
    )
    policy = policy.model_copy(update={"signature": na_sign(policy, T0)})
    attestation = MembershipAttestation(
        attestation_id=uid(901), issuer_sovereign_id=SOVEREIGN, subject_id=VENDOR, roles=["role:client"],
        issued_at=T0, valid_from=T0, expires_at=T0 + timedelta(days=365), issued_by="na-1",
        claims={"capabilities": [CAPABILITY]},
    )
    attestation.signatures.append(na_sign(attestation, T0))

    events: list[EvidenceEvent] = []
    anchors: list[StoreAnchor] = []
    records: dict[str, Any] = {}

    def append(kind: str, at: datetime, payload: dict[str, Any], index: dict[str, Any]) -> EvidenceEvent:
        prev = events[-1].entry.digest() if events else None
        entry = build_entry(store_sequence=len(events) + 1, entry_kind=kind, recorded_at=at, payload=payload,
                            prev_entry_digest=prev, index=index)
        event = EvidenceEvent(entry=entry, entry_digest=entry.digest(), payload=payload)
        events.append(event)
        return event

    def anchor(at: datetime) -> None:
        last = anchors[-1] if anchors else None
        seed, key_id = na_key_at(at)
        anchors.append(sign_store_anchor(StoreAnchor(
            anchor_sequence=len(anchors) + 1, sovereign_id=SOVEREIGN, store_sequence=events[-1].entry.store_sequence,
            entry_digest=events[-1].entry_digest, anchored_at=at,
            previous_anchor_digest=last.digest() if last else None, issued_by=key_id), KEYS[seed], key_id))

    def registry(n: int, at: datetime, **fields: Any) -> None:
        record = RegistryRecord(registry_record_id=uid(n), effective_at=at, issued_by=na_key_at(at)[1],
                                **issuer, **fields)
        record = record.model_copy(update={"signature": na_sign(record, at)})
        append("registry", at, record.to_wire(), entry_index("registry", record))

    registry(1, T0 + timedelta(minutes=1), event="executor_key_registered", key_id="executor-b",
             public_key=pub("b"), executor_sovereign_id=EXECUTOR, key_role="executor")
    registry(2, T0 + timedelta(minutes=1), event="executor_key_registered", key_id="observer-a",
             public_key=pub("a"), executor_sovereign_id=EXECUTOR, key_role="observer")
    registry(3, T0 + timedelta(minutes=2), event="policy_activated", policy_id="secret-lifetime", policy_version=1,
             policy_digest=policy.digest())

    def decision(n: int, at: datetime) -> tuple[BoundaryDecision, ContextRecord]:
        applied = [AppliedPolicy(policy_id="secret-lifetime", version=1, policy_digest=policy.digest(),
                                 signed_by="na-1")]
        context = ContextRecord(
            context_id=uid(100 + n), agreement_id=attestation.attestation_id, parent_kind="attestation",
            requester_sovereign_id=VENDOR, provider_sovereign_id=SOVEREIGN, requested_capability=CAPABILITY,
            request_parameters={"lifetime_days": 30}, requested_at=at, attestation_id=attestation.attestation_id,
        )
        made = BoundaryDecision(
            decision_id=uid(200 + n), context_id=context.context_id, agreement_id=attestation.attestation_id,
            authorized=True, decision_made_at=at, decision_valid_until=at + timedelta(minutes=5),
            operator_sovereign_id=SOVEREIGN,
            policy_binding=PolicyBinding(policies=applied, policy_set_digest=policy_set_digest(applied),
                                         context_digest=context.digest(), resolution_status="resolved"),
            attestation_binding=AttestationBinding(
                attestation_id=attestation.attestation_id, subject_id=VENDOR, issuer_sovereign_id=SOVEREIGN,
                attestation_digest=attestation.digest()),
        )
        made = made.model_copy(update={"signature": na_sign(made, at)})
        append("decision", at, {"decision": made.model_dump(mode="json"), "context": context.model_dump(mode="json")},
               decision_index(made, context))
        return made, context

    def execution(n: int, made: BoundaryDecision, at: datetime, action: str, version: str,
                  prior: ExecutionEvidence | None) -> ExecutionEvidence:
        evidence = ExecutionEvidence(
            evidence_id=uid(300 + n), sequence_no=1, decision_id=made.decision_id, context_id=made.context_id,
            agreement_id=made.agreement_id, executor_sovereign_id=EXECUTOR, executed_capability=CAPABILITY,
            outcome="success", execution_parameters={"version_id": version}, executed_at=at,
            resource_id=RESOURCE, resource_action=action,
            resource_sequence=(prior.resource_sequence or 0) + 1 if prior else 1,
            prev_resource_digest=prior.digest() if prior else None,
        )
        evidence = evidence.model_copy(update={"signature": sign_model(evidence, KEYS["b"], "executor-b")})
        payload = evidence.model_dump(mode="json")
        for name in ("resource_id", "resource_action", "resource_sequence", "prev_resource_digest"):
            if payload.get(name) is None:
                payload.pop(name, None)
        index = execution_index(evidence, {"vendor_id": VENDOR, "attestation_id": attestation.attestation_id})
        append("execution", at, payload, index)
        return evidence

    first_decision, _ = decision(1, T0 + timedelta(hours=1))
    first = execution(1, first_decision, T0 + timedelta(hours=1, minutes=1), "create", "v1", None)
    anchor(T0 + timedelta(hours=2))

    succession = KeySuccessionRecord(
        succession_id=uid(401), sovereign_id=SOVEREIGN, key_sequence=2, previous_key_id="na-1",
        previous_public_key=pub("c"), new_key_id="na-2", new_public_key=pub("g"), effective_at=SUCCESSION_AT,
        new_valid_to=SUCCESSION_AT + timedelta(days=730), issued_at=T0 + timedelta(days=4),
    )
    succession = sign_succession(sign_succession(succession, KEYS["f"], "root"), KEYS["c"], "na-1")
    append("key_succession", T0 + timedelta(days=5), succession.to_wire(), entry_index("key_succession", succession))

    second_decision, _ = decision(2, SUCCESSION_AT + timedelta(days=1))
    second = execution(2, second_decision, SUCCESSION_AT + timedelta(days=1, minutes=1), "rotate", "v2", first)
    observed_at = SUCCESSION_AT + timedelta(days=1, minutes=3)
    observation = ObservationRecord(
        observation_id=uid(501), observer_sovereign_id=EXECUTOR, resource_id=RESOURCE, action="rotate",
        capability=CAPABILITY, changed_at=second.executed_at, observed_at=observed_at, actor="principal-7f3a",
        source="cloud-activity-log", source_event_id="event-0002", version_id="v2", metadata={"lifetime_days": 30},
    )
    observation = observation.model_copy(update={"signature": sign_model(observation, KEYS["a"], "observer-a")})
    observed = append("observation", observed_at + timedelta(seconds=10), observation.to_wire(),
                      {**entry_index("observation", observation), "observation_sequence": 1})
    judged_at = observed_at + timedelta(seconds=20)
    judgement = JudgementRecord(
        judgement_id=uid(601), subject_kind="observation", subject_id=observation.observation_id,
        subject_digest=observed.entry.payload_digest, subject_store_sequence=observed.entry.store_sequence,
        resource_id=RESOURCE, action="rotate", capability=CAPABILITY, governed_by="prior_decision", verdict="allow",
        evaluated_as_of=second.executed_at, matched_evidence_id=second.evidence_id,
        matched_decision_id=second_decision.decision_id, judged_at=judged_at, issued_by="na-2", **issuer,
    )
    judgement = judgement.model_copy(update={"signature": na_sign(judgement, judged_at)})
    append("judgement", judged_at, judgement.to_wire(), entry_index("judgement", judgement))
    anchor(SUCCESSION_AT + timedelta(days=2))

    archived_at = SUCCESSION_AT + timedelta(days=3)
    archive = ArchiveRecord(
        archive_id=uid(701), pack_id=uid(801), from_sequence=1, through_sequence=anchors[0].store_sequence,
        through_entry_digest=anchors[0].entry_digest, end_anchor_sequence=1, manifest_sha256="d" * 64,
        location="archive://audit-archive/packs/" + uid(801), archived_at=archived_at, recorded_by="operator-1",
        issued_by="na-2", **issuer,
    )
    archive = archive.model_copy(update={"signature": na_sign(archive, archived_at)})
    append("archive", archived_at, archive.to_wire(), entry_index("archive", archive))
    anchor(SUCCESSION_AT + timedelta(days=4))
    records.update(first=first, second=second, first_decision=first_decision, second_decision=second_decision,
                   observation=observation, judgement=judgement, succession=succession, archive=archive,
                   policy=policy, attestation=attestation)
    return World(genesis=genesis.model_dump(mode="json"), successions=[succession.to_wire()], events=events,
                 anchors=anchors, policies=[policy.model_dump(mode="json")],
                 attestations=[attestation.model_dump(mode="json")], records=records)


def build_pack(world: World, *, start: int, through: int, pack_id: str, created_at: datetime,
               cited_sequences: list[int]) -> dict[str, bytes]:
    """A pack of the world's entries ``start..through`` (the NA's file layout, reproducibly)."""
    from genesis_mesh.crypto import sign_model
    from genesis_mesh.models.audit_pack import ATTESTATIONS_FILE, FEEDS_FILE, POLICIES_FILE, TREATIES_FILE
    from genesis_mesh.workflows.audit_pack import compose_pack

    entries = [e for e in world.events if start <= e.entry.store_sequence <= through]
    cited = [e for e in world.events if e.entry.store_sequence in cited_sequences]
    anchors = [a for a in world.anchors if start - 1 <= a.store_sequence <= through]
    end = next(a for a in world.anchors if a.store_sequence == through)
    start_anchor = next((a for a in world.anchors if a.store_sequence == start - 1), None)
    seed, key_id = na_key_at(created_at)
    files, _ = compose_pack(
        genesis=world.genesis, successions=world.successions, executor_keys=world.keys_file(), anchors=anchors,
        entries=entries, cited=cited,
        trust={POLICIES_FILE: world.policies, ATTESTATIONS_FILE: world.attestations, TREATIES_FILE: [],
               FEEDS_FILE: []},
        held_anchors=world.anchors, pack_id=pack_id, created_at=created_at, requested_by="auditor-1",
        start_anchor_sequence=start_anchor.anchor_sequence if start_anchor else None,
        end_anchor_sequence=end.anchor_sequence, issued_by=key_id,
        sign=lambda manifest: sign_model(manifest, KEYS[seed], key_id),
    )
    return files


def frozen_pack(world: World) -> dict[str, bytes]:
    """The frozen 1.5.0 pack: the range after anchor 1, across the succession, citing what it rests on."""
    first_anchor = world.anchors[0]
    cited = [e.entry.store_sequence for e in world.events
             if e.entry.store_sequence <= first_anchor.store_sequence
             and e.entry.entry_kind in ("registry", "execution")]
    return build_pack(world, start=first_anchor.store_sequence + 1, through=world.anchors[-1].store_sequence,
                      pack_id=uid(802), created_at=SUCCESSION_AT + timedelta(days=5), cited_sequences=cited)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))
