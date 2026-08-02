"""Tests for routing protocol hardening behavior."""

import pytest

from genesis_mesh.routing.protocol import RoutingProtocol
from genesis_mesh.routing.table import RoutingTable
from genesis_mesh.transport.protocol import MeshMessage, MessageType, RouteInfo


@pytest.mark.asyncio
async def test_route_withdraw_removes_route_learned_from_sender():
    """A withdraw removes only routes learned from the withdrawing sender."""
    broadcasts = []
    async def broadcast(message):
        """Record a broadcast routing message."""
        broadcasts.append(message)

    table = RoutingTable("node-a")
    await table.add_neighbor("node-b")
    await table.update_route(
        destination="node-c",
        next_hop="node-b",
        metric=1,
        sequence=1,
        learned_from="node-b",
    )
    protocol = RoutingProtocol("node-a", table, broadcast)

    message = MeshMessage(
        message_type=MessageType.ROUTE_WITHDRAW,
        sender_id="node-b",
        payload={"destinations": ["node-c"]},
    )

    await protocol.handle_route_withdraw(message, "node-b")

    assert table.get_route("node-c") is None


@pytest.mark.asyncio
async def test_route_withdraw_keeps_route_learned_from_other_sender():
    """A withdraw cannot remove a route learned from a different peer."""
    broadcasts = []
    async def broadcast(message):
        """Record a broadcast routing message."""
        broadcasts.append(message)

    table = RoutingTable("node-a")
    await table.add_neighbor("node-b")
    await table.add_neighbor("node-d")
    await table.update_route(
        destination="node-c",
        next_hop="node-d",
        metric=1,
        sequence=1,
        learned_from="node-d",
    )
    protocol = RoutingProtocol("node-a", table, broadcast)

    message = MeshMessage(
        message_type=MessageType.ROUTE_WITHDRAW,
        sender_id="node-b",
        payload={"destinations": ["node-c"]},
    )

    await protocol.handle_route_withdraw(message, "node-b")

    assert table.get_route("node-c") is not None


@pytest.mark.asyncio
async def test_route_announce_rejects_metric_zero():
    """A gossip route with metric zero is rejected."""
    broadcasts = []
    async def broadcast(message):
        """Record a broadcast routing message."""
        broadcasts.append(message)

    table = RoutingTable("node-a")
    await table.add_neighbor("node-b")
    protocol = RoutingProtocol("node-a", table, broadcast)
    route = RouteInfo(
        destination="node-c",
        next_hop="node-c",
        metric=0,
        sequence=1,
    )
    message = MeshMessage(
        message_type=MessageType.ROUTE_ANNOUNCE,
        sender_id="node-b",
        payload={"routes": [route.model_dump()]},
    )

    await protocol.handle_route_announce(message, "node-b")

    assert table.get_route("node-c") is None


@pytest.mark.asyncio
async def test_route_announce_rejects_revoked_sender():
    """Route announcements from revoked senders are ignored."""
    broadcasts = []
    async def broadcast(message):
        """Record a broadcast routing message."""
        broadcasts.append(message)

    table = RoutingTable("node-a")
    await table.add_neighbor("node-b")
    protocol = RoutingProtocol(
        "node-a",
        table,
        broadcast,
        is_revoked_sender=lambda sender_id: sender_id == "node-b",
    )
    route = RouteInfo(
        destination="node-c",
        next_hop="node-c",
        metric=1,
        sequence=1,
    )
    message = MeshMessage(
        message_type=MessageType.ROUTE_ANNOUNCE,
        sender_id="node-b",
        payload={"routes": [route.model_dump()]},
    )

    await protocol.handle_route_announce(message, "node-b")

    assert table.get_route("node-c") is None


@pytest.mark.asyncio
async def test_route_announce_rejects_stale_sequence():
    """A lower route sequence does not replace a fresher route."""
    broadcasts = []
    async def broadcast(message):
        """Record a broadcast routing message."""
        broadcasts.append(message)

    table = RoutingTable("node-a")
    await table.add_neighbor("node-b")
    await table.update_route(
        destination="node-c",
        next_hop="node-b",
        metric=3,
        sequence=10,
        learned_from="node-b",
    )
    protocol = RoutingProtocol("node-a", table, broadcast)
    route = RouteInfo(
        destination="node-c",
        next_hop="node-c",
        metric=1,
        sequence=9,
    )
    message = MeshMessage(
        message_type=MessageType.ROUTE_ANNOUNCE,
        sender_id="node-b",
        payload={"routes": [route.model_dump()]},
    )

    await protocol.handle_route_announce(message, "node-b")

    assert table.get_route("node-c").sequence == 10


# ---------------------------------------------------------------------------
# F-02 — per-message sender_id must never override the authenticated peer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_withdraw_ignores_forged_sender_id():
    """A neighbor cannot withdraw another node's routes by forging sender_id.

    This is the F-02 proof-of-concept (evidence NF-01): attacker 'M-attacker'
    sends ROUTE_WITHDRAW stamped sender_id='P-victim'. The victim's route must
    survive, because M never taught this node that route.
    """
    async def broadcast(message):
        """Ignore outbound routing broadcasts."""

    table = RoutingTable("V-self")
    await table.add_neighbor("P-victim")
    await table.add_neighbor("M-attacker")
    await table.update_route(
        destination="dest-D",
        next_hop="P-victim",
        metric=2,
        sequence=5,
        learned_from="P-victim",
    )
    protocol = RoutingProtocol("V-self", table, broadcast)

    forged = MeshMessage(
        message_type=MessageType.ROUTE_WITHDRAW,
        sender_id="P-victim",  # forged; the frame really arrived from M-attacker
        payload={"destinations": ["dest-D"]},
    )

    await protocol.handle_route_withdraw(forged, "M-attacker")

    assert table.get_route("dest-D") is not None
    assert table.get_route("dest-D").learned_from == "P-victim"


@pytest.mark.asyncio
async def test_route_announce_attributes_route_to_authenticated_peer():
    """A route is attributed to the peer that sent it, not to the claimed sender."""
    async def broadcast(message):
        """Ignore outbound routing broadcasts."""

    table = RoutingTable("V-self")
    await table.add_neighbor("P-victim")
    await table.add_neighbor("M-attacker")
    protocol = RoutingProtocol("V-self", table, broadcast)

    route = RouteInfo(
        destination="dest-D",
        next_hop="dest-D",
        metric=1,
        sequence=1,
    )
    forged = MeshMessage(
        message_type=MessageType.ROUTE_ANNOUNCE,
        sender_id="P-victim",  # forged; the frame really arrived from M-attacker
        payload={"routes": [route.model_dump()]},
    )

    await protocol.handle_route_announce(forged, "M-attacker")

    installed = table.get_route("dest-D")
    assert installed is not None
    assert installed.learned_from == "M-attacker"
    assert installed.next_hop == "M-attacker"


@pytest.mark.asyncio
async def test_route_announce_revocation_gate_uses_authenticated_peer():
    """A revoked peer cannot evade the revocation gate by relabelling sender_id."""
    async def broadcast(message):
        """Ignore outbound routing broadcasts."""

    table = RoutingTable("V-self")
    await table.add_neighbor("M-attacker")
    protocol = RoutingProtocol(
        "V-self",
        table,
        broadcast,
        is_revoked_sender=lambda node_id: node_id == "M-attacker",
    )

    route = RouteInfo(
        destination="dest-D",
        next_hop="dest-D",
        metric=1,
        sequence=1,
    )
    forged = MeshMessage(
        message_type=MessageType.ROUTE_ANNOUNCE,
        sender_id="node-not-revoked",  # forged to dodge the revocation check
        payload={"routes": [route.model_dump()]},
    )

    await protocol.handle_route_announce(forged, "M-attacker")

    assert table.get_route("dest-D") is None
