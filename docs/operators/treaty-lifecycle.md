# Treaty Lifecycle

Recognition treaties are direct, signed trust decisions from one sovereign to
another. Lifecycle management does not change what a treaty means. It makes the
current and historical state easier for operators to understand: active,
expiring, expired, revoked, or replaced.

## Lifecycle States

| State | Meaning |
|---|---|
| `active` | Persisted as active and outside the expiry warning window. |
| `expiring_soon` | Persisted as active but inside the expiry warning window. |
| `expired` | Persisted as active but past `expires_at`; it no longer contributes active Connectome trust. |
| `revoked` | Explicitly revoked without a successor treaty. |
| `replaced` | Revoked because a successor treaty was issued through renew or replace. |

The public treaty JSON keeps precise ISO timestamps. Human operator pages such
as the Connectome render those same dates compactly as UTC timestamps.

## List Treaties

```bash
genesis-mesh treaty list \
  --na https://na.genesismesh.connectorzzz.com
```

The list output shows the treaty ID, issuer and subject sovereigns, persisted
status, derived lifecycle state, expiry risk, scope roles, and revocation
context when present.

## Inspect One Treaty

```bash
genesis-mesh treaty inspect \
  --na https://na.genesismesh.connectorzzz.com \
  <treaty-id>
```

Use inspect when you need the full role/status/claim scope and operator
metadata for a single relationship.

## Renew A Treaty

Renew issues a successor treaty using the existing treaty scope and public keys,
then revokes the old treaty with a `renewed_by:<new-id>` reason.

```bash
genesis-mesh treaty renew \
  --na https://na.genesismesh.connectorzzz.com \
  <treaty-id> \
  --operator-key .genesis-mesh/keys/operator.key \
  --operator-key-id operator-local \
  --validity-hours 168 \
  --yes
```

This reuses existing treaty issue and revoke semantics. It does not mutate the
signed treaty body in place.

## Replace A Treaty

Replace issues a successor treaty with updated scope, then revokes the old
treaty with a `replaced_by:<new-id>` reason.

```bash
genesis-mesh treaty replace \
  --na https://na.genesismesh.connectorzzz.com \
  <treaty-id> \
  --operator-key .genesis-mesh/keys/operator.key \
  --operator-key-id operator-local \
  --role service:observer \
  --claim reason=scope-tightening \
  --yes
```

Use replace when the relationship continues but the accepted roles, statuses,
or local claims need to change.

## Revoke A Treaty

```bash
genesis-mesh treaty revoke \
  --na https://na.genesismesh.connectorzzz.com \
  <treaty-id> \
  --operator-key .genesis-mesh/keys/operator.key \
  --operator-key-id operator-local \
  --reason relationship_ended \
  --yes
```

After revocation, treaty-backed verification fails with the existing local
revocation semantics, and the Connectome no longer counts the edge as active.
