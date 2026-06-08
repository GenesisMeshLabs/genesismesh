# Genesis Mesh Atlas

**Status:** Phase 2 product concept  
**Purpose:** public explorer for sovereigns, operators, trust material, and recognition relationships.

## Positioning

Atlas is the public answer to:

> Who is using Genesis Mesh?

It should not be framed as a demo. It should be framed as the ecosystem explorer.

The Connectome shows trust state for a Network Authority. Atlas should aggregate
publicly published trust material into a broader ecosystem view without becoming
the authority over the network.

## Core rule

Atlas observes and explains. It does not grant trust.

Trust remains with sovereigns, signed treaties, operator keys, revocation feeds,
and local verification rules.

## Initial surfaces

Atlas should show:

- sovereigns;
- Network Authorities;
- founding community operators;
- managing partners;
- public endpoints;
- sovereign metadata;
- recognition treaties;
- trust paths;
- revocation-feed freshness;
- capability manifests;
- operator continuity status;
- public proof artifact links.

## First question Atlas must answer

> Which sovereigns exist and who recognizes whom?

Minimum useful view:

- list of sovereigns;
- list of active recognition edges;
- date of last observed trust material;
- whether the source material was fetched live or loaded from a published proof
  artifact;
- links to raw JSON material.

## Second question Atlas must answer

> Which operators are independent from Genesis Core?

Atlas should distinguish:

- Genesis Core maintainers;
- non-maintainer operators;
- managing partners;
- hosted authorities;
- offline or historical operators.

This distinction is critical because adoption proof depends on more than
technical reachability.

## Third question Atlas must answer

> What changed recently?

Atlas should eventually expose an activity feed:

- new sovereign published;
- treaty issued;
- treaty renewed;
- treaty revoked;
- revocation feed updated;
- capability manifest changed;
- operator marked offline or restored.

## Data source discipline

Atlas should prefer public signed material over private runtime access.

Acceptable source types:

- `/sovereign.json`;
- `/connectome.json`;
- public trust bundles;
- public revocation feeds;
- public capability manifests;
- repository proof artifacts;
- operator-declared metadata.

Atlas must label each source as live, archived, stale, or unavailable.

## Non-goals

Atlas should not become:

- a central trust registry;
- a permissionless ranking system;
- a reputation market;
- a billing marketplace;
- a governance authority;
- a replacement for local sovereign verification.

## Minimal Phase 2 acceptance

Atlas reaches useful Phase 2 proof when it can:

1. ingest the founding community operator artifacts;
2. fetch at least one live hosted sovereign;
3. display sovereigns and recognition edges;
4. show raw source links;
5. label stale or unavailable material honestly;
6. explain that Atlas is observational, not authoritative.
