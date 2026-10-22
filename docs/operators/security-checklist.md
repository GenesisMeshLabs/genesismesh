# Operator Security Checklist

Use this checklist before counting an external sovereign as independently
operated. The goal is not perfect production hardening; the goal is to prove
that the operator, not Genesis Core, controls their trust domain.

## Identity And Key Ownership

- [ ] The operator chose the sovereign network name.
- [ ] The operator generated their own genesis block.
- [ ] The operator generated their own Network Authority key.
- [ ] The operator generated their own operator key.
- [ ] The operator private keys are generated and held by the operator.
- [ ] The Network Authority private key is held by the operator: a key file
      only the NA user can read, or the operator's own key store
      (`NA_KEY_PROVIDER=env` or `azure-keyvault`).
- [ ] The root private key was generated offline and is kept offline, in two
      places, not on the NA host or in its backups
      ({doc}`../operations/key-succession`). It is the only key that can
      replace the NA key while keeping the sovereign's identity.
- [ ] `NA_DEPLOYMENT=managed` is set (off by default: `local`), so the NA
      refuses to start if it finds the root key near its files.
- [ ] `genesis-mesh na doctor --env-file <settings>` reports `OK`.
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
- [ ] You know `/readyz` shows the database path or PostgreSQL host to anyone
      who can reach it, and accept that or filter it at the proxy.
- [ ] `/sovereign.json` exposes the correct network name and public NA key.
- [ ] `/sovereign.json` does not expose private keys.
- [ ] `/sovereign.json` does not expose local filesystem paths.
- [ ] `/genesis` returns the signed genesis block.
- [ ] `/sovereign-revocation-feed` returns a signed feed, even if empty.

## Admin Write Access

- [ ] Operator public keys are configured on the Network Authority.
- [ ] Every operator key has a tier in `OPERATOR_KEY_TIERS_JSON`. Only the keys
      that issue and revoke are `privileged`; monitoring keys are `read`.
- [ ] Admin requests require operator signature headers.
- [ ] A missing admin signature is rejected.
- [ ] The operator can issue a membership attestation.
- [ ] The operator can revoke that same attestation.
- [ ] The operator can produce a revocation feed after revocation.

## Settings

These depend on the deployment. The opt-in ones are off by default, so a
deployment that does not set them runs without them.

- [ ] `NA_PROXY_HOPS` matches the number of reverse proxies in front of the NA
      (default `0`: reached directly).
- [ ] `NA_PUBLIC_URL` is set to the address other sovereigns use (unset by
      default: the NA then advertises the host each request names).
- [ ] `NA_RETENTION_REQUIRE_ARCHIVE` is on (the default).
- [ ] Opt-in, decided and recorded: `EVIDENCE_STORE=on` for hash-chained,
      anchored evidence; `BOUNDARY_POLICY_ENFORCEMENT=required`;
      `NA_DEPLOYMENT=managed`. All are off by default.
- [ ] With the evidence store on, anchors are fetched to a machine the NA's
      host cannot write to (`genesis-mesh evidence anchors fetch`).
- [ ] On SQLite, rate limits count per worker process; use PostgreSQL with
      `RATE_LIMIT_STORE=database` for shared limits.

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

Before counting a sovereign as external adoption evidence, confirm:

- [ ] The operator has a reason to run a sovereign beyond helping Genesis Core.
- [ ] The operator would be willing to keep it running after the proof.
- [ ] The operator can explain why they are running it without coaching.
- [ ] The operator is willing to be named publicly, or the reason for
      anonymity is documented.
- [ ] Assistance from Genesis Core is recorded in the proof bundle.
