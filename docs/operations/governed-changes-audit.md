# Audit Evidence

The evidence store is one hash chain of signed records. These pages cover
how its history is protected (anchors), how long it is kept and archived,
how a period of it is packed for an audit, and how an auditor verifies a pack
from keys and anchors the auditor holds.

All of it needs the evidence store (`EVIDENCE_STORE=on`), which is off by
default.

```{toctree}
:maxdepth: 1
:hidden:

evidence-anchors
audit-and-retention
audit-packs
audit-verification
independent-verification
audit-verification-walkthrough
```

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} Evidence Anchors
:link: evidence-anchors
:link-type: doc

Signed store anchors, and how an auditor keeps copies that show whether
anything was removed from the evidence store.
:::

:::{grid-item-card} Audit and Retention
:link: audit-and-retention
:link-type: doc

What is kept, for how long, and why nothing is pruned before it is archived
to immutable storage and read back.
:::

:::{grid-item-card} Audit Packs
:link: audit-packs
:link-type: doc

One period of the evidence store, with everything its records cite, a
report for auditors and a manifest the NA signs.
:::

:::{grid-item-card} Verifying a Pack
:link: audit-verification
:link-type: doc

`genesis-mesh audit verify`: from the root key and the anchors you hold, and
the completeness check against a log kept outside Genesis Mesh.
:::

:::{grid-item-card} The Rust Verifier
:link: independent-verification
:link-type: doc

`genesis-mesh-verify`, a Rust port of the reference verifier: what it
checks, what a second verifier does and does not catch, and how to rebuild
it.
:::

:::{grid-item-card} Walkthrough: Verifying an Audit Pack
:link: audit-verification-walkthrough
:link-type: doc

A recorded run: write a pack, verify it with both verifiers, and see a
missing change and a changed file fail.
:::

::::
