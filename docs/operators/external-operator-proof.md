# External Operator Proof

This guide explains how an independent operator can run a Genesis Mesh
sovereign and produce adoption evidence without handing control to Genesis
Core.

The goal is not a sales call, a customer onboarding, or a production migration.
The goal is a short, honest proof that two independently operated sovereigns
can form, inspect, and revoke trust while each side keeps control of its own
keys, policy, database, and infrastructure.

## One-Line Summary

Genesis Mesh lets independently operated trust domains recognize each other,
prove scoped trust, and revoke that trust without centralizing control.

## What the Operator Does

The external operator runs a temporary or persistent Genesis Mesh Network
Authority and completes a guided proof with a recognizing sovereign.

The operator should be willing to:

- choose their own network name;
- generate their own genesis block;
- generate and keep their own Network Authority private key;
- generate and keep their own operator private key;
- run their own database and endpoint, even if temporary;
- expose public trust material for review;
- issue a scoped attestation relevant to their project;
- revoke that attestation;
- publish a revocation feed;
- allow the recognizing sovereign to import the feed and verify rejection;
- record which parts were easy, confusing, or too manual.

They do not need to become a customer. They do not need to deploy production
infrastructure. They do not need to make a long-term commitment.

They do need to control their own keys and infrastructure for the proof to
mean anything.

Expected commitment size:

- first fit call: 15 minutes;
- setup preparation: 30-45 minutes if a reachable VM, host, or lab machine
  already exists;
- guided proof session: 60-90 minutes;
- evidence review and public-permission decision: 15-30 minutes.

## Good-Fit Operators

Strong fit:

- maintainers of agent runtimes or agent security tools;
- MCP/tooling projects exposing tools to AI systems;
- supply-chain security projects;
- self-hosted AI operators;
- zero-trust or infrastructure security teams;
- homelab or platform operators who care about portable trust;
- projects that already think about capabilities, policies, release authority,
  revocation, or delegated trust.

Weak fit:

- someone who only wants to watch a demo;
- someone who cannot run an endpoint;
- someone who cannot generate and control their own keys;
- someone with no real reason to care about trust, revocation, agents, tools,
  supply chain, or infrastructure boundaries;
- a friendly helper running the commands only as a favor.

A friendly proof can still teach the project something, but it is not strong
external adoption evidence.

## Control Boundary

Genesis Core or another recognizing sovereign can provide:

- the recognizing sovereign endpoint;
- a short setup call;
- a command checklist;
- help reading errors;
- a guided proof session;
- review of public trust material;
- signed recognition for the proof scope;
- redacted evidence capture;
- a short public case note if the operator agrees.

The recognizing side should not provide or control:

- the operator's private keys;
- the operator's database;
- the operator's cloud account or VM;
- the operator's policy decisions;
- the operator's revocation decision;
- claims about the operator that they did not approve.

If the operator has to hand over private keys for the proof to work, the proof
is not good enough.

## What Not To Share

Do not share:

- Network Authority private key;
- operator private key;
- root private key;
- database file;
- bearer tokens;
- invite tokens;
- unredacted shell history;
- cloud credentials;
- personal contact details not intended for publication.

Safe to share:

- `/healthz` output;
- `/readyz` output;
- `/genesis` output;
- `/sovereign.json` output;
- `/sovereign-revocation-feed` output;
- `/connectome.json` output;
- redacted proof bundle;
- public key fingerprints;
- approved screenshots.

## Step 1: Public Material Review

Before trust is issued, review public material only.

Expected public surfaces:

```bash
curl -fsS https://issuer.example.org/healthz
curl -fsS https://issuer.example.org/readyz
curl -fsS https://issuer.example.org/genesis | python3 -m json.tool
curl -fsS https://issuer.example.org/sovereign.json | python3 -m json.tool
curl -fsS https://issuer.example.org/sovereign-revocation-feed | python3 -m json.tool
curl -fsS https://issuer.example.org/connectome.json | python3 -m json.tool
```

Check that:

- the service is alive;
- the service is ready;
- the genesis material is present;
- the public sovereign metadata matches the genesis identity;
- the public Network Authority key is visible;
- no private keys or local paths appear in public metadata;
- the revocation feed exists, even if empty;
- the Connectome is visible or clearly empty.

## Step 2: Review Before Recognition

Run the review-only bootstrap path first:

```bash
genesis-mesh federation bootstrap \
  --acceptor https://acceptor.example.org \
  --issuer https://issuer.example.org \
  --dry-run
```

This should help both sides answer:

- Who is the issuer sovereign?
- Is the public metadata consistent?
- What public key identifies the Network Authority?
- Is recognition policy visible?
- Is Connectome available?
- What would be recognized if a treaty is issued?

No treaty should be issued in this step.

## Step 3: Explicit Recognition Decision

If both sides agree to proceed, issue a narrow direct-recognition treaty.

Example:

```bash
genesis-mesh federation bootstrap \
  --acceptor https://acceptor.example.org \
  --issuer https://issuer.example.org \
  --operator-key ./keys/operator.key \
  --operator-key-id operator-local \
  --role service:maintainer \
  --claim proof=external-operator-adoption \
  --validity-hours 24 \
  --evidence ./federation-bootstrap-evidence.json \
  --yes
```

Before confirming, check:

- issuer endpoint is the operator-owned endpoint;
- issuer sovereign ID is the expected one;
- public key fingerprint matches what the operator expects;
- role and claim are narrow;
- validity window is intentionally short;
- the treaty is direct recognition only;
- both sides understand that the operator can revoke their own material.

## Step 4: Revocation Proof

Run the remote proof with explicit operator-control metadata:

```bash
genesis-mesh proof remote \
  --acceptor https://acceptor.example.org \
  --issuer https://issuer.example.org \
  --acceptor-config ./acceptor.toml \
  --issuer-config ./issuer.toml \
  --role role:service:maintainer \
  --claim proof=external-operator-adoption \
  --proof-bundle ./external-operator-proof.json \
  --adoption-proof \
  --acceptor-operator-label "Recognizing Sovereign" \
  --acceptor-operator-type maintainer \
  --issuer-operator-label "OPERATOR_OR_PROJECT_NAME" \
  --issuer-operator-type external \
  --issuer-controls-keys \
  --issuer-controls-infrastructure \
  --operator-assistance-note "The recognizing operator observed and supported debugging, but did not handle issuer private keys."
```

The proof should show:

1. The recognizing sovereign fetched the operator's public genesis material.
2. The operator sovereign issued an attestation.
3. The recognizing sovereign recognized the operator sovereign through a signed
   treaty.
4. The attestation was accepted before revocation.
5. The operator revoked the attestation.
6. The recognizing sovereign imported the operator's revocation feed.
7. The same attestation was rejected after revocation.
8. A redacted proof bundle was produced.

## Step 5: Evidence Review

Inspect the proof bundle:

```bash
python3 -m json.tool external-operator-proof.json
```

Expected evidence:

- issuer operator type is external;
- issuer controls keys is true;
- issuer controls infrastructure is true;
- pre-revocation accepted is true;
- post-revocation accepted is false;
- rejection reason is clear;
- no private keys, tokens, database files, or local secret paths are present.

Inspect Connectome state:

```bash
curl -fsS https://acceptor.example.org/connectome.json | python3 -m json.tool
curl -fsS https://issuer.example.org/connectome.json | python3 -m json.tool
```

Record what changed before and after revocation.

## Readiness Checklist

### Fit

- [ ] Operator has a real use case.
- [ ] Use case maps to agents, MCP/tools, supply chain, self-hosted AI,
      zero-trust, or infrastructure authority.
- [ ] Operator can explain why this matters without coaching.
- [ ] Operator is not only doing this as a favor.

### Control

- [ ] Operator controls infrastructure.
- [ ] Operator controls firewall/DNS if applicable.
- [ ] Operator controls database.
- [ ] Operator controls Network Authority private key.
- [ ] Operator controls operator private key.
- [ ] Recognizing operator never receives private keys.

### Public Material

- [ ] `/healthz` works.
- [ ] `/readyz` works.
- [ ] `/genesis` works.
- [ ] `/sovereign.json` works.
- [ ] `/sovereign-revocation-feed` works.
- [ ] `/connectome.json` works or is clearly empty.
- [ ] Public metadata contains no private material.

### Recognition

- [ ] Review-only bootstrap completed.
- [ ] Treaty scope previewed.
- [ ] Operator and recognizing sovereign understood the scope.
- [ ] Treaty issued only after explicit confirmation.
- [ ] Trust path verified.

### Revocation

- [ ] Operator issued attestation.
- [ ] Recognizing sovereign accepted it before revocation.
- [ ] Operator revoked it.
- [ ] Recognizing sovereign imported revocation feed.
- [ ] Recognizing sovereign rejected the same material after revocation.

### Evidence

- [ ] Redacted proof bundle exists.
- [ ] Bootstrap evidence exists if used.
- [ ] Connectome output captured.
- [ ] Self-service versus assisted notes captured.
- [ ] Top onboarding blockers captured.
- [ ] Public naming permission recorded.

## Bug Found Mid-Proof

If the operator finds a bug during the proof, classify it before deciding
whether the proof can continue.

Patch issue:

- the operator still controls their own keys and infrastructure;
- the bug is CLI ergonomics, docs clarity, display formatting, evidence
  redaction, or non-semantic packaging;
- no treaty, attestation, revocation, or verification rule changes meaning;
- the operator can rerun the failed step after the fix without changing the
  proof claim.

Adoption-proof blocker:

- the operator must hand over private keys or credentials to continue;
- recognition or revocation semantics are wrong;
- accepted-before-revocation or rejected-after-revocation cannot be proved;
- proof-bundle evidence cannot distinguish maintainer-operated from external
  infrastructure;
- public metadata leaks private material;
- the operator cannot explain or approve what trust was granted.

When in doubt, pause and write the issue down. The recognizing operator can
decide whether to patch the software, but the external operator's security
objection is authoritative for their side of the proof.

## Self-Service Versus Assisted Log

Not all steps carry the same adoption weight. A package-install assist is
minor. A key-generation or revocation-decision assist is material because it
weakens the independence claim.

| Step | Weight | Self-service | Assisted | Notes |
|---|---|---:|---:|---|
| Install package | Low | [ ] | [ ] | |
| Initialize sovereign | Medium | [ ] | [ ] | |
| Generate Network Authority key | Critical | [ ] | [ ] | |
| Generate operator key | Critical | [ ] | [ ] | |
| Configure operator public key | Medium | [ ] | [ ] | |
| Start Network Authority | Medium | [ ] | [ ] | |
| Expose endpoint/firewall/DNS | Medium | [ ] | [ ] | |
| Verify public metadata | Medium | [ ] | [ ] | |
| Run review-only bootstrap | Medium | [ ] | [ ] | |
| Confirm treaty scope | Critical | [ ] | [ ] | |
| Issue treaty | High | [ ] | [ ] | |
| Issue attestation | High | [ ] | [ ] | |
| Revoke attestation | Critical | [ ] | [ ] | |
| Import revocation feed | Medium | [ ] | [ ] | |
| Verify post-revocation rejection | High | [ ] | [ ] | |
| Interpret proof bundle | Medium | [ ] | [ ] | |
| Interpret Connectome | Low | [ ] | [ ] | |

Interpretation:

- Critical assisted steps require a written note explaining exactly what the
  recognizing operator did and why the external operator still controlled the
  decision.
- Two or more critical assisted steps make the proof narratively weak even if
  it is technically valid.
- Low assisted steps are normal during a first proof and should become docs or
  CLI polish candidates later.

## Public Case Note Template

Use only after operator approval.

```text
Genesis Mesh external operator proof

Operator: [name/project]
Use case: [why they ran a sovereign]
Operator controlled: genesis, Network Authority key, operator key, database, endpoint, policy
Recognizing sovereign controlled: recognizing sovereign
Proof: direct-recognition treaty, pre-revocation acceptance, operator revocation, post-revocation rejection
Evidence: redacted proof bundle and Connectome output
Friction found: [top 3]
Next improvements: [top 3]
```
