# Phase I -- Runtime Trust Layer

**Versions**: v0.32.0 – v0.37.0
**Question**: How do you make those governed relationships usable by autonomous agents at runtime — fast, portable, and with human override authority for high-stakes actions?

## What Changed

**Invocation-Bound Capability Tokens** (v0.32): An `InvocationToken`
fuses sovereign identity, an attenuated capability scope (always a subset
of the source agreement), an optional invocation budget, and policy
constraints into a single Ed25519-signed JSON record. Any verifier
holding the issuer's public key validates it offline. Each invocation
produces a signed `InvocationUseRecord` linked by `prev_use_digest`,
forming a tamper-evident use ledger. Verification latency: 0.189 ms.

**Justification proofs** (v0.33): A `JustificationProof` wraps the
ordered `GateTrace` from a `BoundaryEngine` run — each gate's name, type,
inputs, and pass/fail result, with a short-circuit pointer. Signed by the
issuer; verifiable by any auditor without re-running the engine.

**Human oversight + dual-signed commitments** (v0.34): A
`HumanOversightPolicy` runs eight deterministic checks (capability scope,
counterparty allowlist, value threshold, time window, frequency limit,
irreversibility, novel counterparty, anomaly flag) and produces one of
three outcomes: `automatic`, `human_approve`, or `block`. High-stakes
actions produce a `HumanApprovalRequest` that the human custodian
must countersign; the result is a `DualSignedCommitment` requiring both
keys. Neither party can forge it alone.

**Selective disclosure** (v0.35): A `CapabilityCommitment` is a signed
Merkle root over a sorted capability set. A `CapabilityMembershipProof`
carries only the leaf hash and O(log N) sibling hashes — nothing about
other capabilities. A `CapabilityNullifier` prevents replay.

**Distributed consensus authorization** (v0.36): A `ConsensusProof`
assembles K-of-N signed `ValidatorVote`s over the same
`JustificationProof`. Votes from sovereigns outside the named validator
set are excluded. An approved proof issues an `EphemeralExecutionIdentity`
that expires in ~120 s and cannot be transferred.

**Peer risk signals** (v0.37): A `PeerRiskSignal` starts at 0.5 and
moves via EWMA (α=0.2) with successful and failed outcomes. Between
updates it decays as `signal × exp(-λ × elapsed_days)` (λ=0.05). A
`RiskAnomaly` is raised when a new delta falls more than 3σ outside the
variance of the last 10 updates. Strictly local: no shared ledger, no
federation-wide score, no cross-sovereign comparison.

## Value Added

- An agent can carry a signed bearer token to an offline verifier
  without any network call to the GM stack.
- Every authorization decision has a signed gate trace; auditors can
  verify how the decision was made, not just what it was.
- High-stakes actions require both the agent key and a human custodian
  key — the agent cannot execute them alone.
- An agent can prove one capability to a third party without revealing
  the full capability set.
- Consequential authorizations can require K-of-N named validators,
  not a single operator.
- Each sovereign independently tracks counterparty reliability through
  a time-decaying signal updated from execution history.
- Every component is opt-in; the normal authorization path is unmodified.

## What Became Possible

With a complete runtime trust layer, Phase J hardened the pipeline against
adversarial behavior: correlated validators, patient credit-farming,
hidden model instructions, context injection, communication fingerprinting,
and DNS-free discovery.

## Key Releases

| Version | Milestone |
|---------|-----------|
| v0.32.0 | Invocation-Bound Capability Tokens (IBCTs): offline bearer token, use ledger |
| v0.33.0 | Justification Proofs: signed GateTrace artifact, evaluate_with_proof() |
| v0.34.0 | Human Oversight + DualSignedCommitment: 8-check policy, countersign flow |
| v0.35.0 | Selective Disclosure: Merkle capability proof, CapabilityNullifier |
| v0.36.0 | Distributed Consensus Authorization: K-of-N, EphemeralExecutionIdentity |
| v0.37.0 | Peer Risk Signals: EWMA, decay, anomaly detection, RiskSignalGate |
