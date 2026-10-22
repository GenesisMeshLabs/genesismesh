# Judging Changes

A governed change has a decision before it and execution evidence after it.
These pages cover the changes that happen another way: someone changes a
resource in a cloud console, or a controller acts while the Network Authority
(NA) does not answer. The NA records them, judges each one, and says what is
to be done about a judged DENY.

All of it is off by default. Out-of-band records need
`EVIDENCE_OUT_OF_BAND=on` (with `EVIDENCE_STORE=on`). Remediation, reviews
and the emergency capability also need `EVIDENCE_REMEDIATION=on`.

```{toctree}
:maxdepth: 1
:hidden:

out-of-band-changes
remediation-and-reviews
emergency-changes
```

::::{grid} 1 1 2 2
:gutter: 3

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

::::
