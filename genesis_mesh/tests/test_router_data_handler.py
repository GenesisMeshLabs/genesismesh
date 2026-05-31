"""Unit test for the MeshRouter.data_handler callback added for application agents."""

import asyncio

import pytest

from genesis_mesh.routing.router import MeshRouter
from genesis_mesh.routing.table import RoutingTable
from genesis_mesh.transport.protocol import create_data_message


@pytest.mark.asyncio
async def test_router_invokes_data_handler_on_local_delivery():
    """A DATA message addressed to the local node fires data_handler."""
    node_id = "local-node"
    delivered: list = []

    async def handler(message):
        delivered.append(message)

    table = RoutingTable(node_id)
    router = MeshRouter(
        node_id=node_id,
        routing_table=table,
        get_connection=lambda peer_id: None,
        data_handler=handler,
    )

    message = create_data_message(
        sender_id="remote-node",
        recipient_id=node_id,
        data=b"hello agent",
    )

    assert await router.route_message(message) is True
    assert len(delivered) == 1
    assert delivered[0].sender_id == "remote-node"
    assert delivered[0].recipient_id == node_id


@pytest.mark.asyncio
async def test_router_handler_exception_does_not_break_delivery():
    """A raising data_handler must not crash the router."""
    node_id = "local-node"

    async def broken(message):
        raise RuntimeError("application bug")

    table = RoutingTable(node_id)
    router = MeshRouter(
        node_id=node_id,
        routing_table=table,
        get_connection=lambda peer_id: None,
        data_handler=broken,
    )

    message = create_data_message(
        sender_id="remote-node",
        recipient_id=node_id,
        data=b"payload",
    )

    # Router still returns True (delivered) even though the app handler raised.
    assert await router.route_message(message) is True


@pytest.mark.asyncio
async def test_router_without_handler_still_delivers_locally():
    """Backward compatibility: data_handler is optional."""
    node_id = "local-node"

    table = RoutingTable(node_id)
    router = MeshRouter(
        node_id=node_id,
        routing_table=table,
        get_connection=lambda peer_id: None,
    )

    message = create_data_message(
        sender_id="remote-node",
        recipient_id=node_id,
        data=b"payload",
    )

    assert await router.route_message(message) is True
