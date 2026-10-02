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
4. **Keep your evidence.** Export it before decommissioning
   (`GET /admin/evidence/export`, verifiable offline with
   `genesis-mesh evidence verify-export`), and keep a database backup
   (`genesis-mesh managed backup`).

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
   exposed: you cannot prove a copy was destroyed. There is no NA key rotation
   procedure that preserves your identity yet (an open question in RFC-001),
   so the safe path is a new sovereign identity: create a new genesis and keys,
   publish them, and ask counterparts to issue treaties to it and revoke the
   old ones. This is why the split-operation model, where the operator keeps
   the keys, is the recommended pilot model.

## Forking

- The code is MIT-licensed. A fork may change anything.
- The protocol is public: RFC-001 to RFC-004 define identity, treaties, trust
  bundles and revocation feeds, including the exact signed bytes.
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
- Without NA key rotation, recovering from a key held by someone you no longer
  trust means a new identity (see above).
