"""Trust in agreements a caller presents (v1.1.1).

Boundary decisions, legacy decisions and disclosure commitments are made
under an ``AgreementRecord`` the caller sends. Before 1.1.1 the NA only
parsed it: a holder of a standard-tier operator key could present a
fabricated agreement and receive an NA-signed ALLOW. The NA now accepts an
agreement only if two different parties signed it with keys it trusts:

* for its own sovereign (the genesis ``network_name``), its own public key;
* for any other sovereign, the ``subject_public_keys`` of an active, unexpired
  recognition treaty this NA signed for that sovereign that grants at least
  one role. The NA's own key never vouches for another sovereign.

The offerer and the responder must be different sovereigns with disjoint
trusted keys, so one signature can never stand for both parties. Trusted keys
come only from state the NA itself signed; nothing in the request can add one.

One exception keeps NA-issued agreements working: an agreement this NA offered
and accepted itself (``/admin/agreements/offer`` then ``/admin/agreements/accept``,
privileged) carries only the NA's signature. It is trusted when the NA is the
offerer, its key verifies for both parties, and the responder holds an active
treaty from this NA, as for an attestation the NA issues.

This refuses fabricated agreements. It does not bind operator keys to
sovereigns: a standard-tier key can still decide under any trusted agreement
or stored attestation it presents.

v1.5.0: "its own key" is the NA's key history. A treaty counts when the key
valid at its ``issued_at`` signed it, and an agreement the NA signed for its
own sovereign verifies with the key valid at its ``established_at``, so a key
succession leaves every treaty and agreement signed before it vouching.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from ...crypto import verify_model_signature
from ...models.agreement import AgreementRecord
from ...models.canonical_registry import agreement_refusal
from ...trust.agreement import verify_agreement
from ..errors import RequestValidationError

if TYPE_CHECKING:
    from ..server import NetworkAuthorityService


class AgreementTrust:
    """Decide whether an agreement presented by a caller may be used."""

    def __init__(self, na: "NetworkAuthorityService") -> None:
        self._na = na

    def _treaties(self, sovereign_id: str) -> list[Any]:
        """Active, unexpired treaties this NA signed for ``sovereign_id`` that grant a role."""
        now = datetime.now(timezone.utc)
        treaties = []
        for row in self._na.db.list_recognition_treaties(subject_sovereign_id=sovereign_id, status="active"):
            treaty = row["treaty"]
            if row.get("revoked_at") or not (treaty.valid_from <= now < treaty.expires_at):
                continue
            # A treaty that grants no role vouches for nothing.
            if not treaty.scope.allowed_roles:
                continue
            # A treaty counts only if this NA signed it: the issuer field is
            # not enough, and treaties are the NA's own trust decisions.
            # v1.5.0: with the key that was valid when it issued the treaty.
            na_keys = self._na.na_public_keys_at(treaty.issued_at)
            if not any(verify_model_signature(treaty, sig, k) for sig in treaty.signatures for k in na_keys):
                continue
            treaties.append(treaty)
        return treaties

    def trusted_keys(self, sovereign_id: str, at: datetime | None = None) -> list[str]:
        """Public keys this NA trusts for ``sovereign_id`` (possibly none); for its own sovereign, the
        key valid at ``at`` (v1.5.0; every key of its history when ``at`` is None)."""
        na_keys = self._na.na_public_keys_at(None)
        if sovereign_id == self._na.genesis_block.network_name:
            return self._na.na_public_keys_at(at)
        keys: list[str] = []
        for treaty in self._treaties(sovereign_id):
            keys.extend(k for k in treaty.subject_public_keys if k not in na_keys and k not in keys)
        return keys

    def _issued_by_this_na(self, agreement: AgreementRecord) -> bool:
        """An agreement this NA offered and accepted itself (privileged routes)."""
        na_keys = self._na.na_public_keys_at(agreement.established_at)
        return (
            agreement.offerer_sovereign_id == self._na.genesis_block.network_name
            and verify_agreement(agreement, na_keys, na_keys).accepted
            and bool(self._treaties(agreement.responder_sovereign_id))
        )

    def require_trusted(self, agreement: AgreementRecord, *, route: str, raw: Any = None) -> None:
        """Raise ``422 agreement_untrusted`` unless two parties signed with trusted keys.

        v1.2.0: given the agreement as received (``raw``), its signatures must
        cover that form, and it must have no field this release does not know
        and be in canonical form, as every verifier requires.
        """
        offerer, responder = agreement.offerer_sovereign_id, agreement.responder_sovereign_id
        party: str | None = None
        if offerer == responder:
            reason, party = "same_party", offerer
        elif self._issued_by_this_na(agreement):
            na_keys = self._na.na_public_keys_at(agreement.established_at)
            refusal = agreement_refusal(raw, na_keys, na_keys) if raw is not None else None
            if refusal is None:
                return
            reason = refusal
        else:
            offerer_keys = self.trusted_keys(offerer, agreement.established_at)
            responder_keys = self.trusted_keys(responder, agreement.established_at)
            if not offerer_keys:
                reason, party = "unknown_party", offerer
            elif not responder_keys:
                reason, party = "unknown_party", responder
            elif set(offerer_keys) & set(responder_keys):
                reason = "overlapping_party_keys"
            else:
                result = verify_agreement(agreement, offerer_keys, responder_keys)
                refusal = agreement_refusal(raw, offerer_keys, responder_keys) if raw is not None else None
                if result.accepted and refusal is None:
                    return
                reason = refusal or result.reason or "invalid_signature"
        self._na.db.add_audit_event("agreement_untrusted", {
            "route": route,
            "agreement_id": agreement.agreement_id,
            "offerer_sovereign_id": offerer,
            "responder_sovereign_id": responder,
            "reason": reason,
            "party": party,
        })
        raise RequestValidationError(
            "The agreement is not signed by two different parties with keys this Network Authority "
            "trusts (its own key, or a key from an active recognition treaty it issued).",
            code="agreement_untrusted",
            details={"reason": reason, **({"party": party} if party else {})},
        )
