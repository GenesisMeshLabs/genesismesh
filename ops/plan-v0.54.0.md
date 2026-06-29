# v0.54.0 Plan -- Go SDK

## Positioning

The TypeScript SDK (v0.53) targets web developers and MCP server authors.
The Go SDK targets the infrastructure layer: Kubernetes operators, cloud
backend services, edge systems, and API gateways.

Go's characteristics make it the right second SDK target:
- Single static binary deployment (no runtime dependency)
- Native concurrency model suits high-throughput trust checks
- Strong typing without a separate compilation step for consumers
- Cloud-native ecosystem: K8s, gRPC, service mesh integrations

Like the TypeScript SDK, the Go SDK is a typed client over the stable
Python API (v0.51).  It does not reimplement the protocol.  It makes the
protocol's capabilities accessible to Go infrastructure engineers without
any Python knowledge.

v0.53 should prove:

> A Go service can perform boundary checks, verify trust agreements, and
> submit data usage intents against a Genesis Mesh Network Authority using
> idiomatic Go: context-aware functions, typed errors, and zero external
> runtime dependencies.

## Design

### Module: `sdk/go/`

Published as Go module `github.com/thaersaidi/genesismesh/sdk`.

```
sdk/go/
  go.mod
  go.sum
  genesismesh/
    client.go          -- Client struct, options, HTTP transport
    agreement.go       -- Offer, Counter, Accept, Cosign, Verify
    boundary.go        -- Decide, Verify
    evidence.go        -- Build, Verify
    attestation.go     -- Create, Verify
    disclosure.go      -- Commit, Prove, Verify, Nullifier
    consensus.go       -- Vote, BuildProof, Verify
    data_usage.go      -- CreateIntent, VerifyIntent, VerifyRecord
    types.go           -- all protocol struct types
    errors.go          -- typed error types
  genesismesh_test/
    agreement_test.go
    boundary_test.go
    ...
  README.md
  examples/
    boundary_check/main.go
    data_intent/main.go
```

### `Client`

```go
type Client struct {
    Agreement  *AgreementClient
    Boundary   *BoundaryClient
    Evidence   *EvidenceClient
    Attestation *AttestationClient
    Disclosure  *DisclosureClient
    Consensus   *ConsensusClient
    DataUsage   *DataUsageClient
}

type Options struct {
    BaseURL    string
    SigningKey  []byte        // Ed25519 private key seed (32 bytes)
    APIKey     string         // Optional bearer token
    Timeout    time.Duration  // default 10s
    HTTPClient *http.Client   // Optional custom transport
}

func NewClient(opts Options) (*Client, error)
```

### Example: boundary check

```go
package main

import (
    "context"
    "fmt"
    "github.com/thaersaidi/genesismesh/sdk/genesismesh"
)

func main() {
    client, _ := genesismesh.NewClient(genesismesh.Options{
        BaseURL:   "https://na.example.com",
        SigningKey: loadKey("operator.key"),
    })

    result, err := client.Boundary.Decide(context.Background(), genesismesh.BoundaryRequest{
        RequestingAgent: "agent-a",
        TargetAgent:     "agent-b",
        Capability:      "transactions.read",
        AgreementID:     agreementID,
    })
    if err != nil {
        panic(err)
    }
    if !result.Allowed {
        fmt.Printf("denied: %s\n", result.Reason)
    }
}
```

### Error types

```go
type APIError struct {
    Code    string // protocol error code e.g. "capability_not_in_agreement"
    Message string
    Status  int    // HTTP status code
}

func (e *APIError) Error() string { ... }

// Sentinel errors for common cases
var (
    ErrUnauthorized       = &APIError{Code: "unauthorized"}
    ErrCapabilityDenied   = &APIError{Code: "capability_not_in_agreement"}
    ErrSignatureInvalid   = &APIError{Code: "invalid_signature"}
    ErrAgreementExpired   = &APIError{Code: "agreement_expired"}
)
```

### Types

All stable protocol models as Go structs with JSON tags:

```go
type AgreementRecord struct {
    AgreementID         string      `json:"agreement_id"`
    OffererSovereignID  string      `json:"offerer_sovereign_id"`
    ResponderSovereignID string     `json:"responder_sovereign_id"`
    AgreedTerms         AgreedTerms `json:"agreed_terms"`
    // ...
}
```

### Test strategy

`go test ./...` runs against a mock HTTP server (httptest).
Integration tests (`//go:build integration`) run against a real NA.

Minimum supported: Go 1.22.

### K8s admission webhook example (in `examples/`)

A minimal Kubernetes admission webhook that uses the Go SDK to check
boundary authorization before allowing a pod to be scheduled.  This
demonstrates the concrete cloud-native use case.

## Success Criteria

- [ ] `sdk/go/` with full module structure
- [ ] `Client` with all 7 sub-clients
- [ ] Go structs for all stable protocol models with correct JSON tags
- [ ] Typed error types; sentinel errors for common cases
- [ ] `go test ./...` >= 40 tests; all pass
- [ ] `go build ./...` produces no errors
- [ ] `examples/boundary_check/main.go` compiles and includes README
- [ ] K8s admission webhook example in `examples/`
- [ ] `README.md` with install + quick-start

## Release Gate

- [ ] Package metadata bumped to `0.53.0`
- [ ] `sdk/go/go.mod` version set to `v0.54.0`
- [ ] CHANGELOG entry (Go SDK)
- [ ] history.md updated with v0.54.0 entry
- [ ] All prior Python tests continue to pass
- [ ] TypeScript SDK tests continue to pass
