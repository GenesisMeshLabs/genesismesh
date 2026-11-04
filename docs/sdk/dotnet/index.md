# .NET SDK

> **Added in v0.55.0** · Package: `genesismesh-sdk-dotnet` · Source: `sdk-dotnet/`

C# client for the Genesis Mesh Network Authority HTTP API.
Targets .NET 8 (`net8.0`); from 1.8.0 also .NET 10 (`net10.0`).
One runtime dependency: `NSec.Cryptography 25.4.0` (Ed25519).

**Scope.** From 1.9.0 the .NET SDK is a governed client, as the TypeScript
SDK is (decision {doc}`../../development/decisions/0008-dotnet-governed-client`).
Up to 1.8.1 it had the Go SDK's scope: the trust API's clients, offline
verification of agreements, boundary decisions, license policies and data
access intents, the NA's key history (1.5.0) and a pre-issued grant's
signature (1.6.0). From 1.9.0 it also has:

- **Calls to the NA:** policies and policy-aware evaluation, the evidence
  store (execution evidence, histories, the export, executor keys, retention,
  anchors, audit packs and archives), changes made outside the governed path,
  remediation and reviews, pre-issued grants, health and the NA's key history
  ({doc}`sub-clients`).
- **Governed actions:** `Governance.GovernedAction` with the evidence outbox
  and reconciliation, break-glass when the NA cannot be reached, the record
  outbox, cancelling a denied change and urgent changes ({doc}`governance`),
  and a `GrantHolder` that acts within a pre-issued grant ({doc}`grants`).
- **Offline verification:** the NA's other signed records, an evidence export,
  store anchors, audit packs and their completeness check
  ({doc}`verification`).
- **The transport:** several NA instances with failover, retries and signers
  for a key the client does not hold (below).

The node identity and the edge agent stay in the Rust SDK.

To develop against a governed NA on your machine, see
{doc}`../local-network-authority`. That NA requires boundary policies, so it
refuses `Boundary.Decide`: a controller calls `Boundary.Evaluate` (1.9.0), or
`/admin/boundary/evaluate` with a raw admin call before 1.9.0 (see
{doc}`sub-clients`).

---

## Install

```sh
dotnet add package genesismesh-sdk-dotnet
```

---

## `GenesisMeshClient`

```csharp
using GenesisMesh;

using var client = new GenesisMeshClient(new ClientOptions
{
    BaseUrl    = "http://127.0.0.1:9443",  // the local NA (see below)
    SigningKey = "<base64-seed>",           // 32-byte Ed25519 seed, base64-encoded
    KeyId      = "operator-local",          // identifies the key in signatures
});
```

The examples on these pages use the local NA from
{doc}`../local-network-authority`, which listens on port 9443. Without
`--na-port`, `genesis-mesh init` sets port 8443.

`SigningKey` and `KeyId` are only required for admin routes. You can omit them
when calling public verification endpoints only. The key's operator tier
decides which admin methods it may call (see {doc}`sub-clients`).

The client owns one `HttpClient`: create one client, reuse it, and dispose it
when done.

The client exposes 7 sub-clients up to 1.8.1, and 12 from 1.9.0:

```
client.Agreement   client.Boundary    client.Evidence
client.Attestation client.Disclosure  client.Consensus
client.DataUsage
client.Policy      client.EvidenceStore  client.Grants      (1.9.0)
client.Health      client.NA                                (1.9.0)
```

The offline verifiers are static methods of `OfflineVerifier`
({doc}`verification`); the governed actions are in `Governance`
({doc}`governance`).

### Several NA instances (1.9.0)

```csharp
using var client = new GenesisMeshClient(new ClientOptions
{
    BaseUrls = ["https://na-1.internal:9443", "https://na-2.internal:9443"],
    Signer   = new SeedSigner(seed, "controller"),   // or your own ISigner, such as an HSM
    Retry    = new RetrySettings { Attempts = 3 },
});
```

- **`BaseUrls`:** several instances sharing one database, without a load
  balancer. An idempotent request (a GET, a verification) moves to the next
  instance on a connection failure or a 502, 503 or 504. Any other request
  moves only when it never reached an instance.
- **`Retry`:** idempotent requests are tried again after a connection failure
  or a 429, 502, 503 or 504, with a doubling delay. A request that creates
  state is never retried.
- **`Signer`:** signs admin requests instead of `SigningKey` and `KeyId`.
- **`HttpClient`, `HttpHandler`, `Headers` and `Timeout`:** for
  `IHttpClientFactory`, connection lifetimes and gateways in front of the NA.
- **`Outbox` and `RecordOutbox`:** durable storage for records the NA has not
  admitted yet ({doc}`governance`).

---

## Pages

- **Calling the NA**
  - {doc}`sub-clients`: each sub-client's methods, the operator tier each
    one needs, and the NA's constraints
  - {doc}`auth`: admin signatures, raw admin calls, errors and types
- **A governed controller** (1.9.0)
  - {doc}`governance`: governed actions, the outboxes, break-glass, changes
    outside the governed path, remediation and reviews
  - {doc}`grants`: pre-issued grants, and acting within one offline
- **Verifying offline**
  - {doc}`verification`: signed records, the NA key history, evidence
    exports, store anchors and audit packs

---

## Build and test

In an `sdk-dotnet` checkout:

```sh
dotnet build
dotnet test --filter "Category!=Live"
```

The live contract test checks every client method against a real Network
Authority. It starts a disposable NA from the Python package
(`scripts/contract_na.py`), so the Python it runs needs `genesis-mesh`
installed:

```sh
pip install "genesis-mesh==1.8.*"
GM_E2E_PYTHON=python dotnet test --filter "Category=Live"
```

Without `GM_E2E_PYTHON` the test returns at once. From 1.8.0 the
solution also builds `net10.0`, so building `main` needs the .NET 10 SDK.

```{toctree}
:maxdepth: 1
:hidden:

sub-clients
auth
governance
grants
verification
```
