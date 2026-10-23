"""The ``vouching`` conformance suite (1.8.0): records of a succeeded NA key, judged now.

Since 1.5.0 a verifier given the NA's key history places a record at its own
time. That leaves a gap: whoever keeps the outgoing key after a succession can
sign a record dated inside the old key's window. The vouching horizon closes
it: judged now, a record whose key ended more than the hand-over and the grace
ago no longer vouches for the present. Judged at its own time, nothing changes.

Each vector holds the ``audit`` world's key history (a succession on day 10),
one NA-signed record, a ``now`` and optionally a shorter grace; ``expected``
holds the Python reference's verdict judged at the record's own time and
judged now (``trust.key_succession.na_record_refusal``). A verdict is
``null`` when the record verifies, else the reason. Reason codes are the
contract.

Until the SDKs adopt it, only the core runs this suite (``runner.py``); it is
not copied to the SDKs.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from audit_world import KEYS, SOVEREIGN, SUCCESSION_AT, T0, build_world, pub, uid

HANDOVER = timedelta(seconds=300)
GRACE = timedelta(hours=24)
#: The old key's horizon with the default grace: day 10, the hand-over, then 24 hours.
HORIZON = SUCCESSION_AT + HANDOVER + GRACE


def _iso(at: datetime) -> str:
    return at.isoformat().replace("+00:00", "Z")


def _history(inp: dict[str, Any]) -> Any:
    from genesis_mesh.trust.key_succession import verify_key_history

    result = verify_key_history(inp["genesis"], inp["successions"], inp["root_public_key"])
    assert result.history is not None, result.failures
    history = result.history
    if inp.get("grace_seconds") is not None:
        history = history.with_vouching_grace(inp["grace_seconds"])
    return history


def evaluate(vector: dict[str, Any]) -> dict[str, Any]:
    """The Python reference's verdicts for one vector."""
    from genesis_mesh.trust.key_succession import na_record_refusal

    inp = vector["input"]
    history = _history(inp)
    now = datetime.fromisoformat(inp["now"].replace("Z", "+00:00"))
    return {
        "at_record_time": na_record_refusal(vector["model"], inp["record"], history),
        "now": na_record_refusal(vector["model"], inp["record"], history, now=now),
    }


def _sign_list(record: Any, key: str, key_id: str) -> dict[str, Any]:
    from genesis_mesh.crypto import sign_model

    record = record.model_copy(update={"signatures": [sign_model(record.model_copy(update={"signatures": []}),
                                                                  KEYS[key], key_id)]})
    return record.model_dump(mode="json")


def _sign_one(record: Any, key: str, key_id: str) -> dict[str, Any]:
    from genesis_mesh.crypto import sign_model

    record = record.model_copy(update={"signature": sign_model(record.model_copy(update={"signature": None}),
                                                                KEYS[key], key_id)})
    return record.model_dump(mode="json")


def _attestation(at: datetime, key: str, key_id: str, n: int) -> dict[str, Any]:
    from genesis_mesh.models.sovereign import MembershipAttestation

    return _sign_list(MembershipAttestation(
        attestation_id=uid(800 + n), issuer_sovereign_id=SOVEREIGN, subject_id="vendor-acme", roles=["role:client"],
        issued_at=at, valid_from=at, expires_at=at + timedelta(days=365), issued_by=key_id), key, key_id)


def _treaty(at: datetime, key: str, key_id: str, n: int) -> dict[str, Any]:
    from genesis_mesh.models.sovereign import RecognitionTreaty

    return _sign_list(RecognitionTreaty(
        treaty_id=uid(820 + n), issuer_sovereign_id=SOVEREIGN, subject_sovereign_id="sovereign-d",
        subject_public_keys=[pub("a")], issued_at=at, valid_from=at, expires_at=at + timedelta(days=365),
        issued_by=key_id), key, key_id)


def _feed(at: datetime, key: str, key_id: str, n: int) -> dict[str, Any]:
    from genesis_mesh.models.sovereign import SovereignRevocationFeed

    return _sign_list(SovereignRevocationFeed(
        feed_id=uid(840 + n), issuer_sovereign_id=SOVEREIGN, sequence=10**6 + n, issued_at=at, issued_by=key_id),
        key, key_id)


def _grant(at: datetime, key: str, key_id: str, n: int) -> dict[str, Any]:
    from genesis_mesh.models.boundary_policy import AppliedPolicy, policy_set_digest
    from genesis_mesh.models.grants import CapabilityGrant

    applied = [AppliedPolicy(policy_id="secret-limits", version=1, policy_digest="d" * 64, signed_by=key_id)]
    return _sign_one(CapabilityGrant(
        grant_id=uid(860 + n), bearer_key_id="executor-b", bearer_public_key=pub("b"),
        bearer_sovereign_id="sovereign-b", capabilities=["secret.rotate"], basis_kind="attestation",
        basis_id=uid(1), basis_digest="e" * 64, requester_sovereign_id="vendor-acme",
        provider_sovereign_id=SOVEREIGN, valid_from=at, valid_until=at + timedelta(hours=24), max_uses=3,
        max_uses_per_time_token=2,
        policy_binding={"policies": [a.model_dump() for a in applied], "policy_set_digest": policy_set_digest(applied)},
        issued_at=at, issuer_sovereign_id=SOVEREIGN, issued_by=key_id), key, key_id)


BUILDERS = {
    "MembershipAttestation": _attestation,
    "RecognitionTreaty": _treaty,
    "SovereignRevocationFeed": _feed,
    "CapabilityGrant": _grant,
}

#: The old key, the new key, and when each signs (``audit_world.na_key_at``).
OLD = ("c", "na-1")
NEW = ("g", "na-2")


def vouching_vectors() -> list[dict[str, Any]]:
    world = build_world()
    base = {"genesis": world.genesis, "successions": world.successions, "root_public_key": pub("f")}
    out: list[dict[str, Any]] = []

    def add(vid: str, model: str, description: str, record: dict[str, Any], now: datetime,
            grace_seconds: int | None = None) -> None:
        inp: dict[str, Any] = {**base, "record": record, "now": _iso(now)}
        if grace_seconds is not None:
            inp["grace_seconds"] = grace_seconds
        vector = {"id": vid, "kind": "record_vouching", "model": model, "description": description, "input": inp}
        vector["expected"] = evaluate(vector)
        out.append(vector)

    for i, (model, build) in enumerate(sorted(BUILDERS.items())):
        slug = {"CapabilityGrant": "grant", "MembershipAttestation": "attestation",
                "RecognitionTreaty": "treaty", "SovereignRevocationFeed": "feed"}[model]
        before = build(T0 + timedelta(days=1), *OLD, 10 * i)
        add(f"{slug}-old-key-within-grace", model,
            f"A {model} the old key signed before the succession, judged inside the grace: it vouches",
            before, HORIZON - timedelta(seconds=1))
        add(f"{slug}-old-key-after-horizon", model,
            f"The same {model} judged after the horizon: it verifies at its own time, not now",
            before, HORIZON)
        backdated = build(SUCCESSION_AT - timedelta(seconds=1), *OLD, 10 * i + 1)
        add(f"{slug}-old-key-backdated", model,
            f"A {model} the old key's holder dates just inside its window, judged after the horizon",
            backdated, HORIZON + timedelta(days=30))
        after = build(SUCCESSION_AT + HANDOVER + timedelta(seconds=1), *OLD, 10 * i + 2)
        add(f"{slug}-old-key-after-handover", model,
            f"A {model} the old key signed after the hand-over: the key was not valid at its time",
            after, SUCCESSION_AT + timedelta(days=1))
        fresh = build(SUCCESSION_AT + timedelta(hours=1), *NEW, 10 * i + 3)
        add(f"{slug}-new-key", model,
            f"A {model} the new key signed after the succession: no end, so it vouches",
            fresh, HORIZON + timedelta(days=300))
        add(f"{slug}-grace-zero", model,
            f"A {model} of the old key with the grace set to 0, judged just after the hand-over",
            before, SUCCESSION_AT + HANDOVER, grace_seconds=0)
        tampered = json.loads(json.dumps(before))
        tampered["issued_by"] = "na-tampered"
        add(f"{slug}-tampered", model, f"A {model} changed after signing", tampered, HORIZON - timedelta(seconds=1))

    attestation = _attestation(T0 + timedelta(days=1), *OLD, 99)
    add("grace-hint-above-default", "MembershipAttestation",
        "A grace above the default is clamped to 24 hours: past the horizon the record no longer vouches",
        attestation, HORIZON, grace_seconds=10 * 86400)
    add("grace-hint-shorter", "MembershipAttestation",
        "A shorter grace moves the horizon earlier", attestation,
        SUCCESSION_AT + HANDOVER + timedelta(hours=1), grace_seconds=3600)

    # A grant starts within 24 hours of its issue (core 1.8.0), so a key's holder cannot sign one
    # inside the key's window that starts long after the horizon. The model refuses it, whichever
    # key signed it and whenever it is judged.
    for key, issued, n in ((OLD, T0 + timedelta(days=1), 90), (NEW, SUCCESSION_AT + timedelta(hours=1), 91)):
        add(f"grant-valid-from-beyond-max-{key[1]}", "CapabilityGrant",
            f"A grant signed by {key[1]} that starts 30 days after its issue: malformed",
            _late_grant(issued, *key, n), issued + timedelta(hours=1))
    return out


def _late_grant(at: datetime, key: str, key_id: str, n: int) -> dict[str, Any]:
    """A grant issued at ``at`` that starts 30 days later, signed as is (the model refuses it)."""
    from genesis_mesh.models.grants import CapabilityGrant

    grant = CapabilityGrant.model_validate(_grant(at, key, key_id, n))
    late = grant.model_copy(update={"valid_from": at + timedelta(days=30), "valid_until": at + timedelta(days=31)})
    return _sign_one(late, key, key_id)


if __name__ == "__main__":
    print(json.dumps({"suite": "vouching", "vectors": vouching_vectors()}, indent=2))
