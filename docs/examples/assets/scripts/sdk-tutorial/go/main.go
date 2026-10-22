package main

import (
	"context"
	"errors"
	"fmt"
	"log"
	"os"

	"github.com/GenesisMeshLabs/sdk-go/genesismesh"
)

func main() {
	ctx := context.Background()

	baseURL := os.Getenv("GM_NA_URL")
	if baseURL == "" {
		baseURL = "http://127.0.0.1:9443"
	}

	// Step 2: create an admin client
	client, err := genesismesh.NewClient(genesismesh.ClientOptions{
		BaseURL:    baseURL,
		SigningKey: os.Getenv("GM_ADMIN_KEY_B64"),
		KeyID:      os.Getenv("GM_ADMIN_KEY_ID"),
	})
	if err != nil {
		log.Fatal(err)
	}

	// Step 3: build trust evidence for a decision
	decision := genesismesh.TrustDecision{
		SourceSovereignID: "ALPHA-NA",
		TargetSovereignID: "BETA-NA",
		Verdict:           "allow",
		Reason:            "Recognition treaty active, attestation valid",
	}

	evidence, err := client.Evidence.Build(ctx, decision)
	if err != nil {
		log.Fatal(err)
	}

	fmt.Println(evidence.EvidenceID) // a UUID
	fmt.Println(evidence.Verdict)    // "allow"
	fmt.Println(evidence.IssuedAt)   // ISO 8601 timestamp

	// Step 4: verify the evidence
	publicClient, err := genesismesh.NewClient(genesismesh.ClientOptions{
		BaseURL: baseURL,
	})
	if err != nil {
		log.Fatal(err)
	}

	result, err := publicClient.Evidence.Verify(ctx, map[string]interface{}{
		"evidence": evidence,
	})
	if err != nil {
		log.Fatal(err)
	}

	fmt.Println(result.Accepted) // true
	fmt.Println(result.Reason)   // "accepted"

	// Step 5: handle errors
	_, err = client.Evidence.Build(ctx, genesismesh.TrustDecision{
		SourceSovereignID: "ALPHA-NA",
		TargetSovereignID: "BETA-NA",
		Verdict:           "trusted", // not in the allowed set
		Reason:            "testing",
	})

	var bre *genesismesh.BadRequestError
	if errors.As(err, &bre) {
		fmt.Println(bre.Status, bre.Code, bre.Message)
		// 400 invalid_verdict verdict must be one of: allow, block, escalate, warn
	} else if err != nil {
		log.Fatal(err)
	}
}
