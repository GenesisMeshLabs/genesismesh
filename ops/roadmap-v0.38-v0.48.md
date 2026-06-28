# Roadmap: v0.38.0 -- v0.48.0
## Third Trust Cycle: Adversarial Hardening, Privacy, and the Data Plane

_Triage and analysis document for the next release cycle._

---

## 1. Context

v0.37.0 closed the second complete GenesisMesh trust cycle (Phase I, v0.32-v0.37).
The six capabilities shipped make authorization richer, more expressive, and more
auditable.  They also introduce new attack surfaces that the 2026 research
literature has explicitly identified.

This roadmap addresses those attack surfaces, adds missing infrastructure layers,
and extends the formal verification foundation.

---

## 2. Threat Analysis

### 2.1 Immediate threats (attack surfaces opened by Phase I)

**Persuasion cascade via ConsensusProof (v0.36 vulnerability)**
arXiv:2603.15809 proves that K-of-N voting systems are vulnerable to cascade:
if validators share context before voting, the K threshold is met but independence
is lost.  Risk: a single adversary can unilaterally satisfy a 3-of-5 threshold
by seeding a common narrative to all validators.
_Addressed by: v0.38.0 (Cascade-Resilient Consensus)_

**Adversarial credit farming via PeerRiskSignal (v0.37 vulnerability)**
An adversary that behaves perfectly for 30 days then fails suddenly will trigger
anomaly detection.  But a sophisticated adversary who introduces small, scheduled
degradations can keep the EWMA high while gradually shifting the mean, preventing
anomaly fire while still building toward a coordinated attack.
_Addressed by: v0.39.0 (Adversarial Seed Isolation)_

### 2.2 Persistent gaps (not addressed in Phase I)

**Hidden instruction exploit (IBCTs blind spot)**
IBCTs (v0.32) attest WHAT but not HOW an agent reasons.  A valid IBCT can be
executed with a jailbroken model, manipulated system prompt, or undeclared tools.
arXiv:2604.02767 (SentinelAgent) identifies intent verification as a required
delegation chain property.
_Addressed by: v0.40.0 (Verifiable Logic Attestation)_

**Prompt injection at runtime**
Even with LogicAttestation, tool outputs and retrieved documents can inject
adversarial instructions.  arXiv:2605.04093 identifies this as the "container
fallacy."  The system prompt hash is valid; the actual execution context is
contaminated.  The correct security invariant is `final_context = committed_base
+ declared_typed_append_segments` -- not context immutability, which would block
legitimate tool use.
_Addressed by: v0.41.0 (Context-Injection Defense Gate)_

**Ephemeral identity audit bloat**
EphemeralExecutionIdentity (v0.36) records accumulate indefinitely.  arXiv:2605.04093
specifically mandates minimum retention periods followed by verifiable deletion.
_Addressed by: v0.42.0 (Ephemeral Identity Purge Protocol)_

**Stylometric deanonymization**
arXiv:2602.23079 (SALA) and the ICLR 2026 Workshop paper demonstrate that LLM-
powered authorship attribution is now routine.  Message length, timing, and
structural patterns expose agent and operator identity even on encrypted transports.
_Addressed by: v0.43.0 (Communication Privacy Layer)_

### 2.3 Infrastructure gaps (scale and sovereignty)

**DNS dependency**
Current discovery requires DNS or pre-configured endpoints.  ISP-level blocking,
redirection, or simply deploying in a mesh-hostile network environment makes DNS
unreliable for sovereign discovery.
_Addressed by: v0.44.0 (Sovereign Overlay Discovery)_

**Application-layer enforcement bypass**
arXiv:2604.23425 documents April 2026 sandbox escapes where agents used authorized
tool access to gain OS-level persistence.  BoundaryEngine enforcement at the
application layer can be bypassed if the agent controls its own process.
GenesisGuard is a hard enforcement layer only when deployed in mandatory mediation
mode; advisory mode produces receipts but does not prevent bypass.
_Addressed by: v0.45.0 (Process-Level Execution Mediation)_

**Trust Atlas staleness and scale**
Expired treaties and revoked certificates remain in the active graph indefinitely.
At hundreds of sovereigns, path traversal becomes slow and incorrect.
_Addressed by: v0.46.0 (Trust Path Performance and Atlas Pruning)_

**Data usage not tracked**
arXiv:2606.12320 defines the Data Plane as a distinct enforcement layer.  GM has
no mechanism to track which data sources were accessed during execution, under
what terms, or with what volume.  This is the missing infrastructure for any
responsible AI data stewardship claim.
_Addressed by: v0.47.0 (Data Usage Attestation)_

**PeerRiskSignal formally unverified**
EWMA + anomaly detection has been empirically tested but not formally verified.
Two attack questions are open: can the anomaly threshold be permanently suppressed?
Can a single adversary cascade across independent sovereigns?
_Addressed by: v0.48.0 (Formal PeerRiskSignal Verification)_

---

## 3. What Was Assessed and Excluded

### OS-Kernel Level Mediation
Recommended as "must fix" in the threat analysis.  Implementing kernel modules,
eBPF hooks, or hardware attestation (TPM-based) is outside the scope of a Python
library.  v0.45.0 (GenesisGuard) implements the realistic equivalent: a
deterministic, non-LLM sidecar that enforces mediation *below* the agent but
*above* the kernel.  This closes the immediate bypass gap without requiring kernel
access.  A future hardware attestation integration plan is warranted if GM adopts
native binary distribution.

### Full Stylometric Rewriting (SALA Content Defense)
The SALA attack operates on both metadata and content.  v0.43.0 covers the
metadata attack vectors (length, timing, headers).  Full content-level stylometric
rewriting requires an LLM-in-the-loop to paraphrase agent outputs before forwarding.
This is architecturally complex and would make GM semantically lossy.  Excluded
from this cycle.  Recommended approach: expose a `StyleNormalizationHook` interface
in v0.43.0 that external LLM normalization services can implement without GM
needing to embed a model.

### Data Dignity Settlement / Payment Rails
The settlement layer requires integration with payment infrastructure (smart
contracts, payment channels, or traditional billing APIs).  v0.47.0 provides the
attestation and audit infrastructure (signed DataAccessRecords) that settlement
systems can verify.  The settlement itself is external.

### Multi-Agent Workflow Economics / Inverse Subscription
Requires payment rails (above) plus marketplace infrastructure (governance, pricing,
discovery of services at value).  This is a multi-release initiative beyond the
current cycle.  The prerequisite is v0.47.0 (data attestation) + a future
marketplace plan.

---

## 4. Priority Order and Rationale

| Version | Plan | Priority | Rationale |
|---------|------|----------|-----------|
| v0.38.0 | Cascade-Resilient Consensus | P1 | Closes active vulnerability in v0.36 |
| v0.39.0 | Adversarial Seed Isolation | P1 | Closes active vulnerability in v0.37 |
| v0.40.0 | Verifiable Logic Attestation | P1 | Closes IBCTs blind spot (hidden instruction) |
| v0.41.0 | Context-Injection Defense | P2 | Closes runtime injection gap |
| v0.42.0 | Ephemeral Identity Purge | P2 | Closes audit bloat + residual correlation |
| v0.43.0 | Communication Privacy | P2 | Closes stylometric metadata fingerprinting |
| v0.44.0 | Sovereign Overlay Discovery | P3 | DNS independence + scale |
| v0.45.0 | Process-Level Mediation | P3 | Below-agent enforcement |
| v0.46.0 | Trust Path Performance | P3 | Atlas scale + pruning |
| v0.47.0 | Data Usage Attestation | P3 | Data Plane foundation |
| v0.48.0 | Formal PeerRiskSignal Verification | P4 | Academic rigor; no immediate attack |

**P1** = Closes an active attack surface on features already shipped.
**P2** = Closes a known gap identified by 2026 research.
**P3** = New infrastructure capability.
**P4** = Formal verification and academic rigor.

---

## 5. Research Reference Summary

| Paper | Plans it informs |
|-------|-----------------|
| arXiv:2603.15809 -- Don't Trust Stubborn Neighbors | v0.38, v0.39, v0.48 |
| arXiv:2604.02767 -- SentinelAgent | v0.40, v0.41, v0.42, v0.48 |
| arXiv:2605.04093 -- Decision Evidence Maturity Model | v0.41, v0.42, v0.47 |
| arXiv:2604.23425 -- Sandbox Escape (Mitchell) | v0.45 |
| arXiv:2605.14932 -- Securing AI Agents Like OSes (Pirch) | v0.45 |
| arXiv:2602.23079 -- SALA (Zhang) | v0.43 |
| Lermen (2026), ICLR Workshop | v0.43 |
| arXiv:2606.12320 -- Five-Plane Architecture (Tallam) | v0.40, v0.45, v0.47 |
| arXiv:2605.05440 -- Authorization Propagation (Tallam) | v0.38, v0.39, v0.44, v0.46 |
