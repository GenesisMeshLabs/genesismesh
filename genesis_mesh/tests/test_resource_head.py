"""Resource heads and bounded histories (v0.63.1).

On a pilot-profile VM, a resource chain of a few thousand records made
`resource history` a 22 MB response, and the TypeScript SDK fetched it before
every governed action to find the chain head. Past 10,000 records the history
was silently cut to the oldest records, so the computed head was stale and
every later action on the resource was refused as a conflict. The head now has
its own indexed lookup, and a cut history says so.
"""

from __future__ import annotations

import pytest

from genesis_mesh.crypto import sign_model
from genesis_mesh.models.execution import ExecutionEvidence
from genesis_mesh.na_service.services import evidence_store as service_module

from .test_evidence_store import SECRET, Controller, _client, _decide, _get, _submit
from .test_na_boundary_policy import _make_service


@pytest.fixture
def client():
    return _client(_make_service(evidence_store="on"))


def _chain(client, n: int) -> list[ExecutionEvidence]:
    controller = Controller(client)
    records: list[ExecutionEvidence] = []
    prior = None
    for i in range(n):
        record = controller.record(_decide(client), action="create" if prior is None else "rotate",
                                   prior_resource=prior)
        assert _submit(client, record).status_code == 201
        records.append(record)
        prior = record
    return records


def test_unknown_resource_has_no_head(client):
    resp = _get(client, "/admin/evidence/resource-heads/kv:nowhere/secret")
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "resource_not_found"


def test_head_is_the_last_record(client):
    records = _chain(client, 3)
    head = _get(client, f"/admin/evidence/resource-heads/{SECRET}").get_json()
    assert head == {"resource_id": SECRET, "resource_sequence": 3, "record_digest": records[-1].digest()}


def test_a_record_linked_to_the_head_is_accepted(client):
    """A controller that only knows the head (not the records) can continue the chain."""
    _chain(client, 2)
    head = _get(client, f"/admin/evidence/resource-heads/{SECRET}").get_json()
    controller = Controller(client, key_id="ctrl-2")
    unlinked = controller.record(_decide(client), action="rotate")
    linked = unlinked.model_copy(update={
        "resource_sequence": head["resource_sequence"] + 1,
        "prev_resource_digest": head["record_digest"], "signature": None,
    })
    linked = linked.model_copy(update={"signature": sign_model(linked, controller.key, "ctrl-2")})
    assert _submit(client, linked).status_code == 201


def test_a_cut_history_says_so_and_the_head_stays_right(client, monkeypatch):
    records = _chain(client, 3)
    monkeypatch.setattr(service_module, "HISTORY_LIMIT", 2)
    history = _get(client, f"/admin/evidence/resources/{SECRET}").get_json()
    assert history["truncated"] is True
    executions = [e for e in history["entries"] if e["entry"]["entry_kind"] == "execution"]
    assert [e["entry"]["resource_sequence"] for e in executions] == [1, 2]
    head = _get(client, f"/admin/evidence/resource-heads/{SECRET}").get_json()
    assert head["resource_sequence"] == 3 and head["record_digest"] == records[-1].digest()


def test_a_complete_history_is_not_marked_truncated(client):
    _chain(client, 2)
    assert _get(client, f"/admin/evidence/resources/{SECRET}").get_json()["truncated"] is False
