// Leg 2 (Go): verify the Python leg's agreement, boundary decisions and data
// license policy offline with the Go SDK, and record the verdicts in
// fixtures/results/go.json for comparison with the other implementations.
//
//	go run . ../fixtures
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"

	gm "github.com/GenesisMeshLabs/sdk-go/genesismesh"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "[GO VERIFIER] error:", err)
		os.Exit(1)
	}
}

func run() error {
	dir := "../fixtures"
	if len(os.Args) > 1 {
		dir = os.Args[1]
	}
	read := func(name string) []byte {
		data, err := os.ReadFile(filepath.Join(dir, name))
		if err != nil {
			panic(err)
		}
		return data
	}
	var keys map[string]string
	if err := json.Unmarshal(read("public_keys.json"), &keys); err != nil {
		return err
	}
	na := []string{keys["na"]}
	verdicts := map[string]map[string]interface{}{}

	for _, name := range []string{"agreement", "agreement_tampered"} {
		r, err := gm.VerifyAgreement(read(name+".json"), []string{keys["org-a"]}, []string{keys["bank-a"]}, "")
		if err != nil {
			return fmt.Errorf("%s: %w", name, err)
		}
		verdicts[name] = map[string]interface{}{"accepted": r.Accepted, "reason": r.Reason}
	}

	now := time.Now().UTC()
	policies := [][]byte{read("boundary_policy.json")}
	decisions := []struct {
		name        string
		policies    [][]byte
		attestation []byte
	}{
		{"boundary_decision", policies, nil},
		{"boundary_decision_denied", policies, nil},
		{"boundary_decision_attestation", policies, read("attestation.json")},
		{"boundary_decision_tampered", nil, nil},
	}
	for _, d := range decisions {
		r, err := gm.VerifyBoundaryDecision(read(d.name+".json"), gm.DecisionVerifyOptions{
			OperatorPublicKeys: na, Now: now, ExpectedPolicies: d.policies, ExpectedAttestation: d.attestation,
		})
		if err != nil {
			return fmt.Errorf("%s: %w", d.name, err)
		}
		verdicts[d.name] = map[string]interface{}{"accepted": r.Accepted, "reason": r.Reason, "authorized": r.Authorized}
	}

	valid, err := gm.VerifyDataLicensePolicySignature(read("data_policy.json"), na)
	if err != nil {
		return fmt.Errorf("data_policy: %w", err)
	}
	verdicts["data_policy"] = map[string]interface{}{"valid": valid}

	out, _ := json.MarshalIndent(map[string]interface{}{"leg": "go", "verdicts": verdicts}, "", "  ")
	if err := os.MkdirAll(filepath.Join(dir, "results"), 0o755); err != nil {
		return err
	}
	if err := os.WriteFile(filepath.Join(dir, "results", "go.json"), append(out, '\n'), 0o644); err != nil {
		return err
	}
	for _, name := range []string{"agreement", "agreement_tampered", "boundary_decision", "boundary_decision_denied",
		"boundary_decision_attestation", "boundary_decision_tampered", "data_policy"} {
		fmt.Printf("[GO VERIFIER] %s: %v\n", name, verdicts[name])
	}
	if verdicts["agreement"]["accepted"] != true || verdicts["boundary_decision"]["authorized"] != true ||
		verdicts["boundary_decision"]["accepted"] != true {
		return fmt.Errorf("agreement or boundary decision did not verify")
	}
	fmt.Println("[GO VERIFIER] agreement: OK  boundary: OK")
	return nil
}
