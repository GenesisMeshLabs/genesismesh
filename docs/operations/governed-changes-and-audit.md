# Governed Changes and Audit

How a Network Authority records every change to the resources it governs,
judges changes made outside the controlled path, settles them, authorises
changes in advance for devices that cannot reach it, and hands a security
team an audit it verifies on its own, years later.

```{toctree}
:maxdepth: 1
:hidden:

evidence-anchors
out-of-band-changes
remediation-and-reviews
emergency-changes
grants
edge-agent
audit-and-retention
audit-packs
audit-verification
key-succession
independent-verification
```

## Recording and judging changes

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} Evidence Anchors
:link: evidence-anchors
:link-type: doc

Signed store anchors, and how an auditor keeps copies that prove nothing was
removed from the evidence store.
:::

:::{grid-item-card} Changes Outside the Controlled Path
:link: out-of-band-changes
:link-type: doc

Observers, break-glass, judgements and quarantine: how changes made outside
governed actions are recorded and judged.
:::

:::{grid-item-card} Remediation and Reviews
:link: remediation-and-reviews
:link-type: doc

What a judged DENY leads to: remediation guidance, due times, the cancel
pair, reviews by a second holder, waivers and notices.
:::

:::{grid-item-card} Emergency Changes and Break-Glass
:link: emergency-changes
:link-type: doc

Urgent changes under an ordinary DENY, or while the NA does not answer: the
emergency capability and break-glass.
:::

:::{grid-item-card} Pre-Issued Grants
:link: grants
:link-type: doc

Changes authorised in advance for a device that cannot reach the NA: when to
use a grant instead of break-glass, its envelope, time tokens, revocation and
the limits of offline trust (v1.6.0).
:::

:::{grid-item-card} The Edge Agent
:link: edge-agent
:link-type: doc

One device that changes what it holds while often offline: edge invites,
decisions, grants and break-glass on the device, revocation and the console
(v1.7.0, beta).
:::

::::

## Audit

::::{grid} 1 1 2 2
:gutter: 3

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

:::{grid-item-card} Independent Verification
:link: independent-verification
:link-type: doc

`genesis-mesh-verify`, a second verifier in separate code: what it checks,
how to rebuild it and how to read a mismatch.
:::

::::

## Keys

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} Key Succession and the Root Key
:link: key-succession
:link-type: doc

Replacing the NA key without losing old signatures, and the ceremony that
keeps the root key offline.
:::

::::
