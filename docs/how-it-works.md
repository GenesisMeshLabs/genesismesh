# How It Works in Five Minutes

Five ideas, in the order you meet them. Each comes with one command you can run
after `pip install genesis-mesh`. For the full picture, see the
[concept map](https://www.genesismesh.org/concepts) and the
[Concepts](concepts/introduction.md) section.

## 1. A sovereign owns its trust

A sovereign is an operator that holds its own root key, signs its own genesis
block and decides its own policy. Nobody else can admit nodes to it or revoke
them.

```bash
genesis-mesh init
```

## 2. The Network Authority runs it

The Network Authority (NA) is the sovereign's online control plane: it issues
invite tokens, signs join certificates, publishes policy and a signed
revocation list, and serves the sovereign's public trust material.

```bash
genesis-mesh na start
```

## 3. Attestations say who belongs

An attestation is a signed statement from a sovereign about one of its members
or their roles. Anyone with the sovereign's public keys (its key history, from
`/na/key-history`) can verify it offline, without asking the sovereign. Its public trust material, keys included, is
one command away:

```bash
genesis-mesh sovereign inspect --na https://na.genesismesh.org
```

## 4. Treaties let sovereigns recognize each other

A recognition treaty is a signed, scoped and expiring agreement in which one
sovereign accepts another's members for named roles. There is no shared root:
each side signs only for itself, and either can end the treaty.

```bash
genesis-mesh treaty list --na https://na.genesismesh.org
```

## 5. Revocation travels as signed evidence

When a sovereign revokes a member, key or treaty, it publishes a signed
revocation feed. A recognizing sovereign's operator imports the feed
(`genesis-mesh treaty import-feed`), and the revocation then applies there too.
With the evidence store on (`EVIDENCE_STORE=on`; it is off by default), each
decision is also recorded as evidence that can be verified later.

```bash
curl https://na.genesismesh.org/sovereign-revocation-feed
```

## Next

- See all five working together, without installing anything, at
  [mesh.genesismesh.org](https://mesh.genesismesh.org).
- Run your own sovereign with the [Quick Start](quickstart.md).
- Work through the [tutorials](tutorials.md) in order.
