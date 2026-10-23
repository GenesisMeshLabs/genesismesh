# Go SDK

> **Added in v0.54.0** · Module: `github.com/GenesisMeshLabs/sdk-go` · Source: `sdk-go/`

Go client for the Genesis Mesh Network Authority HTTP API.
Go 1.22 or later. One runtime dependency: `github.com/google/uuid`, for nonces.

**Scope.** The Go SDK is stable for its clients (agreements, boundary decide
and verify, trust evidence, attestations, selective disclosure, consensus,
data usage, raw admin calls) and for offline verification of agreements,
boundary decisions, license policies and data access intents. It does not
wrap the policy lifecycle, attestation evaluation or the evidence store: call
those routes with raw admin calls ({doc}`auth`). It also verifies the NA's key
history (1.5.0) and a pre-issued grant's signature (1.6.0) ({doc}`verification`).
It has no outbox, break-glass, observation or remediation API and does not
hold grants: those are in the TypeScript and Rust SDKs.

To develop against a governed NA on your machine, see
{doc}`../local-network-authority`. That NA requires boundary policies, so it
refuses `Boundary.Decide`: a controller calls `/admin/boundary/evaluate` with a
raw admin call instead (see {doc}`sub-clients`).

---

## Install

```sh
go get github.com/GenesisMeshLabs/sdk-go@latest
```

---

## `NewClient`

```go
import (
	"time"

	"github.com/GenesisMeshLabs/sdk-go/genesismesh"
)

client, err := genesismesh.NewClient(genesismesh.ClientOptions{
	BaseURL:    "http://127.0.0.1:9443", // the local NA (see below)
	SigningKey: "<base64-seed>",         // 32-byte Ed25519 seed, base64-encoded
	KeyID:      "operator-local",        // identifies the key in signatures
	Timeout:    10 * time.Second,        // optional (default 10 s)
})
if err != nil {
	return err
}
```

The examples on these pages use the local NA from
{doc}`../local-network-authority`, which listens on port 9443. Without
`--na-port`, `genesis-mesh init` sets port 8443.

`SigningKey` and `KeyID` are only required for admin routes. You can omit them
when calling public verification endpoints only. The key's operator tier
decides which admin methods it may call (see {doc}`sub-clients`).

The client exposes 7 sub-clients:

```
client.Agreement   client.Boundary    client.Evidence
client.Attestation client.Disclosure  client.Consensus
client.DataUsage
```

The offline verifiers are package functions, such as
`genesismesh.VerifyBoundaryDecision` ({doc}`verification`).

---

## Pages

- {doc}`sub-clients`: each sub-client's methods, the operator tier each one
  needs, and the NA's constraints
- {doc}`auth`: admin signatures, raw admin calls, errors and types
- {doc}`verification`: offline verification, the NA key history and
  pre-issued grants

---

## Build and test

In an `sdk-go` checkout:

```sh
go build ./...
go test -race ./...
go vet ./...
```

The live contract test checks every client method against a real Network
Authority. It starts a disposable NA from the Python package
(`scripts/contract_na.py`), so the Python it runs needs `genesis-mesh`
installed:

```sh
pip install "genesis-mesh==1.8.*"
GM_E2E_PYTHON=python go test -tags live -count=1 -run '^TestLiveContract$' ./genesismesh
```

Without `GM_E2E_PYTHON` the test is skipped.

```{toctree}
:maxdepth: 1
:hidden:

sub-clients
auth
verification
```
