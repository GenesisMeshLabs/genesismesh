# .NET SDK

> **Added in v0.55.0** · Package: `genesismesh-sdk-dotnet` · Source: `sdk-dotnet/`

C# client for the Genesis Mesh Network Authority HTTP API.
Targets .NET 8 (`net8.0`); from 1.7.1 (unreleased) also .NET 10 (`net10.0`).
One runtime dependency: `NSec.Cryptography 25.4.0` (Ed25519).

**Scope.** The .NET SDK has the same scope as the Go SDK: its clients
(agreements, boundary decide and verify, trust evidence, attestations,
selective disclosure, consensus, data usage, raw admin calls) and
`OfflineVerifier` (agreements, boundary decisions, license policies and data
access intents) are stable. It does not wrap the policy lifecycle,
attestation evaluation or the evidence store: call those routes with raw
admin calls ({doc}`auth`). It also verifies the NA's key history (1.5.0) and
a pre-issued grant's signature (1.6.0) ({doc}`verification`). It has no
outbox, break-glass, observation or remediation API and does not hold grants:
those are in the TypeScript and Rust SDKs.

To develop against a governed NA on your machine, see
{doc}`../local-network-authority`. That NA requires boundary policies, so it
refuses `Boundary.Decide`: a controller calls `/admin/boundary/evaluate` with a
raw admin call instead (see {doc}`sub-clients`).

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

The client exposes 7 sub-clients:

```
client.Agreement   client.Boundary    client.Evidence
client.Attestation client.Disclosure  client.Consensus
client.DataUsage
```

The offline verifiers are static methods of `OfflineVerifier`
({doc}`verification`).

---

## Pages

- {doc}`sub-clients`: each sub-client's methods, the operator tier each one
  needs, and the NA's constraints
- {doc}`auth`: admin signatures, raw admin calls, errors and types
- {doc}`verification`: offline verification, the NA key history and
  pre-issued grants

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
pip install "genesis-mesh==1.7.*"
GM_E2E_PYTHON=python dotnet test --filter "Category=Live"
```

Without `GM_E2E_PYTHON` the test returns at once. From 1.7.1 (unreleased) the
solution also builds `net10.0`, so building `main` needs the .NET 10 SDK.

```{toctree}
:maxdepth: 1
:hidden:

sub-clients
auth
verification
```
