"""Re-issue at a key succession (v1.8.0).

From 1.8.0 a record signed by an NA key that has ended vouches for the present
only until the key's end, the 5-minute hand-over and the vouching grace
(``NAKeyHistory.vouches_until``). For the records the NA issued to outlive
that horizon, the NA re-issues them under the key that signs now:

- **Attestations and treaties** in this sovereign's name that are active,
  current (not superseded) and expire after the horizon get a copy under a
  new ID, with ``issued_at`` now and the same content otherwise. The copy
  joins the record's lineage (migration 020): the previous copy stays
  active, so grants and decisions that name its ID keep verifying, and a
  revocation of either copy revokes both. Records that lapse within the
  grace are left to lapse.
- **The active policy manifest**, which every node fetches, is signed again
  under the same ``policy_id``. ``GET /policy`` and a rollback re-sign it too.
- The CRL needs nothing here: the NA republishes it under the key that signs
  now (core 1.8.0).

The job runs only on an instance whose key signs now: at start, on a lazy
trigger (``maybe_reissue``, from the readiness probe and ``GET /policy``), and
on request (``POST /admin/na/reissue``, ``genesis-mesh na reissue``). Each run
re-issues at most ``REISSUE_BATCH`` records; the next trigger continues.
Instances may run it at once: the store's compare-and-set keeps one copy per
record and never brings back a record revoked meanwhile. A run that
re-issues anything records ``na_records_reissued``. ``reissue_pending`` in the
readiness details and ``genesis-mesh na doctor`` say whether any record is
still due.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from ...crypto import verify_model_signature
from ...models import MembershipAttestation, PolicyManifest, RecognitionTreaty
from ...models.key_succession import NAKey, NAKeyHistory

if TYPE_CHECKING:
    from ..server import NetworkAuthorityService

logger = logging.getLogger(__name__)

#: How often the lazy trigger looks for records to re-issue while none is due.
REISSUE_CHECK_SECONDS = 60.0
#: The most records one run re-issues; a run that stops there leaves the rest to the next trigger.
REISSUE_BATCH = 100
#: The migration that adds the lineage columns.
REISSUE_SCHEMA = 20


def _parse(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def record_signer(record: Any, history: NAKeyHistory) -> NAKey | None:
    """The key of ``history`` whose signature ``record`` carries, if any."""
    for signature in getattr(record, "signatures", None) or []:
        for key in history.keys:
            if verify_model_signature(record, signature, key.public_key):
                return key
    return None


@dataclass
class DueRecords:
    """What a key succession leaves to re-issue: (record, the ended key that signed it) pairs."""

    attestations: list[tuple[MembershipAttestation, NAKey]] = field(default_factory=list)
    treaties: list[tuple[RecognitionTreaty, NAKey]] = field(default_factory=list)
    #: The active policy manifest, when a key other than the one signing now signed it.
    policy: PolicyManifest | None = None

    @property
    def pending(self) -> bool:
        return bool(self.attestations or self.treaties or self.policy is not None)

    def summary(self) -> dict[str, Any]:
        return {"reissue_pending": self.pending,
                "due": {"attestations": len(self.attestations), "treaties": len(self.treaties),
                        "policy_manifest": self.policy is not None}}


def _due(record: Any, history: NAKeyHistory, signing: NAKey, now: datetime) -> NAKey | None:
    """The ended key that signed ``record`` when the record outlives that key's horizon, else None."""
    signer = record_signer(record, history)
    if signer is None:
        logger.debug("%s %s carries no signature of a key in the key history; not re-issued",
                       type(record).__name__, getattr(record, "attestation_id", None) or getattr(record, "treaty_id", ""))
        return None
    if signer.public_key == signing.public_key or signer.end is None or signer.end > now:
        return None
    horizon = history.vouches_until(signer.public_key)
    if horizon is None or record.expires_at <= max(horizon, now):
        return None  # it lapses within the grace (or has lapsed): left to lapse
    return signer


def due_records(db: Any, history: NAKeyHistory, sovereign_id: str, signing: NAKey, now: datetime) -> DueRecords:
    """The records an instance signing with ``signing`` would re-issue at ``now``.

    Pure over the database, for the job and for ``genesis-mesh na doctor``.
    Only keys that have ended matter, so a history of one key has nothing due.
    A record issued once ``signing`` took effect was not signed by an earlier
    key (an outgoing key signs nothing from then on), so only the rows issued
    before are read and their signatures checked: re-issued copies drop out.
    """
    due = DueRecords()
    if not any(k.end is not None and k.end <= now and k.public_key != signing.public_key for k in history.keys):
        return due
    if db.schema_version() < REISSUE_SCHEMA:
        return due

    def candidates(kind: str) -> list[str]:
        return [head["record_id"] for head in db.lineage_heads(kind, sovereign_id)
                if _parse(head["expires_at"]) > now
                and (signing.valid_from is None or _parse(head["issued_at"]) < signing.valid_from)]

    for record_id in candidates("attestation"):
        row = db.get_membership_attestation(record_id)
        if row is not None and (signer := _due(row["attestation"], history, signing, now)) is not None:
            due.attestations.append((row["attestation"], signer))
    for record_id in candidates("treaty"):
        row = db.get_recognition_treaty(record_id)
        if row is not None and (signer := _due(row["treaty"], history, signing, now)) is not None:
            due.treaties.append((row["treaty"], signer))
    policy = db.get_active_policy()
    if policy is not None:
        signer = record_signer(policy, history)
        if signer is not None and signer.public_key != signing.public_key and signer.end is not None \
                and signer.end <= now:
            due.policy = policy
    return due


class ReissueService:
    """Re-issues the NA's records of a succeeded key under the key that signs now (v1.8.0)."""

    def __init__(self, na: "NetworkAuthorityService") -> None:
        self._na = na
        self._lock = threading.Lock()
        self._next_run = 0.0
        self._summary: dict[str, Any] = DueRecords().summary()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    def _signing_key(self, history: NAKeyHistory, now: datetime) -> NAKey | None:
        key = history.key_for(self._na.signer.public_key_b64)
        return key if key is not None and key.signs_at(now) else None

    def due(self) -> DueRecords:
        """The records due now; none on an instance whose key does not sign now."""
        now = self._now()
        history = self._na.key_history.history()
        signing = self._signing_key(history, now)
        if signing is None:
            return DueRecords()
        return due_records(self._na.db, history, self._na.genesis_block.network_name, signing, now)

    def summary(self) -> dict[str, Any]:
        """What the last run left due (for the readiness details)."""
        return dict(self._summary)

    # -- the job ----------------------------------------------------------------------

    def run(self, *, all_due: bool = False) -> dict[str, Any]:
        """Re-issue what is due: ``REISSUE_BATCH`` attestations and treaties, or ``all_due``.

        Raises ``503`` when this instance's key may not sign now (``check_can_sign``).
        """
        self._na.key_history.check_can_sign()
        due = self.due()
        budget = len(due.attestations) + len(due.treaties) if all_due else REISSUE_BATCH
        now = self._now()
        key_id = self._na.key_id
        reissued = {"attestations": 0, "treaties": 0}
        not_current = 0
        previous_keys: set[str] = set()
        for attestation, signer in due.attestations[:budget]:
            new_attestation = MembershipAttestation.model_validate(attestation.model_copy(update={
                "attestation_id": str(uuid.uuid4()), "issued_at": now, "issued_by": key_id, "signatures": []},
            ).model_dump())
            new_attestation.signatures.append(self._na.signer.sign_model(new_attestation))
            if self._na.db.reissue_membership_attestation(attestation.attestation_id, new_attestation):
                reissued["attestations"] += 1
                previous_keys.add(signer.key_id or f"key-{signer.key_sequence}")
            else:
                not_current += 1  # revoked or re-issued by another instance meanwhile
        budget -= len(due.attestations[:budget])
        for treaty, signer in due.treaties[:max(budget, 0)]:
            new_treaty = RecognitionTreaty.model_validate(treaty.model_copy(update={
                "treaty_id": str(uuid.uuid4()), "issued_at": now, "issued_by": key_id, "signatures": []},
            ).model_dump())
            new_treaty.signatures.append(self._na.signer.sign_model(new_treaty))
            if self._na.db.reissue_recognition_treaty(treaty.treaty_id, new_treaty):
                reissued["treaties"] += 1
                previous_keys.add(signer.key_id or f"key-{signer.key_sequence}")
            else:
                not_current += 1
        policy_id = None
        if due.policy is not None:
            policy_id = self._resign_policy(due.policy).policy_id
        if reissued["attestations"] or reissued["treaties"] or policy_id is not None:
            self._na.db.add_audit_event("na_records_reissued", {
                **reissued, "policy_manifest": policy_id, "key_id": key_id,
                "previous_key_ids": sorted(previous_keys), "not_current": not_current,
            })
            logger.info("re-issued %d attestations and %d treaties under %s%s", reissued["attestations"],
                        reissued["treaties"], key_id, f", and policy manifest {policy_id}" if policy_id else "")
        self._summary = self.due().summary()
        return {"reissued": {**reissued, "policy_manifest": policy_id}, "not_current": not_current,
                **self._summary}

    def maybe_reissue(self) -> None:
        """``run`` when it is time to look again; never fails the caller, never runs twice at once.

        After a run that left records due it runs again on the next trigger,
        otherwise after ``REISSUE_CHECK_SECONDS``.
        """
        if time.monotonic() < self._next_run:
            return
        if not self._lock.acquire(blocking=False):
            return
        try:
            self._next_run = time.monotonic() + REISSUE_CHECK_SECONDS
            history = self._na.key_history.history()
            if self._signing_key(history, self._now()) is None:
                return
            if self.run()["reissue_pending"]:
                self._next_run = 0.0
        except Exception as exc:  # noqa: BLE001
            logger.error("re-issuing records after a key succession failed: %s", exc)
        finally:
            self._lock.release()

    # -- the policy manifest ----------------------------------------------------------

    def _resign_policy(self, policy: PolicyManifest) -> PolicyManifest:
        signed = policy.model_copy(update={"issued_at": self._now(), "issued_by": self._na.key_id, "signatures": []})
        signed = PolicyManifest.model_validate(signed.model_dump())
        signed.signatures.append(self._na.signer.sign_model(signed))
        self._na.db.save_policy(signed, active=True)
        return signed

    def active_policy(self) -> PolicyManifest:
        """The active policy manifest, signed by the key that signs now (``GET /policy``, rollback).

        A manifest a succeeded key signed is signed again under the same
        ``policy_id`` (v1.8.0); with none stored, the default is signed and
        stored, as before. An instance whose key does not sign now serves what
        is stored.
        """
        self.maybe_reissue()
        policy = self._na.db.get_active_policy()
        if policy is None:
            policy = self._na._get_default_policy()
            self._na.db.save_policy(policy, active=True)
            return policy
        now = self._now()
        history = self._na.key_history.history()
        signing = self._signing_key(history, now)
        if signing is None:
            return policy
        signer = record_signer(policy, history)
        if signer is not None and signer.public_key != signing.public_key and signer.end is not None \
                and signer.end <= now:
            return self._resign_policy(policy)
        return policy
