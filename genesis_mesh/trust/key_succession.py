"""NA key history: verify the genesis block and key successions (v1.5.0, Stage 4).

Pure functions. A verifier passes the genesis block and the succession
records as received (JSON objects) and the root public key it holds out of
band; it gets the NA's key history (``NAKeyHistory``) to verify NA
signatures as of each record's time, or the reasons the history is refused.

Checks, in order, for the genesis block: it parses (``genesis_invalid``),
names the root key the verifier holds (``genesis_root_mismatch``), and a
signature over it as received verifies with that key
(``genesis_invalid_signature``). For each succession, in order: it parses
(``payload_invalid``), has no unknown field and is in canonical form
(``unknown_field``, ``non_canonical_form``, ``invalid_signature`` as for every
record), names the genesis sovereign (``succession_sovereign_mismatch``),
continues the history (``succession_chain_break``: the next position, the
current key as the previous one, the previous succession's digest), names a
key the history never held (``succession_key_reused``), takes effect after
the previous key did and before the new key's own end
(``succession_not_increasing``), and before the previous key's enforced
expiry (``succession_after_expiry``); a signature verifies with the root key
(``succession_invalid_root_signature``) and one with the previous key
(``succession_invalid_previous_signature``).
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


def genesis_refusal(raw: Any, root_public_key: str | None) -> tuple[str | None, GenesisBlock | None]:
    """(reason the genesis block is refused or None, the parsed block)."""
    if not isinstance(raw, dict):
        return "genesis_invalid", None
    try:
        genesis = GenesisBlock.model_validate(raw)
    except ValidationError:
        return "genesis_invalid", None
    root = root_public_key or genesis.root_public_key
    if genesis.root_public_key != root:
        return "genesis_root_mismatch", genesis
    if not _signed_by("GenesisBlock", raw, root):
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
    from ..models.canonical_registry import strict_refusal, unknown_fields

    if not isinstance(raw, dict):
        return "payload_invalid", None
    if unknown_fields("KeySuccessionRecord", raw):
        # Signed over a field this release does not know (unknown_field), or not signed as received.
        return strict_refusal("KeySuccessionRecord", raw, [root_public_key, previous.public_key]), None
    try:
        record = KeySuccessionRecord.model_validate(raw)
    except ValidationError:
        return "payload_invalid", None
    form = strict_refusal("KeySuccessionRecord", raw, [root_public_key, previous.public_key])
    if form is not None:
        return form, record
    if record.sovereign_id != sovereign_id:
        return "succession_sovereign_mismatch", record
    if (record.key_sequence != previous.key_sequence + 1 or record.previous_public_key != previous.public_key
            or record.previous_succession_digest != previous_digest):
        return "succession_chain_break", record
    if not valid_public_key(record.new_public_key) or record.new_public_key in held_keys:
        return "succession_key_reused", record
    effective = _utc(record.effective_at)
    if (previous.valid_from is not None and effective <= previous.valid_from) \
            or _utc(record.new_valid_to) <= effective:
        return "succession_not_increasing", record
    if previous.valid_to_enforced and previous.valid_to is not None and effective > previous.valid_to:
        return "succession_after_expiry", record
    if not _signed_by("KeySuccessionRecord", raw, root_public_key):
        return "succession_invalid_root_signature", record
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
    """Return the record with one more signature (the root key's offline, the outgoing key's at the NA)."""
    signature: Signature = sign_model(record, signing_key, key_id)
    return record.model_copy(update={"signatures": [*record.signatures, signature]})


def signature_by(record: KeySuccessionRecord, public_key: str) -> bool:
    """True when one of the record's signatures verifies with ``public_key``."""
    body = record.to_canonical_json().encode("utf-8")
    return any(verify_signature(body, s.sig, public_key) for s in record.signatures)
