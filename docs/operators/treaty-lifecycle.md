# Treaty Lifecycle

Recognition treaties are direct, signed trust decisions from one sovereign to
another. Lifecycle management does not change what a treaty means. It makes the
current and historical state easier for operators to understand: active,
expiring, expired, revoked, or replaced.

## See It Run

```{image} ../examples/assets/images/genesis-mesh-treaty-lifecycle-management.gif
:alt: A recorded run of treaty list, inspect, renew, replace and revoke against a local Network Authority
:class: screenshot
```

Recorded from the example scripts; the steps and output are in {doc}`../examples/treaty-lifecycle-management`.

## Lifecycle States

| State | Meaning |
|---|---|
| `active` | Persisted as active and more than 72 hours from `expires_at` (`expiry_risk` `low`). |
| `expiring_soon` | Persisted as active and expiring within 72 hours (`expiry_risk` `high` within 24 hours, `medium` within 72). |
| `expired` | Persisted as active but past `expires_at`; it no longer contributes active Connectome trust. |
| `revoked` | Explicitly revoked without a successor treaty. |
| `replaced` | Revoked because a successor treaty was issued through renew or replace. |

The public treaty JSON keeps precise ISO timestamps. Human operator pages such
as the Connectome render those same dates compactly as UTC timestamps.

## List Treaties

```bash
genesis-mesh treaty list \
  --na https://na.example.org
```

The list output shows the treaty ID, issuer and subject sovereigns, persisted
status, derived lifecycle state, expiry risk, scope roles, and revocation
context when present.

## Inspect One Treaty

```bash
genesis-mesh treaty inspect \
  --na https://na.example.org \
  <treaty-id>
```

Use inspect when you need the full role/status/claim scope and operator
metadata for a single relationship.

Only `allowed_roles` and `accepted_statuses` restrict which attestations a
treaty accepts. Claims (`--claim key=value`) are informational labels signed
into the treaty, such as the proof that motivated it; they are not matched
against attestations.

## Renew A Treaty

Renew issues a successor treaty using the existing treaty scope and public keys,
then revokes the old treaty with a `renewed_by:<new-id>` reason.
`--validity-hours` defaults to 24, for `renew` and `replace` alike: a treaty
renewed with the default shows as `expiring_soon` at once, so always pass the
window you want.

```bash
genesis-mesh treaty renew \
  --na https://na.example.org \
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
  --na https://na.example.org \
  <treaty-id> \
  --operator-key .genesis-mesh/keys/operator.key \
  --operator-key-id operator-local \
  --role service:observer \
  --claim reason=scope-tightening \
  --yes
```

Use replace when the relationship continues but the accepted roles, statuses,
or informational claims need to change.

## Revoke A Treaty

```bash
genesis-mesh treaty revoke \
  --na https://na.example.org \
  <treaty-id> \
  --operator-key .genesis-mesh/keys/operator.key \
  --operator-key-id operator-local \
  --reason relationship_ended \
  --yes
```

After revocation, treaty-backed verification fails with the existing local
revocation semantics, and the Connectome no longer counts the edge as active.
It also stops agreements with that sovereign from counting: boundary
decisions under them are refused (`agreement_untrusted`). With
`EVIDENCE_GRANTS=on` (off by default), the NA also revokes the grants that
rest on such agreements.

## When The Other Sovereign Succeeds Its NA Key

A treaty names the subject's NA public keys (`subject_public_keys`), and
attestations and imported revocation feeds verify only against those keys.
When the subject succeeds its NA key ({doc}`../operations/key-succession`),
it signs new attestations and its revocation feed with the new key. Your
treaty does not name that key, so they are rejected as `invalid_signature`.

1. Read the subject's key history (`GET /na/key-history`) and check it from
   the root key you hold for that sovereign. `signing_key` in its
   `/sovereign.json` names the key that signs now.
2. Issue a new treaty that names the new key, or both keys through the
   hand-over, with `POST /admin/recognition-treaties`.
3. Revoke the old treaty.

`treaty renew` and `treaty replace` copy the old treaty's keys, and
`federation bootstrap` takes the genesis key from `/sovereign.json`
(`network_authority.public_key`). None of them picks up a successor key.
