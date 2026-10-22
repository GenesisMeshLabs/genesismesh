# Governed Changes and Audit

How a Network Authority records the changes reported to it, judges changes
made outside the controlled path, settles them, authorises changes in advance
for devices that cannot reach it, and hands a security team an audit it can
verify on its own.

Each part is off by default, and each needs the one before it:

| Setting | Turns on | Needs |
| --- | --- | --- |
| `EVIDENCE_STORE=on` | the evidence store: decisions, execution evidence, anchors, audit packs, archives | — |
| `EVIDENCE_OUT_OF_BAND=on` | observations, break-glass records, judgements; edge nodes | `EVIDENCE_STORE=on` |
| `EVIDENCE_REMEDIATION=on` | remediation, reviews, the emergency capability | `EVIDENCE_OUT_OF_BAND=on` |
| `EVIDENCE_GRANTS=on` | pre-issued grants | `EVIDENCE_OUT_OF_BAND=on` |

The NA records only what is reported to it, through execution evidence or
observations. A change nobody reports is found only against a log kept
elsewhere (the completeness check in {doc}`audit-verification`).

On the client side, the outbox, observations, break-glass, the remediation
helpers and grant holders exist only in the TypeScript and Rust SDKs and in
the edge agent. The Go and .NET SDKs verify records and grants but do not
make them.

```{toctree}
:maxdepth: 2
:hidden:

governed-changes-judging
governed-changes-offline
governed-changes-audit
governed-changes-keys
```

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} Judging Changes
:link: governed-changes-judging
:link-type: doc

Changes made outside the controlled path: observers, break-glass,
judgements, remediation, reviews and the emergency capability.
:::

:::{grid-item-card} Offline Changes
:link: governed-changes-offline
:link-type: doc

Changes authorised in advance for devices that cannot reach the NA:
pre-issued grants and the edge agent.
:::

:::{grid-item-card} Audit Evidence
:link: governed-changes-audit
:link-type: doc

Anchors, retention and archives, audit packs, and verifying them with the
Python and Rust verifiers.
:::

:::{grid-item-card} Keys
:link: governed-changes-keys
:link-type: doc

Replacing the NA key by succession, and the ceremony that keeps the root key
offline.
:::

::::
