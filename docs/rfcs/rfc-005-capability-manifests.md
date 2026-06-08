# RFC-005 — Capability Manifests

Status: Draft
Created: 2026-06-08
Authors: Genesis Mesh contributors
Requires: RFC-001

## Abstract

This RFC defines how a node or agent advertises what it can do, so peers can
discover providers by capability instead of by raw public key. It defines the
signed capability descriptor, its time-to-live (TTL) semantics, and the rule
that capability discovery never overrides trust: a discovered provider is still
subject to identity, policy, and revocation checks before it is used.

## Motivation

A trust fabric is more useful when participants can find each other by function
("who can do `llm:chat`?") rather than by key. But discovery must not become a
trust backdoor. RFC-005 specifies a capability announcement that is signed,
expiring, and trust-subordinate, so capability routing rides on top of the trust
layer rather than around it.

## Terminology

- **Capability** — a tag describing something a provider can do, for example
  `llm:chat` or `kb:security`.
- **Capability descriptor** — the signed announcement a provider publishes
  (the `AgentDescriptor` model in the reference implementation).
- **Registry** — the Network Authority service registry that holds active
  descriptors, keyed by node public key.
- **TTL** — the validity window after which a descriptor is stale and **MUST**
  be treated as absent.

## Normative requirements

1. A capability descriptor **MUST** carry `agent_id`, `node_public_key`,
   `network_name`, `capabilities`, `endpoint`, `registered_at`, and
   `expires_at`.
2. A descriptor **MUST** be signed by the provider's join-certificate key. The
   registry **MUST** verify that signature against `node_public_key` before
   accepting the descriptor.
3. `expires_at` **MUST** be strictly after `registered_at`. A descriptor outside
   its TTL **MUST** be treated as inactive and **MUST NOT** be returned as a live
   provider. The reference implementation tolerates ~5 minutes of skew on the
   lower bound.
4. Capability discovery **MUST NOT** override trust. A consumer that finds a
   provider by capability **MUST** still apply identity (RFC-001), recognition
   (RFC-002), and revocation (RFC-004) checks before using it.
5. Revocation **MUST** evict capability: when a `node_public_key` is revoked via
   the CRL, its registry entries **MUST** be removed or treated as inactive.
6. When trust changes after discovery, the consumer **MUST** re-evaluate: a
   descriptor that was valid at discovery time confers nothing if the provider's
   trust has since been withdrawn.

## Data model

The reference implementation defines `AgentDescriptor` and `AgentEndpoint` in
`genesis_mesh/models/discovery.py`:

```json
{
  "agent_id": "llm-1",
  "node_public_key": "<base64 ed25519 public key>",
  "network_name": "USG",
  "capabilities": ["llm:chat", "kb:security"],
  "endpoint": {"host": "10.0.0.4", "port": 8443, "scheme": "wss"},
  "registered_at": "<iso8601>",
  "expires_at": "<iso8601>",
  "metadata": {"model": "example-model"},
  "signatures": [{"key_id": "...", "signature": "..."}]
}
```

The registry is intentionally simple: TTL-based expiry, at most one descriptor
per `node_public_key`, and automatic eviction on node-key revocation. A
service-level manifest (`ServiceManifest`) describes a node's offered services in
certificate material; capability descriptors are the discovery-time projection
of what is reachable now.

## Verification rules

1. A consumer **MUST** reject a descriptor whose signature does not verify
   against its `node_public_key`.
2. A consumer **MUST** check `is_active` (TTL) before treating a descriptor as a
   live provider.
3. Capability matching is by tag membership in `capabilities`. Tag semantics
   (namespacing such as `llm:chat`) are a convention; this RFC does not mandate a
   taxonomy.
4. A consumer **SHOULD** filter discovery results down to trusted providers
   before ranking or selecting among them, not after.

## Security considerations

- Descriptors are self-asserted capability claims. They prove *who is
  announcing* (via signature) and *what they claim to offer*, not that the
  provider performs the capability correctly or safely.
- TTL bounds the blast radius of a stale or compromised announcement; short TTLs
  reduce the window in which a revoked provider still appears discoverable.
- Because discovery is trust-subordinate, a malicious announcement cannot, by
  itself, cause a consumer to trust an untrusted provider.
- `metadata` is free-form and non-normative; consumers **MUST NOT** make trust
  decisions from it.

## Operational considerations

- Providers refresh descriptors before TTL expiry to stay discoverable; lapse is
  the normal "offline" signal.
- Operators revoke a compromised node once; both routing and capability
  discovery stop honoring it because the CRL eviction cascades to the registry.

## Compatibility notes

- Additional optional descriptor fields **MAY** be added; consumers **MUST**
  ignore unknown fields.
- A capability taxonomy, if standardized later, will be a separate RFC; this RFC
  fixes only the descriptor envelope and trust-subordination rule.

## Open questions

- Should capabilities be scope-bound to treaties (RFC-002), so an issuer can
  recognize a subject *for specific capabilities only*?
- Should the registry support more than one descriptor per node, or is the
  one-role-per-node constraint a long-term simplification?
