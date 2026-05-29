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

    await protocol.handle_route_withdraw(message)

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

    await protocol.handle_route_withdraw(message)

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

    await protocol.handle_route_announce(message)

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

    await protocol.handle_route_announce(message)

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

    await protocol.handle_route_announce(message)

    assert table.get_route("node-c").sequence == 10
