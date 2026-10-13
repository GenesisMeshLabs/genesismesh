"""The NA's key history and key succession (v1.5.0, Stage 4).

At start the NA records its genesis key as the first entry of its key
history (migration 017 creates the table), verifies the history from the
genesis block's root key down, and refuses to start with a key that is not
the one valid now. A succession is prepared and signed by the root key
offline (``genesis-mesh na succession sign``), submitted with a privileged
operator key (``POST /admin/na/succession``), checked and countersigned by
the outgoing key here, and recorded: in the history table and, with the
evidence store on, as a ``key_succession`` entry.

From the succession's ``effective_at`` the outgoing key signs nothing more:
every signature goes through ``GuardedSigner``, which asks
``check_can_sign`` first (``503 na_key_succeeded``). The operator restarts
the NA with the new key at that time. A key named by a succession signs
nothing at or after its own ``new_valid_to`` (``503 na_key_expired``); the
genesis key's ``valid_to`` is not enforced.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError as PydanticValidationError

from ...models.key_succession import KeySuccessionRecord, NAKey, NAKeyHistory
from ...trust.evidence_store import build_entry
from ...trust.key_succession import (
    genesis_key,
    sign_succession,
    signature_by,
    succession_refusal,
    verify_key_history,
)
from ..errors import BadRequestError, ConflictError, ServiceUnavailableError, ValidationError

if TYPE_CHECKING:
    from ..server import NetworkAuthorityService

logger = logging.getLogger(__name__)

#: A succession takes effect at least this long after it is recorded, so every NA instance
#: learns of it (``REFRESH_SECONDS``) before the outgoing key stops signing.
SUCCESSION_MIN_LEAD = timedelta(seconds=60)
#: ... and at most this long after.
SUCCESSION_MAX_LEAD = timedelta(days=30)
#: The longest validity a succession may give its new key.
MAX_KEY_VALIDITY = timedelta(days=3653)
#: How often an instance reads the history again, to learn of a succession another instance recorded.
REFRESH_SECONDS = 30.0
#: The migration that creates the key history table.
KEY_HISTORY_SCHEMA = 17


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


class KeyHistoryService:
    """The NA key history: recorded at start, read by verifiers, extended by a succession."""

    def __init__(self, na: "NetworkAuthorityService") -> None:
        self._na = na
        self._history: NAKeyHistory | None = None
        self._refreshed_at = 0.0

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    # -- start ------------------------------------------------------------------

    def ensure(self) -> None:
        """Record the genesis key as the first entry when the history is empty, verify the history,
        and refuse to start with a key that is not the one valid now (``ValueError``)."""
        db = self._na.db
        genesis = self._na.genesis_block
        if db.schema_version() < KEY_HISTORY_SCHEMA:
            # A database a test leaves at an older schema: the genesis key alone, as before 1.5.0.
            if genesis.network_authority.public_key != self._na.signer.public_key_b64:
                raise ValueError("NA private key does not match genesis block")
            self._history = NAKeyHistory(sovereign_id=genesis.network_name, root_public_key=genesis.root_public_key,
                                         keys=(genesis_key(genesis, self._na.key_id),))
            self._refreshed_at = float("inf")
            return
        if db.na_key_history_length() == 0:
            if genesis.network_authority.public_key != self._na.signer.public_key_b64:
                raise ValueError("NA private key does not match genesis block")
            try:
                db.add_na_key_row({
                    "key_sequence": 1, "key_id": self._na.key_id,
                    "public_key": genesis.network_authority.public_key,
                    "effective_at": None, "valid_to": _iso(genesis.network_authority.valid_to),
                    "valid_to_enforced": 0, "succession_digest": None, "succession_json": None,
                    "recorded_at": self._now().isoformat(),
                })
            except db.integrity_errors:
                pass  # another instance recorded it first
        self._load()
        history = self.history()
        key = history.key_for(self._na.signer.public_key_b64)
        if key is None:
            raise ValueError("NA private key does not match genesis block or any key of its succession history")
        now = self._now()
        if not key.signs_at(now):
            raise ValueError(self._not_signing(key, now))
        if key.key_id is not None and key.key_id != self._na.key_id:
            logger.warning("NA_KEY_ID %r differs from the key ID %r the key history records for this key",
                           self._na.key_id, key.key_id)

    def _load(self) -> None:
        """Read and verify the history; a history that does not verify stops the NA (``ValueError``)."""
        rows = self._na.db.na_key_history_rows()
        genesis = self._na.genesis_block
        if not rows or rows[0]["public_key"] != genesis.network_authority.public_key:
            raise ValueError("the NA key history does not start with the genesis block's NA key")
        successions = [json.loads(r["succession_json"]) for r in rows[1:]]
        result = verify_key_history(genesis.model_dump(mode="json"), successions,
                                    genesis_key_id=rows[0]["key_id"])
        if not result.verified or result.history is None:
            failure = result.failures[0] if result.failures else {"key_sequence": None, "reason": "invalid"}
            raise ValueError(f"the NA key history does not verify: key {failure['key_sequence']} "
                             f"{failure['reason']}")
        self._history = result.history
        self._refreshed_at = time.monotonic()

    def history(self) -> NAKeyHistory:
        """The verified key history (read again from the database every ``REFRESH_SECONDS``)."""
        if self._history is None or time.monotonic() - self._refreshed_at >= REFRESH_SECONDS:
            # (an older schema is never read again: its history is the genesis key)
            if self._history is None or self._na.db.na_key_history_length() != len(self._history.keys):
                self._load()
            else:
                self._refreshed_at = time.monotonic()
        assert self._history is not None
        return self._history

    # -- signing ----------------------------------------------------------------

    @staticmethod
    def _not_signing(key: NAKey, now: datetime) -> str:
        if key.valid_from is not None and now < key.valid_from:
            return (f"NA key {key.key_sequence} ({key.key_id}) takes effect at {key.valid_from.isoformat()}: "
                    f"keep the previous key until then")
        if key.succeeded_at is not None and now >= key.succeeded_at:
            return (f"NA key {key.key_sequence} ({key.key_id}) was succeeded at {key.succeeded_at.isoformat()}: "
                    f"start the NA with key {key.key_sequence + 1}")
        assert key.valid_to is not None
        return (f"NA key {key.key_sequence} ({key.key_id}) expired at {key.valid_to.isoformat()}: "
                "the network needs a new genesis block")

    def check_can_sign(self) -> None:
        """Raise ``503`` when this instance's key may not sign now (``GuardedSigner`` asks first)."""
        if self._history is None:
            return  # still starting: ensure() checks the key before anything is signed
        now = self._now()
        key = self.history().key_for(self._na.signer.public_key_b64)
        if key is not None and key.signs_at(now):
            return
        if key is not None and key.succeeded_at is None and key.valid_to_enforced and key.valid_to is not None \
                and now >= key.valid_to:
            code = "na_key_expired"
        elif key is not None and key.valid_from is not None and now < key.valid_from:
            code = "na_key_not_yet_effective"
        else:
            code = "na_key_succeeded"
        detail = self._not_signing(key, now) if key is not None else "the NA key is not in its key history"
        logger.error("refusing to sign: %s", detail)
        raise ServiceUnavailableError("The Network Authority's signing key may no longer sign: " + detail, code=code)

    # -- views ------------------------------------------------------------------

    def public_view(self) -> dict[str, Any]:
        """``GET /na/key-history``: everything a verifier needs, given the root key it holds."""
        history = self.history()
        current = self._na.signer.public_key_b64
        now = self._now()
        signing = history.signing_key_at(now)
        return {
            "sovereign_id": history.sovereign_id,
            "root_public_key": history.root_public_key,
            "handover_seconds": 300,
            "genesis": self._na.genesis_block.model_dump(mode="json"),
            "successions": [s.to_wire() for s in history.successions],
            "keys": [{**k.to_dict(), "current": k.public_key == current} for k in history.keys],
            "signing_key_sequence": signing.key_sequence if signing is not None else None,
        }

    def status(self) -> dict[str, Any]:
        """This instance's key: its position, when it stops signing and why (for status and doctor)."""
        history = self.history()
        key = history.key_for(self._na.signer.public_key_b64)
        if key is None:
            return {"key_sequence": None}
        ends = [t for t in (key.succeeded_at, key.valid_to if key.valid_to_enforced else None) if t is not None]
        return {
            "key_sequence": key.key_sequence, "key_id": key.key_id, "keys": len(history.keys),
            "signs_until": _iso(min(ends)) if ends else None,
            "valid_to": _iso(key.valid_to), "valid_to_enforced": key.valid_to_enforced,
            "succession_pending": key.succeeded_at is not None,
        }

    # -- succession -------------------------------------------------------------

    def succeed(self, data: dict[str, Any], recorded_by: str) -> dict[str, Any]:
        """Check a root-signed succession record, countersign it with the outgoing key and record it."""
        raw = data.get("succession")
        if not isinstance(raw, dict):
            raise BadRequestError("succession is required: the record the root key signed", code="invalid_succession")
        try:
            record = KeySuccessionRecord.model_validate(raw)
        except PydanticValidationError as exc:
            raise BadRequestError("succession does not match the KeySuccessionRecord model",
                                  code="invalid_succession") from exc
        self._load()
        history = self.history()
        current = history.keys[-1]
        now = self._now()
        if current.public_key != self._na.signer.public_key_b64 or not current.signs_at(now):
            raise ConflictError("this instance does not sign with the NA's newest key: a succession is pending, "
                                "or the instance runs an older key", code="succession_pending")
        assert history.root_public_key is not None
        previous_digest = history.successions[-1].digest() if history.successions else None
        refusal, _ = succession_refusal(
            raw, previous=current, previous_digest=previous_digest, sovereign_id=history.sovereign_id,
            root_public_key=history.root_public_key, held_keys=history.all_keys(),
            require_previous_signature=False,
        )
        detail = f"the succession does not continue the key history ({refusal})"
        if refusal == "succession_sovereign_mismatch":
            raise ConflictError(detail, code="succession_sovereign_mismatch")
        if refusal == "succession_chain_break":
            raise ConflictError(detail, code="succession_chain_break")
        if refusal == "succession_key_reused":
            raise ConflictError(detail, code="succession_key_reused")
        if refusal == "succession_not_increasing":
            raise ConflictError(detail, code="succession_not_increasing")
        if refusal == "succession_after_expiry":
            raise ConflictError(detail, code="succession_after_expiry")
        if refusal == "succession_invalid_root_signature":
            raise ValidationError("the succession is not signed by the root key",
                                  code="succession_invalid_root_signature")
        if refusal is not None:
            raise BadRequestError(f"the succession is not in its exact form ({refusal})", code="invalid_succession")
        effective = record.effective_at
        if not now + SUCCESSION_MIN_LEAD <= effective <= now + SUCCESSION_MAX_LEAD \
                or record.new_valid_to - effective > MAX_KEY_VALIDITY:
            raise ConflictError(
                f"effective_at must be {int(SUCCESSION_MIN_LEAD.total_seconds())} seconds to "
                f"{SUCCESSION_MAX_LEAD.days} days from now, and the new key valid for at most "
                f"{MAX_KEY_VALIDITY.days} days", code="succession_times_invalid")
        signed = record if signature_by(record, current.public_key) else sign_succession(
            record, self._na.signer, self._na.key_id)
        recorded_at = self._now()
        row = {
            "key_sequence": record.key_sequence, "key_id": record.new_key_id, "public_key": record.new_public_key,
            "effective_at": effective.isoformat(), "valid_to": record.new_valid_to.isoformat(),
            "valid_to_enforced": 1, "succession_digest": signed.digest(),
            "succession_json": json.dumps(signed.to_wire(), sort_keys=True, separators=(",", ":")),
            "recorded_at": recorded_at.isoformat(),
        }
        db = self._na.db
        payload = signed.to_wire()
        try:
            if self._na.evidence_store_service.enabled:
                def make(write_db: Any) -> list[Any]:
                    write_db.insert_na_key_row(row)
                    return [(
                        lambda seq, prev: build_entry(
                            store_sequence=seq, entry_kind="key_succession", recorded_at=recorded_at,
                            payload=payload, prev_entry_digest=prev, index={"record_id": signed.succession_id},
                        ),
                        payload,
                    )]

                db.append_evidence_entries_with(make)
            else:
                db.add_na_key_row(row)
        except db.integrity_errors as exc:
            raise ConflictError("another succession was recorded first", code="succession_chain_break") from exc
        except db.database_errors as exc:
            raise ServiceUnavailableError("The succession could not be stored",
                                          code="evidence_store_unavailable") from exc
        db.add_audit_event("na_key_succession_recorded", {
            "succession_id": signed.succession_id, "key_sequence": signed.key_sequence,
            "previous_key_id": signed.previous_key_id, "new_key_id": signed.new_key_id,
            "new_public_key": signed.new_public_key, "effective_at": effective.isoformat(),
            "new_valid_to": signed.new_valid_to.isoformat(), "recorded_by": recorded_by,
        })
        self._load()
        self._na.evidence_store_service.maybe_anchor()
        return {"status": "recorded", "succession": signed.to_wire(), "key_history": self.public_view()}
