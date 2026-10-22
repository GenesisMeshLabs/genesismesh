# Offline Changes

Some devices must change what they hold while they cannot reach the Network
Authority (NA). A pre-issued grant authorises such changes in advance, within
an envelope the NA checked when it signed the grant. The edge agent runs on
one such device and asks the NA when it can, uses its grants when it cannot,
and uploads what it did later.

Both are off by default. Grants need `EVIDENCE_GRANTS=on`, which needs
`EVIDENCE_OUT_OF_BAND=on` and `EVIDENCE_STORE=on`. Edge nodes need
`EVIDENCE_STORE=on` and `EVIDENCE_OUT_OF_BAND=on`.

```{toctree}
:maxdepth: 1
:hidden:

grants
edge-agent
edge-agent-walkthrough
```

::::{grid} 1 1 2 2
:gutter: 3

:::{grid-item-card} Pre-Issued Grants
:link: grants
:link-type: doc

Changes authorised in advance for a device that cannot reach the NA: when to
use a grant instead of break-glass, its envelope, time tokens, revocation and
the limits of offline trust (v1.6.0, beta routes).
:::

:::{grid-item-card} The Edge Agent
:link: edge-agent
:link-type: doc

One device that changes what it holds while often offline: edge invites,
decisions, grants and break-glass on the device, revocation and the console
(v1.7.0, beta).
:::

:::{grid-item-card} Walkthrough: Enrolling an Edge Device
:link: edge-agent-walkthrough
:link-type: doc

A recorded run: a bound invite, enrolment, a decision by the NA,
break-glass while the NA is down, and the upload when it returns.
:::

::::
