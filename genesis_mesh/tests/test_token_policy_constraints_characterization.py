"""Characterization tests for InvocationToken policy constraints (finding F-19).

Pins the CURRENT constraint-evaluation behavior of
``trust/invocation_token.py::_check_policy_constraints`` (:179-203) before
the F-19 remediation flips unknown predicates from fail-OPEN to fail-CLOSED.

The complete predicate inventory understood today (this list is the point —
the fix must keep exactly these working while rejecting everything else):

  * ``not_before:<iso-datetime>``   — enforced; malformed date fails closed
  * ``peer_sovereign:<sovereign>``  — enforced against the bearer id

Anything else — including misspellings, prefix near-misses, and strings that
LOOK like restrictions (``not_after:...``) — is silently treated as satisfied
(invocation_token.py:202). Tests marked "DEFECT PIN" assert that fail-open
behavior on purpose; the F-19 fix is EXPECTED to flip them to
``policy_violated`` and they must be updated deliberately, not deleted.

All verification here injects ``at_time=_NOW`` (frozen clock), so these tests
are immune to the wall-clock expiry that breaks the two CLI tests in
test_invocation_tokens.py (see remediation-log/_baseline-test-run.md).
"""

import base64
from datetime import datetime, timedelta, timezone

import nacl.signing

from genesis_mesh.models.agreement import AgreementRecord, AgreementTerms
from genesis_mesh.trust.invocation_token import (
    issue_invocation_token,
    verify_invocation_token,
)

_NOW = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)


def _make_agreement() -> tuple[AgreementRecord, nacl.signing.SigningKey]:
    sk = nacl.signing.SigningKey.generate()
    terms = AgreementTerms(
        capabilities=["transactions.read"],
        valid_from=_NOW - timedelta(hours=1),
        valid_until=_NOW + timedelta(hours=24),
    )
    agreement = AgreementRecord(
        offer_id="offer-char",
        offerer_sovereign_id="issuer-sovereign",
        responder_sovereign_id="other-sovereign",
        agreed_terms=terms,
        offerer_evidence={"type": "test"},
        responder_evidence={"type": "test"},
        graph_digest="abc123",
        established_at=_NOW,
        expires_at=_NOW + timedelta(hours=24),
    )
    return agreement, sk


def _verify_with_constraints(constraints: list[str]):
    """Issue a token carrying the given constraints and verify it at _NOW."""
    agreement, sk = _make_agreement()
    tok = issue_invocation_token(
        agreement, "agent-b", ["transactions.read"], sk,
        issued_by="op", policy_constraints=constraints, now=_NOW,
    )
    pub = base64.b64encode(bytes(sk.verify_key)).decode()
    return verify_invocation_token(
        tok, [pub],
        requested_capability="transactions.read",
        bearer_sovereign_id="agent-b",
        at_time=_NOW,
    )


# ── The two predicates understood today (must SURVIVE the F-19 fix) ──


def test_not_before_satisfied():
    result = _verify_with_constraints(["not_before:2026-07-01T00:00:00+00:00"])
    assert result.valid is True
    assert result.reason == "valid"


def test_not_before_violated():
    result = _verify_with_constraints(["not_before:2026-07-02T00:00:00+00:00"])
    assert result.valid is False
    assert result.reason == "policy_violated"


def test_not_before_malformed_date_fails_closed():
    """A recognized predicate with an unparsable value already fails closed
    today (invocation_token.py:196-197) — must keep failing after F-19."""
    result = _verify_with_constraints(["not_before:not-a-date"])
    assert result.valid is False
    assert result.reason == "policy_violated"


def test_peer_sovereign_satisfied():
    result = _verify_with_constraints(["peer_sovereign:agent-b"])
    assert result.valid is True


def test_peer_sovereign_violated():
    result = _verify_with_constraints(["peer_sovereign:someone-else"])
    assert result.valid is False
    assert result.reason == "policy_violated"


# ── DEFECT PINS: everything unrecognized passes today (fail-open) ──


def test_unknown_restriction_lookalike_passes():
    """DEFECT PIN (F-19): a constraint that clearly INTENDS to restrict use
    ('not_after' — expired in 2020) is silently ignored and the token
    verifies. After F-19 this must become policy_violated; update
    deliberately then."""
    result = _verify_with_constraints(["not_after:2020-01-01T00:00:00+00:00"])
    assert result.valid is True
    assert result.reason == "valid"


def test_misspelled_known_predicate_passes():
    """DEFECT PIN (F-19): 'notbefore:' (no underscore) misses the
    'not_before:' prefix match and falls through to fail-open."""
    result = _verify_with_constraints(["notbefore:2099-01-01T00:00:00+00:00"])
    assert result.valid is True


def test_prefixless_peer_sovereign_passes():
    """DEFECT PIN (F-19): 'peer_sovereign' without the colon is not matched
    by the 'peer_sovereign:' prefix check and falls through to fail-open."""
    result = _verify_with_constraints(["peer_sovereign"])
    assert result.valid is True


def test_empty_and_arbitrary_constraints_pass():
    """DEFECT PIN (F-19): empty strings and arbitrary text are 'satisfied'."""
    result = _verify_with_constraints(["", "totally-made-up-rule:xyz"])
    assert result.valid is True


def test_issuer_accepts_unknown_constraint_strings():
    """Issue-side pin: issuance performs no predicate validation either
    (invocation_token.py:163) — an unknown constraint is stored verbatim.
    Relevant to the Bucket-B watch-item on cross-version tokens: today an
    older issuer can mint constraints a newer verifier must decide about."""
    agreement, sk = _make_agreement()
    tok = issue_invocation_token(
        agreement, "agent-b", ["transactions.read"], sk,
        issued_by="op",
        policy_constraints=["future_predicate_v99:whatever"],
        now=_NOW,
    )
    assert tok.policy_constraints == ["future_predicate_v99:whatever"]
