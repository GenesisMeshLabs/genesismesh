"""The vouching horizon (1.8.0): how long a record of a succeeded NA key vouches for the present.

The ``vouching`` conformance suite pins the verdicts on signed records; these tests pin the
model helpers it rests on.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from genesis_mesh.models.key_succession import (
    MAX_DECISION_LIFETIME,
    SUCCESSION_HANDOVER,
    SUCCESSION_VOUCHING_GRACE,
    NAKey,
    NAKeyHistory,
    decision_outlives_key,
    na_keys_vouching_at,
    record_outlives_key,
)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
SUCCEEDED = T0 + timedelta(days=10)


def _history(**kwargs) -> NAKeyHistory:
    old = NAKey(key_sequence=1, public_key="old", key_id="na-1", valid_from=None, succeeded_at=SUCCEEDED,
                valid_to=None, valid_to_enforced=False)
    new = NAKey(key_sequence=2, public_key="new", key_id="na-2", valid_from=SUCCEEDED, succeeded_at=None,
                valid_to=SUCCEEDED + timedelta(days=365), valid_to_enforced=True)
    return NAKeyHistory(sovereign_id="TEST", root_public_key="root", keys=(old, new), **kwargs)


def test_a_keys_end_is_its_succession_or_its_enforced_valid_to():
    history = _history()
    assert history.keys[0].end == SUCCEEDED
    assert history.keys[1].end == SUCCEEDED + timedelta(days=365)
    genesis = NAKey(key_sequence=1, public_key="g", key_id=None, valid_from=None, succeeded_at=None,
                    valid_to=T0 + timedelta(days=90), valid_to_enforced=False)
    assert genesis.end is None  # the genesis key's valid_to is not enforced


def test_a_record_of_a_succeeded_key_vouches_until_the_hand_over_and_the_grace():
    history = _history()
    horizon = SUCCEEDED + SUCCESSION_HANDOVER + SUCCESSION_VOUCHING_GRACE
    assert history.vouches_until("old") == horizon
    assert not record_outlives_key(history, "old", horizon - timedelta(seconds=1))
    assert record_outlives_key(history, "old", horizon)
    # The current key has an end too (its enforced valid_to), but it is far off.
    assert not record_outlives_key(history, "new", horizon + timedelta(days=30))
    assert history.vouches_until("unknown") is None
    assert not record_outlives_key(history, "unknown", horizon + timedelta(days=30))


def test_keys_vouching_at_drops_the_keys_past_their_horizon():
    history = _history()
    at = SUCCEEDED - timedelta(days=1)
    assert na_keys_vouching_at(history, at, SUCCEEDED) == ["old"]
    assert na_keys_vouching_at(history, at, SUCCEEDED + timedelta(days=2)) == []


def test_a_plain_list_of_keys_has_no_ends():
    assert not record_outlives_key(["old"], "old", T0 + timedelta(days=1000))
    assert na_keys_vouching_at(["old", "new"], None, T0 + timedelta(days=1000)) == ["old", "new"]


def test_the_grace_can_only_be_shortened():
    history = _history()
    assert history.with_vouching_grace(None) is history
    assert history.with_vouching_grace(0).vouching_grace == timedelta(0)
    assert history.with_vouching_grace(3600).vouching_grace == timedelta(hours=1)
    assert history.with_vouching_grace(10 * 86400).vouching_grace == SUCCESSION_VOUCHING_GRACE
    assert history.with_vouching_grace(-5).vouching_grace == timedelta(0)
    # Once shortened, it cannot be lengthened again.
    assert history.with_vouching_grace(3600).with_vouching_grace(7200).vouching_grace == timedelta(hours=1)
    with pytest.raises(ValueError):
        _history(vouching_grace=SUCCESSION_VOUCHING_GRACE + timedelta(seconds=1))
    with pytest.raises(ValueError):
        _history(vouching_grace=timedelta(seconds=-1))


def test_a_zero_grace_ends_vouching_at_the_hand_over():
    history = _history().with_vouching_grace(0)
    assert history.vouches_until("old") == SUCCEEDED + SUCCESSION_HANDOVER
    assert record_outlives_key(history, "old", SUCCEEDED + SUCCESSION_HANDOVER)


def test_the_decision_bound_is_unchanged():
    history = _history()
    limit = SUCCEEDED + SUCCESSION_HANDOVER + MAX_DECISION_LIFETIME
    assert not decision_outlives_key(history, "old", limit)
    assert decision_outlives_key(history, "old", limit + timedelta(seconds=1))
    assert not decision_outlives_key(["old"], "old", limit + timedelta(days=1))
