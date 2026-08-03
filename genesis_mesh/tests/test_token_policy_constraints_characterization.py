"""Characterization + regression tests for InvocationToken policy constraints
(finding F-19).

Originally pinned the fail-OPEN behavior of
``trust/invocation_token.py::_check_policy_constraints``. The F-19 remediation
flipped unknown predicates from fail-OPEN to fail-CLOSED, and the four tests
below that were marked "DEFECT PIN" have been updated accordingly — they now
assert the defended behavior and serve as the F-19 regression tests.

The complete predicate inventory understood today (this list is the point —
the fix keeps exactly these working while rejecting everything else):

  * ``not_before:<iso-datetime>``   — enforced; malformed date fails closed
  * ``peer_sovereign:<sovereign>``  — enforced against the bearer id

Anything else — including misspellings, prefix near-misses, and strings that
LOOK like restrictions (``not_after:...``) — is now rejected with
``policy_violated`` rather than silently treated as satisfied.

All verification here injects ``at_time=_NOW`` (frozen clock), so these tests
are immune to the wall-clock expiry that breaks the two CLI tests in
test_invocation_tokens.py (see remediation-log/_baseline-test-run.md).
"""

import base64
import logging
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


# ── F-19 REGRESSION: everything unrecognized is now rejected (fail-closed) ──
#
# These four were "DEFECT PIN" tests asserting valid is True before the fix.


def test_unknown_restriction_lookalike_rejected():
    """F-19 regression: a constraint that clearly INTENDS to restrict use
    ('not_after' — expired in 2020) is no longer silently ignored."""
    result = _verify_with_constraints(["not_after:2020-01-01T00:00:00+00:00"])
    assert result.valid is False
    assert result.reason == "policy_violated"


def test_misspelled_known_predicate_rejected():
    """F-19 regression: 'notbefore:' (no underscore) misses the 'not_before:'
    prefix match; a near-miss must not be read as 'no constraint'."""
    result = _verify_with_constraints(["notbefore:2099-01-01T00:00:00+00:00"])
    assert result.valid is False
    assert result.reason == "policy_violated"


def test_prefixless_peer_sovereign_rejected():
    """F-19 regression: 'peer_sovereign' without the colon is not matched by
    the 'peer_sovereign:' prefix check, so it is unevaluable → rejected."""
    result = _verify_with_constraints(["peer_sovereign"])
    assert result.valid is False
    assert result.reason == "policy_violated"


def test_empty_and_arbitrary_constraints_rejected():
    """F-19 regression: empty strings and arbitrary text are not 'satisfied'."""
    result = _verify_with_constraints(["", "totally-made-up-rule:xyz"])
    assert result.valid is False
    assert result.reason == "policy_violated"


def test_nf10_poc_unknown_predicates_rejected():
    """F-19 regression, replaying the exact Phase-1 PoC payload from
    verification/evidence/NF-10.log: an issuer writes 'geo:eu-only' and
    'max_amount:100' believing they are enforced. Baseline verdict was
    valid=True reason='valid' (VULN-CONFIRMED); must now be policy_violated."""
    result = _verify_with_constraints(["geo:eu-only", "max_amount:100"])
    assert result.valid is False
    assert result.reason == "policy_violated"


def test_nf10_poc_recognized_constraint_control():
    """The NF-10 control leg: a RECOGNIZED constraint that fails must still be
    rejected for the same reason — proving the fix did not simply reject
    everything."""
    result = _verify_with_constraints(["peer_sovereign:someone-else"])
    assert result.valid is False
    assert result.reason == "policy_violated"


def test_issuer_accepts_unknown_constraint_strings():
    """Issue-side pin: issuance still performs no predicate REJECTION — an
    unknown constraint is stored verbatim (it may be intended for a newer
    verifier); F-19 only added a warning on this path. Relevant to the
    Bucket-B watch-item on cross-version tokens."""
    agreement, sk = _make_agreement()
    tok = issue_invocation_token(
        agreement, "agent-b", ["transactions.read"], sk,
        issued_by="op",
        policy_constraints=["future_predicate_v99:whatever"],
        now=_NOW,
    )
    assert tok.policy_constraints == ["future_predicate_v99:whatever"]


def test_issuer_warns_on_unknown_constraint(caplog):
    """F-19: the issuance-side warning names the predicate, so a typo'd
    --constraint surfaces at mint time instead of as an opaque
    policy_violated at use time."""
    agreement, sk = _make_agreement()
    with caplog.at_level(logging.WARNING, logger="genesis_mesh.trust.invocation_token"):
        issue_invocation_token(
            agreement, "agent-b", ["transactions.read"], sk,
            issued_by="op",
            policy_constraints=["geo:eu-only"],
            now=_NOW,
        )
    assert "geo:eu-only" in caplog.text


def test_verifier_warns_naming_the_unrecognized_predicate(caplog):
    """F-19 / Bucket-B watch-item: a cross-version rejection must be
    diagnosable — the log has to say WHICH predicate this build didn't know,
    not just 'policy_violated'."""
    with caplog.at_level(logging.WARNING, logger="genesis_mesh.trust.invocation_token"):
        result = _verify_with_constraints(["geo:eu-only"])
    assert result.reason == "policy_violated"
    assert "geo:eu-only" in caplog.text
    assert "not_before:" in caplog.text  # tells the operator what IS understood
