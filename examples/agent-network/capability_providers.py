"""Provider helpers for executable Genesis Mesh agent capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from genesis_mesh.models.discovery import AgentDescriptor

from agent_protocol import CapabilityMetadata


class CapabilityProvider(Protocol):
    """A local implementation of one executable capability."""

    metadata: CapabilityMetadata

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Run the capability and return JSON-safe result data."""


@dataclass
class ProviderRegistry:
    """In-process registry of capability providers for an agent."""

    providers: dict[str, CapabilityProvider]

    @classmethod
    def from_providers(cls, providers: list[CapabilityProvider]) -> "ProviderRegistry":
        """Create a registry from provider instances."""
        return cls({provider.metadata.name: provider for provider in providers})

    def advertised_names(self) -> list[str]:
        """Return capability names for the existing NA discovery registry."""
        return sorted(self.providers)

    def advertised_metadata(self) -> list[dict[str, str]]:
        """Return minimal capability metadata for descriptor metadata."""
        return [self.providers[name].metadata.to_dict() for name in sorted(self.providers)]

    async def execute(self, capability: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a known capability or raise a controlled ValueError."""
        provider = self.providers.get(capability)
        if provider is None:
            raise ValueError(f"unknown capability: {capability}")
        return await provider.execute(arguments)


def select_provider(
    descriptors: list[AgentDescriptor],
    capability: str,
    exclude_node_keys: set[str] | None = None,
) -> AgentDescriptor:
    """Select one provider deterministically from discovered descriptors."""
    exclude = exclude_node_keys or set()
    candidates = [
        descriptor
        for descriptor in descriptors
        if descriptor.node_public_key not in exclude
        and capability in descriptor.capabilities
    ]
    if not candidates:
        raise ValueError(f"no provider available for capability {capability}")
    return sorted(candidates, key=lambda item: (item.agent_id, item.node_public_key))[0]


def provider_uri(descriptor: AgentDescriptor) -> str:
    """Return the provider's WebSocket endpoint URI."""
    return descriptor.endpoint.to_uri()
