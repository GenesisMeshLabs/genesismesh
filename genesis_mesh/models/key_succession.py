"""Network Authority key succession (v1.5.0, Stage 4).

The genesis block names the NA's first public key and the root key that
signed it. A ``KeySuccessionRecord`` names the next NA key: signed by the
root key, which is kept offline, and by the outgoing NA key. The genesis key
and the successions form the NA's key history; a verifier holding only the
root public key (supplied out of band) rebuilds it and accepts an NA
signature made by the key that was valid at the record's own time, so
records signed before and after a succession keep verifying for years.

Validity windows (``NAKey.accepts``)
------------------------------------
* The genesis key is valid from the start of the network until the first
  succession takes effect. Its ``valid_to`` is not enforced: deployments
  created before 1.5.0 wrote one 90 days after creation.
* A key named by a succession is valid from the succession's
  ``effective_at`` until the next succession takes effect, and never at or
  after its own ``new_valid_to`` (enforced).
* A succeeded key is still accepted for records dated up to
  ``SUCCESSION_HANDOVER`` after the next key took effect: NA instances'
  clocks differ and an entry signed just before the hand-over may be stored
  just after it. The NA stops signing with the outgoing key at
  ``effective_at`` (``NAKey.signs_at``).

The record's time is the time the signer gave it when it signed: for a
store entry, the entry's ``recorded_at``; outside the store, the record's own
time (``anchored_at``, ``created_at``, ``issued_at``...). The table is in
``docs/reference/evidence-event-schema.md``.

Canonical form: every field but ``signatures``, ``previous_succession_digest``
omitted when absent; timestamps UTC. Frozen from 1.5.0 on.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .genesis import Signature

#: How long after a succession takes effect the outgoing key is still accepted
#: (records signed just before the hand-over and stored just after it).
SUCCESSION_HANDOVER = timedelta(seconds=300)

#: A succession takes effect at least this long after the store records it (v1.5.0 review fixes):
#: the NA refuses a shorter lead, and a verifier refuses a ``key_succession`` entry recorded later
#: than ``effective_at`` minus it (``succession_backdated``). Every NA instance learns of a succession
#: (it re-reads the history every 30 seconds) before the outgoing key stops signing.
SUCCESSION_MIN_LEAD = timedelta(seconds=60)

#: The longest lifetime of a decision the NA issues (v1.5.0 review fixes;
#: ``NA_DECISION_LIFETIME_SECONDS`` may only shorten it). A decision signed by a key with an end
#: of validity is refused when it stays valid longer than that end, the hand-over and this
#: lifetime: the holder of a succeeded key cannot mint a long-lived decision dated in its window.
MAX_DECISION_LIFETIME = timedelta(seconds=300)

#: v1.5.0 review fixes: the time an NA-signed record is placed at in the key history (the key that
#: may sign it is the key valid then). In the evidence store every entry is placed at its envelope's
#: ``recorded_at`` (a key succession, an archive, every kind); read alone, outside the store (a pack's
#: trust files, a record verified by itself), a record is placed at its own signed time below.
NA_RECORD_TIME_FIELDS: dict[str, str] = {
    "ArchiveRecord": "archived_at",
    "AuditPackManifest": "created_at",
    "BoundaryDecision": "decision_made_at",
    "BoundaryPolicy": "issued_at",
    "JudgementRecord": "judged_at",
    "JustificationProof": "proof_issued_at",
    "MembershipAttestation": "issued_at",
    "QuarantineRecord": "quarantined_at",
    "RecognitionTreaty": "issued_at",
    "RegistryRecord": "effective_at",
    "RetentionCheckpoint": "created_at",
    "ReviewRecord": "decided_at",
    "StoreAnchor": "anchored_at",
}

#: Optional fields a succession record omits from its signed form when absent.
KEY_SUCCESSION_OMIT_WHEN_NONE: tuple[str, ...] = ("previous_succession_digest",)


def _canonical(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


class KeySuccessionRecord(BaseModel):
    """The NA's next key, signed by the root key, the new key and the outgoing NA key (v1.5.0).

    ``key_sequence`` is the new key's position in the key history (the
    genesis key is 1). ``previous_succession_digest`` links to the previous
    succession (absent for the first). The new key signs from
    ``effective_at`` and never at or after ``new_valid_to``. ``issued_at`` is
    when the root key signed the record, offline. Three signatures over one
    canonical form (v1.5.0 review fixes): the root key's, the new key's (proof
    that the new key exists and is held) and the outgoing key's, which the NA
    adds when it records the succession.
    """

    model_config = ConfigDict(extra="forbid")

    succession_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1, max_length=128)
    sovereign_id: str = Field(..., min_length=1, max_length=256)
    key_sequence: int = Field(..., ge=2)
    previous_key_id: str = Field(..., min_length=1, max_length=128)
    previous_public_key: str = Field(..., min_length=1, max_length=128)
    previous_succession_digest: str | None = Field(default=None, min_length=64, max_length=64)
    new_key_id: str = Field(..., min_length=1, max_length=128)
    new_public_key: str = Field(..., min_length=1, max_length=128)
    effective_at: datetime
    new_valid_to: datetime
    issued_at: datetime
    signatures: list[Signature] = Field(default_factory=list)

    @field_validator("effective_at", "new_valid_to", "issued_at")
    @classmethod
    def _utc(cls, value: datetime, info: Any) -> datetime:
        if value.utcoffset() != timedelta(0):
            raise ValueError(f"{info.field_name} must be a UTC timestamp")
        return value

    def _fields(self, *, signatures: bool) -> dict[str, Any]:
        data = self.model_dump(exclude=None if signatures else {"signatures"}, mode="json")
        return {k: v for k, v in data.items() if not (k in KEY_SUCCESSION_OMIT_WHEN_NONE and v is None)}

    def to_canonical_json(self) -> str:
        """Canonical form both signers sign: ``signatures`` excluded, an absent previous digest omitted."""
        return _canonical(self._fields(signatures=False))

    def to_wire(self) -> dict[str, Any]:
        """The JSON form served, stored and exported: the canonical fields plus the signatures."""
        return self._fields(signatures=True)

    def digest(self) -> str:
        """SHA-256 of the canonical form; the next succession links to it."""
        return hashlib.sha256(self.to_canonical_json().encode("utf-8")).hexdigest()


def _utc_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class NAKey:
    """One key of the NA's key history and the times it is valid at."""

    key_sequence: int
    public_key: str
    key_id: str | None
    #: None for the genesis key: valid from the start of the network.
    valid_from: datetime | None
    #: The next succession's ``effective_at``; None while the key is current.
    succeeded_at: datetime | None
    #: The declared end of validity (the genesis block's, or a succession's ``new_valid_to``).
    valid_to: datetime | None
    #: False for the genesis key (v1.5.0: deployments before it carry a 90-day ``valid_to``).
    valid_to_enforced: bool

    def accepts(self, at: datetime) -> bool:
        """True when a record dated ``at`` may carry this key's signature (with the hand-over)."""
        at = _utc_aware(at)
        if self.valid_from is not None and at < self.valid_from:
            return False
        if self.succeeded_at is not None and at >= self.succeeded_at + SUCCESSION_HANDOVER:
            return False
        if self.valid_to_enforced and self.valid_to is not None and at >= self.valid_to:
            return False
        return True

    def signs_at(self, at: datetime) -> bool:
        """True when the NA may sign with this key at ``at`` (no hand-over)."""
        at = _utc_aware(at)
        if self.valid_from is not None and at < self.valid_from:
            return False
        if self.succeeded_at is not None and at >= self.succeeded_at:
            return False
        if self.valid_to_enforced and self.valid_to is not None and at >= self.valid_to:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        def iso(value: datetime | None) -> str | None:
            return value.isoformat().replace("+00:00", "Z") if value is not None else None

        return {
            "key_sequence": self.key_sequence, "key_id": self.key_id, "public_key": self.public_key,
            "valid_from": iso(self.valid_from), "succeeded_at": iso(self.succeeded_at),
            "valid_to": iso(self.valid_to), "valid_to_enforced": self.valid_to_enforced,
        }


@dataclass(frozen=True)
class NAKeyHistory:
    """The NA's keys in order, from a verified genesis block and successions (v1.5.0).

    Iterating yields every public key, so code that needs no time (an
    admin request's audience, a record's unknown fields) reads it as the
    list of NA keys it used to take.
    """

    sovereign_id: str
    root_public_key: str | None
    keys: tuple[NAKey, ...]
    successions: tuple[KeySuccessionRecord, ...] = ()

    def __iter__(self) -> Iterator[str]:
        return iter(self.all_keys())

    def __len__(self) -> int:
        return len(self.keys)

    def __getitem__(self, index: int) -> str:
        return self.keys[index].public_key

    def all_keys(self) -> list[str]:
        return [k.public_key for k in self.keys]

    def keys_at(self, at: datetime) -> list[str]:
        """The public keys a record dated ``at`` may be signed with."""
        return [k.public_key for k in self.keys if k.accepts(at)]

    def key_for(self, public_key: str) -> NAKey | None:
        return next((k for k in self.keys if k.public_key == public_key), None)

    def signing_key_at(self, at: datetime) -> NAKey | None:
        """The key the NA signs with at ``at`` (None in a gap after an enforced expiry)."""
        return next((k for k in self.keys if k.signs_at(at)), None)

    @classmethod
    def of_keys(cls, public_keys: Sequence[str], sovereign_id: str = "") -> "NAKeyHistory":
        """Keys valid at every time: what a list of NA keys meant before 1.5.0."""
        return cls(sovereign_id=sovereign_id, root_public_key=None, keys=tuple(
            NAKey(key_sequence=i + 1, public_key=k, key_id=None, valid_from=None, succeeded_at=None,
                  valid_to=None, valid_to_enforced=False)
            for i, k in enumerate(public_keys)
        ))


def build_history(
    sovereign_id: str, root_public_key: str | None, genesis_key: NAKey, successions: Sequence[KeySuccessionRecord],
) -> NAKeyHistory:
    """The key windows of a genesis key and its successions, in order (their signatures checked elsewhere)."""
    keys = [genesis_key]
    for record in successions:
        previous = keys[-1]
        effective = _utc_aware(record.effective_at)
        keys[-1] = NAKey(previous.key_sequence, previous.public_key, previous.key_id or record.previous_key_id,
                         previous.valid_from, effective, previous.valid_to, previous.valid_to_enforced)
        keys.append(NAKey(key_sequence=record.key_sequence, public_key=record.new_public_key,
                          key_id=record.new_key_id, valid_from=effective, succeeded_at=None,
                          valid_to=_utc_aware(record.new_valid_to), valid_to_enforced=True))
    return NAKeyHistory(sovereign_id=sovereign_id, root_public_key=root_public_key, keys=tuple(keys),
                        successions=tuple(successions))


def decision_outlives_key(keys: "Sequence[str] | NAKeyHistory", public_key: str, valid_until: datetime) -> bool:
    """True when a decision signed by ``public_key`` stays valid past what that key may vouch for
    (v1.5.0 review fixes): the key's end (its succession, or its enforced ``valid_to``), the
    hand-over and ``MAX_DECISION_LIFETIME``. A plain list of keys has no ends."""
    if not isinstance(keys, NAKeyHistory):
        return False
    key = keys.key_for(public_key)
    if key is None:
        return False
    ends = [t for t in (key.succeeded_at, key.valid_to if key.valid_to_enforced else None) if t is not None]
    if not ends:
        return False
    return _utc_aware(valid_until) > min(ends) + SUCCESSION_HANDOVER + MAX_DECISION_LIFETIME


def na_keys_at(keys: "Sequence[str] | NAKeyHistory", at: datetime | None) -> list[str]:
    """The NA public keys a record dated ``at`` may be signed with.

    A plain list of keys (before 1.5.0, and callers that hold one key) is
    valid at every time; a key history is read at ``at`` (every key when
    ``at`` is None).
    """
    if isinstance(keys, NAKeyHistory):
        return keys.keys_at(at) if at is not None else keys.all_keys()
    return list(keys)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
