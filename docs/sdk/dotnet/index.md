# .NET SDK

> **Added in v0.55.0** · Package: `genesismesh-sdk-dotnet` · Source: `sdk-dotnet/`

C# client for the Genesis Mesh Network Authority HTTP API.
.NET 8 (`net8.0`) required. One runtime dependency: `NSec.Cryptography 25.4.0` (Ed25519).

---

## Install

```sh
dotnet add package genesismesh-sdk-dotnet
```

---

## `GenesisMeshClient`

```csharp
using GenesisMesh;

var client = new GenesisMeshClient(new ClientOptions
{
    BaseUrl    = "http://127.0.0.1:9443",  // NA address
    SigningKey = "<base64-seed>",           // 32-byte Ed25519 seed, base64-encoded
    KeyId      = "operator-local",          // identifies the key in signatures
});
```

`SigningKey` and `KeyId` are only required for admin routes. You can omit them
when calling public verification endpoints only.

The client exposes 7 sub-clients:

```
client.Agreement   client.Boundary    client.Evidence
client.Attestation client.Disclosure  client.Consensus
client.DataUsage
```

---

## Build and test

```sh
cd sdk-dotnet
dotnet build
dotnet test
```

```{toctree}
:maxdepth: 1
:hidden:

sub-clients
auth
```
