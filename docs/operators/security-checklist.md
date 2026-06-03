# Operator Security Checklist

Use this checklist before counting an external sovereign as independently
operated. The goal is not perfect production hardening; the goal is to prove
that the operator, not Genesis Core, controls their trust domain.

## Identity And Key Ownership

- [ ] The operator chose the sovereign network name.
- [ ] The operator generated their own genesis block.
- [ ] The operator generated their own Network Authority key.
- [ ] The operator generated their own operator key.
- [ ] The operator private key is controlled by the external operator in future multi-cloud operation proofs.
- [ ] The Network Authority private key is controlled by the external operator in future multi-cloud operation proofs.
- [ ] The operator can rotate or remove Genesis Core assistance without
      losing control of the sovereign.

## Infrastructure Ownership

- [ ] The operator controls the VM, account, project, or tenancy that runs the
      Network Authority.
- [ ] The operator controls inbound firewall rules.
- [ ] The operator controls DNS, if a domain is used.
- [ ] The operator can restart the service without maintainer access.
- [ ] The operator knows where the database lives.
- [ ] The operator knows how to back up the database.

## Public Metadata

- [ ] `/healthz` returns `{"status":"ok"}`.
- [ ] `/readyz` returns a ready status.
- [ ] `/sovereign.json` exposes the correct network name and public NA key.
- [ ] `/sovereign.json` does not expose private keys.
- [ ] `/sovereign.json` does not expose local filesystem paths.
- [ ] `/genesis` returns the signed genesis block.
- [ ] `/sovereign-revocation-feed` returns a signed feed, even if empty.

## Admin Write Access

- [ ] Operator public keys are configured on the Network Authority.
- [ ] Admin requests require operator signature headers.
- [ ] A missing admin signature is rejected.
- [ ] The operator can issue a membership attestation.
- [ ] The operator can revoke that same attestation.
- [ ] The operator can produce a revocation feed after revocation.

## Recognition Proof

- [ ] The recognizing sovereign fetches the operator's public metadata.
- [ ] The recognizing sovereign signs a treaty for the operator's sovereign.
- [ ] The recognizing sovereign accepts the operator's attestation before
      revocation.
- [ ] The operator revokes the attestation.
- [ ] The recognizing sovereign imports the operator's signed feed.
- [ ] The recognizing sovereign rejects the same attestation after feed import.
- [ ] `/connectome.json` shows the recognition edge and imported revocation.

## What Not To Share

Do not share:

- Network Authority private key.
- Operator private key.
- Root private key.
- Raw database backups unless explicitly required for incident support.
- Shell history containing secrets.

Safe to share:

- `/sovereign.json`.
- `/genesis`.
- Network name.
- Network Authority public key.
- Revocation feed.
- Redacted proof bundle.

## External Operator Quality Gate

Before marking v0.14 complete, confirm:

- [ ] The operator has a reason to run a sovereign beyond helping Genesis Core.
- [ ] The operator would be willing to keep it running after the proof.
- [ ] The operator can explain why they are running it without coaching.
- [ ] The operator is willing to be named publicly, or the reason for
      anonymity is documented.
- [ ] Assistance from Genesis Core is recorded in the proof bundle.
