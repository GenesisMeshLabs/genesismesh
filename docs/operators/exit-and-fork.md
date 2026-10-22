# Operator Exit and Fork

An operator can leave a federation, leave a managing partner, or fork the
software without Genesis Core's approval. This page says what an operator
owns, how each kind of exit works, and where the limits are.

## What an operator owns

| Asset | Where it lives | Who can use it |
| --- | --- | --- |
| Root key (anchors the sovereign's genesis) | Operator's custody | Operator only |
| Network Authority signing key | Operator's key provider (file, environment, or the operator's Azure Key Vault) | The operator's NA |
| Operator (admin) keys | Operator's custody | Operator |
| Database: treaties, attestations, revocations, policies, decisions, evidence | Operator's SQLite file or PostgreSQL | Operator |
| Endpoint and DNS | Operator's infrastructure | Operator |
| Trust decisions (whom to recognize, what to revoke) | The operator's NA | Operator |

**Nothing in the software calls Genesis Core.** The Network Authority has no
built-in Genesis Core endpoint, key, sovereign identity or license check, and
`genesis_mesh/tests/test_operator_independence.py` fails if runtime code gains
one. Recognition is between sovereigns: another sovereign trusts you because
*it* issued a treaty naming your keys, not because Genesis Core vouched for
you.

## Leaving a federation

You recognize others through treaties you issued; they recognize you through
treaties they issued.

1. **Stop recognizing others.** Revoke each treaty you issued
   (`genesis-mesh treaty revoke TREATY_ID --na URL`), or let them expire.
   Revocation takes effect on your NA immediately.
2. **Revoke your members' attestations** that others accept, and publish your
   revocation feed (`GET /sovereign-revocation-feed`). Sovereigns that import
   it stop accepting those members.
3. **Tell your counterparts.** The treaties *they* issued about you are their
   decisions: they revoke them on their side. Until they do, they keep
   accepting attestations you signed earlier that are still valid, so revoke
   those first if you want them rejected.
4. **Keep your evidence.** If the evidence store is on (`EVIDENCE_STORE=on`,
   off by default), write an audit pack of the whole store
   (`genesis-mesh audit pack`) or archive it (`genesis-mesh audit archive`),
   and keep the anchors you fetched, so you can verify it offline later
   (`genesis-mesh audit verify`). Keep a database backup:
   `genesis-mesh managed backup` for SQLite, `pg_dump` for PostgreSQL.
   Without the evidence store, the database backup and the audit log export
   (`genesis-mesh managed audit-export`, SQLite only) are all there is.

## Leaving a managing partner

A managing partner may run infrastructure, DNS and runbooks for you; it must
never hold your root or operator keys (see {doc}`managing-partner-boundary`).

1. **Revoke the partner's operator keys**:
   `genesis-mesh admin revoke-operator-key KEY_ID --na URL`. A revoked key is
   refused before its signature is checked and stays revoked for the life of
   the deployment.
2. **Take the database**: an online backup (`genesis-mesh managed backup`) or
   a `pg_dump`, then `genesis-mesh na verify-db` on your copy.
3. **Take the endpoint**: point your DNS at infrastructure you control and
   run the NA there with your keys. Your sovereign identity does not change,
   so counterparts' treaties keep working.
4. **If the partner ever held your NA signing key** (the "managed NA key"
   custody model in {doc}`../operations/managed-sovereign`), treat the key as
   exposed: you cannot prove a copy was destroyed. What you can do depends on
   the root key:
   - **The partner never held the root key, and you still hold the NA key.**
     Succeed the NA key ({doc}`../operations/key-succession`): sign a
     succession with your offline root key, have the new key sign it, submit
     it, and restart the NA with the new key at `effective_at`. Your sovereign
     identity stays the same, and your NA signs nothing with the old key after
     the hand-over. Verifiers that read your key history (`/na/key-history`)
     still accept old-key signatures dated before the hand-over ends, so
     whoever holds a copy can still make records that look earlier: treat
     what the old key signed in that window as suspect. Counterparts' treaties
     name your NA public key, so ask each counterpart to issue a new treaty
     that names the new key (see {doc}`treaty-lifecycle`).
   - **The partner held the root key, or the NA key is lost.** A succession
     is not possible. Create a new genesis and keys, publish them, and ask
     counterparts to issue treaties to the new identity and revoke the old
     ones.

   This is why the split-operation model, where the operator keeps the keys,
   is the recommended pilot model.

## Forking

- The code is MIT-licensed. A fork may change anything.
- The protocol is public: RFC-001 to RFC-004 define identity, treaties, trust
  bundles and revocation feeds, including the exact signed bytes. Key
  succession (1.5.0) is not in an RFC yet: its records and rules are in
  {doc}`../reference/audit-pack-format` and
  {doc}`../operations/key-succession`, and the `audit` conformance suite
  covers them.
- Compatibility is testable without Genesis Core: a fork that passes the
  conformance vectors (`conformance/vectors/`) produces and accepts the same
  signed artifacts, so it interoperates with unmodified sovereigns.
- A fork run by an operator keeps the operator's identity and treaties: they
  are data in the operator's database and keys in the operator's custody.

## Limits

- Exit is unilateral, but **others' trust in you is theirs**: you cannot
  force a counterpart to revoke or keep a treaty it issued.
- Evidence and audit records written by your NA are yours; copies held by
  counterparts (decisions they received, attestations they cached) are theirs.
- A key succession replaces an NA key held by someone you no longer trust, as
  long as you hold the root key and the NA key. If the root key was exposed,
  or the NA key is already lost, recovery means a new identity (see above).
