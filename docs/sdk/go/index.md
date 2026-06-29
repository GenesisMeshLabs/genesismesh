# Go SDK

> **Added in v0.54.0** · Module: `github.com/GenesisMeshLabs/sdk-go` · Source: `sdk-go/`

Go client for the Genesis Mesh Network Authority HTTP API.
Go ≥ 1.22 required. Zero runtime dependencies (stdlib + `github.com/google/uuid`).

---

## Install

```sh
go get github.com/GenesisMeshLabs/sdk-go@latest
```

---

## `NewClient`

```go
import "github.com/GenesisMeshLabs/sdk-go/genesismesh"

client, err := genesismesh.NewClient(genesismesh.ClientOptions{
    BaseURL:    "http://127.0.0.1:9443",  // NA address
    SigningKey: "<base64-seed>",          // 32-byte Ed25519 seed, base64-encoded
    KeyID:      "operator-local",         // identifies the key in signatures
    Timeout:    10 * time.Second,         // optional (default 10 s)
})
```

`SigningKey` and `KeyID` are only required for admin routes. You can omit them
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
go build ./...
go test -race ./...
go vet ./...
```

Smoke test against a live NA:

```sh
cd sandbox/sdk-smoke-go
go run ./smoke.go   # requires NA on http://127.0.0.1:9443
```

```{toctree}
:maxdepth: 1
:hidden:

sub-clients
auth
```
