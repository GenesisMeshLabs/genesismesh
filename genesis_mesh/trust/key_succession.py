"""NA key history: verify the genesis block and key successions (v1.5.0, Stage 4).

Pure functions. A verifier passes the genesis block and the succession
records as received (JSON objects) and the root public key it holds out of
band; it gets the NA's key history (``NAKeyHistory``) to verify NA
signatures as of each record's time, or the reasons the history is refused.

Checks, in order, for the genesis block: it parses (``genesis_invalid``),
names the root key the verifier holds (``genesis_root_mismatch``), and is
strict like every other root: a signature by that key over it as received,
no unknown field, the canonical form (``unknown_field``,
``non_canonical_form``, otherwise ``genesis_invalid_signature``).

For each succession, in order (v1.5.0 review fixes):

1. it parses, its unknown fields set aside (``payload_invalid``);
2. it has no unknown field (``unknown_field`` when one of its signers
   signed it, ``invalid_signature`` otherwise) and is in canonical form
   (``non_canonical_form``);
3. it names the genesis sovereign (``succession_sovereign_mismatch``);
4. it continues the history (``succession_chain_break``: the next position,
   the current key as the previous one, the previous succession's digest);
5. it names a valid key the history never held and that is not the root
   key (``succession_key_reused``);
6. it was not issued after it takes effect (``succession_backdated``);
7. it takes effect after the previous key did and before the new key's own
   end (``succession_not_increasing``), and before the previous key's
   enforced expiry (``succession_after_expiry``);
8. a signature verifies with the root key
   (``succession_invalid_root_signature``), one with the new key, which
   proves the new key exists and is held (``succession_invalid_new_key_signature``),
   and one with the previous key (``succession_invalid_previous_signature``).
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Sequence

from pydantic import ValidationError

from ..crypto import sign_model, verify_signature
from ..crypto.signing import SigningKeyLike
from ..models.genesis import GenesisBlock, Signature
from ..models.key_succession import KeySuccessionRecord, NAKey, NAKeyHistory, build_history

SuccessionReason = str


@dataclass
class KeyHistoryVerification:
    """Result of verifying a genesis block and its successions."""

    verified: bool = True
    history: NAKeyHistory | None = None
    failures: list[dict[str, Any]] = field(default_factory=list)

    def fail(self, key_sequence: int | None, reason: str, detail: str = "") -> None:
        self.verified = False
        self.failures.append({"key_sequence": key_sequence, "reason": reason, "detail": detail})

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"verified": self.verified, "failures": self.failures}
        if self.history is not None:
            out["keys"] = [k.to_dict() for k in self.history.keys]
        return out


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def valid_public_key(value: Any) -> bool:
    """True when ``value`` is a base64 Ed25519 public key (32 bytes)."""
    if not isinstance(value, str):
        return False
    try:
        return len(base64.b64decode(value, validate=True)) == 32
    except (binascii.Error, ValueError):
        return False


def _signed_by(model: str, raw: dict[str, Any], public_key: str) -> bool:
    from ..models.canonical_registry import signed_as_received

    return signed_as_received(model, raw, [public_key])


def na_record_refusal(model: str, raw: Any, history: NAKeyHistory, *, now: datetime | None = None) -> str | None:
    """Why an NA-signed record of ``model`` does not verify, or None (1.8.0).

    The reference for the ``vouching`` conformance suite. The record is placed at the time
    its kind names (``NA_VOUCHING_TIME_FIELDS``), its signature checked over the record as
    received with the NA keys valid then, and, when ``now`` is given, the vouching horizon
    applied: a record whose key ended more than the hand-over and the grace before ``now``
    no longer vouches for the present. Reasons, in order: ``unknown_field`` or
    ``non_canonical_form``, ``na_key_not_valid_at_time``, ``invalid_signature``,
    ``record_malformed`` (signed, but its model refuses it: a grant whose
    ``valid_from`` lies more than 24 hours after its ``issued_at``), ``outlives_key``.
    Without ``now`` the record is judged at its own time only.
    """
    from ..models.canonical_registry import model_accepts, signed_as_received, strict_refusal
    from ..models.key_succession import NA_VOUCHING_TIME_FIELDS, record_outlives_key

    field_name = NA_VOUCHING_TIME_FIELDS.get(model)
    if field_name is None:
        raise ValueError(f"{model} is not a kind the vouching horizon applies to")
    if not isinstance(raw, dict) or not isinstance(raw.get(field_name), str):
        return "invalid_signature"
    try:
        at = _utc(datetime.fromisoformat(raw[field_name].replace("Z", "+00:00")))
    except ValueError:
        return "invalid_signature"
    keys = history.keys_at(at)
    signer = next((k for k in keys if signed_as_received(model, raw, [k])), None)
    if signer is None:
        others = [k for k in history.all_keys() if k not in keys]
        if others and signed_as_received(model, raw, others):
            return "na_key_not_valid_at_time"
        return "invalid_signature"
    refusal = strict_refusal(model, raw, [signer])
    if refusal is not None:
        return refusal
    if not model_accepts(model, raw):
        return "record_malformed"
    if now is not None and record_outlives_key(history, signer, now):
        return "outlives_key"
    return None


def genesis_refusal(raw: Any, root_public_key: str | None) -> tuple[str | None, GenesisBlock | None]:
    """(reason the genesis block is refused or None, the parsed block).

    v1.5.0 review fixes: the genesis block is the trust anchor of the key
    history, so it is held to the rules of every other signed root: an
    unknown field or a non-canonical form is refused by name.
    """
    from ..models.canonical_registry import strict_refusal, without_unknown_fields

    if not isinstance(raw, dict):
        return "genesis_invalid", None
    try:
        genesis = GenesisBlock.model_validate(without_unknown_fields("GenesisBlock", raw))
    except ValidationError:
        return "genesis_invalid", None
    root = root_public_key or genesis.root_public_key
    if genesis.root_public_key != root:
        return "genesis_root_mismatch", genesis
    form = strict_refusal("GenesisBlock", raw, [root])
    if form in ("unknown_field", "non_canonical_form"):
        return form, genesis
    if form is not None or not _signed_by("GenesisBlock", raw, root):
        return "genesis_invalid_signature", genesis
    return None, genesis


def genesis_key(genesis: GenesisBlock, key_id: str | None = None) -> NAKey:
    """The genesis NA key: valid from the start, its ``valid_to`` not enforced."""
    return NAKey(key_sequence=1, public_key=genesis.network_authority.public_key, key_id=key_id,
                 valid_from=None, succeeded_at=None, valid_to=_utc(genesis.network_authority.valid_to),
                 valid_to_enforced=False)


def succession_refusal(
    raw: Any, *, previous: NAKey, previous_digest: str | None, sovereign_id: str, root_public_key: str,
    held_keys: Sequence[str], require_previous_signature: bool = True,
) -> tuple[str | None, KeySuccessionRecord | None]:
    """(reason one succession record is refused or None, the parsed record), in the order of the
    module docstring. ``previous`` is the key the record must succeed. The NA checks a record
    before it countersigns it (``require_previous_signature=False``)."""
    from ..models.canonical_registry import strict_refusal, without_unknown_fields

    if not isinstance(raw, dict):
        return "payload_invalid", None
    try:
        record = KeySuccessionRecord.model_validate(without_unknown_fields("KeySuccessionRecord", raw))
    except ValidationError:
        return "payload_invalid", None
    # Unknown fields (signed by one of the record's signers: unknown_field; otherwise
    # invalid_signature), then the canonical form.
    signers = [root_public_key, previous.public_key]
    if valid_public_key(record.new_public_key):
        signers.append(record.new_public_key)
    form = strict_refusal("KeySuccessionRecord", raw, signers)
    if form is not None:
        return form, record
    if record.sovereign_id != sovereign_id:
        return "succession_sovereign_mismatch", record
    if (record.key_sequence != previous.key_sequence + 1 or record.previous_public_key != previous.public_key
            or record.previous_succession_digest != previous_digest):
        return "succession_chain_break", record
    if not valid_public_key(record.new_public_key) or record.new_public_key in held_keys \
            or record.new_public_key == root_public_key:
        return "succession_key_reused", record
    if _utc(record.issued_at) > _utc(record.effective_at):
        return "succession_backdated", record
    effective = _utc(record.effective_at)
    if (previous.valid_from is not None and effective <= previous.valid_from) \
            or _utc(record.new_valid_to) <= effective:
        return "succession_not_increasing", record
    if previous.valid_to_enforced and previous.valid_to is not None and effective > previous.valid_to:
        return "succession_after_expiry", record
    if not _signed_by("KeySuccessionRecord", raw, root_public_key):
        return "succession_invalid_root_signature", record
    if not _signed_by("KeySuccessionRecord", raw, record.new_public_key):
        return "succession_invalid_new_key_signature", record
    if require_previous_signature and not _signed_by("KeySuccessionRecord", raw, previous.public_key):
        return "succession_invalid_previous_signature", record
    return None, record


def verify_key_history(
    genesis: Any, successions: Sequence[Any], root_public_key: str | None = None,
    *, genesis_key_id: str | None = None,
) -> KeyHistoryVerification:
    """Verify a genesis block and its successions, in order, and build the key history.

    ``root_public_key`` is the root key the verifier holds out of band; without
    it the genesis block's own root key is used (the NA at start, which holds
    the block it was configured with). Keys in the records prove nothing by
    themselves: the history is accepted only from the root key down. Nothing
    after the first refused record is accepted.
    """
    result = KeyHistoryVerification()
    reason, block = genesis_refusal(genesis, root_public_key)
    if reason is not None or block is None:
        result.fail(1, reason or "genesis_invalid")
        return result
    root = block.root_public_key
    keys = [genesis_key(block, genesis_key_id)]
    records: list[KeySuccessionRecord] = []
    previous_digest: str | None = None
    for raw in successions:
        previous = keys[-1]
        refusal, record = succession_refusal(
            raw, previous=previous, previous_digest=previous_digest, sovereign_id=block.network_name,
            root_public_key=root, held_keys=[k.public_key for k in keys],
        )
        position = record.key_sequence if record is not None else previous.key_sequence + 1
        if refusal is not None or record is None:
            result.fail(position, refusal or "payload_invalid")
            return result
        records.append(record)
        keys = list(build_history(block.network_name, root, keys[0], records).keys)
        previous_digest = record.digest()
    result.history = build_history(block.network_name, root, keys[0], records)
    return result


def sign_succession(record: KeySuccessionRecord, signing_key: SigningKeyLike, key_id: str) -> KeySuccessionRecord:
    """Return the record with one more signature: the root key's offline, the new key's where it is held
    (its proof of possession), the outgoing key's at the NA."""
    signature: Signature = sign_model(record, signing_key, key_id)
    return record.model_copy(update={"signatures": [*record.signatures, signature]})


def signature_by(record: KeySuccessionRecord, public_key: str) -> bool:
    """True when one of the record's signatures verifies with ``public_key``."""
    body = record.to_canonical_json().encode("utf-8")
    return any(verify_signature(body, s.sig, public_key) for s in record.signatures)
