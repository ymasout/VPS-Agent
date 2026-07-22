package operation

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/base64"
	"fmt"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/example/vps-agent-console/apps/agent/internal/client"
	"github.com/example/vps-agent-console/apps/agent/internal/config"
)

func signedTask(t *testing.T) (client.OperationTask, config.Config) {
	t.Helper()
	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC().Truncate(time.Second)
	task := client.OperationTask{
		Version: "v1", OperationID: "operation-1", ActionType: "docker_restart",
		AgentID: "agent-1", ServiceKind: "docker", ServiceKey: "compose:demo:api:1",
		IssuedAt: now.Add(-time.Second), ExpiresAt: now.Add(time.Minute),
		IdempotencyKey: "idempotency-1", Attempt: 1, Nonce: "nonce-1", KeyID: "m4-test",
	}
	fields := []string{
		"v1", task.OperationID, task.ActionType, task.AgentID, task.ServiceKind,
		task.ServiceKey, task.IssuedAt.Format("2006-01-02T15:04:05Z"),
		task.ExpiresAt.Format("2006-01-02T15:04:05Z"), task.IdempotencyKey,
		"1", task.Nonce, task.KeyID,
	}
	task.Signature = base64.StdEncoding.EncodeToString(ed25519.Sign(privateKey, []byte(strings.Join(fields, "\n"))))
	cfg := config.Config{
		OperationPolicy:    config.OperationPolicyDockerRestart,
		OperationKeyID:     task.KeyID,
		OperationPublicKey: base64.StdEncoding.EncodeToString(publicKey),
	}
	return task, cfg
}

func TestVerifyAcceptsBoundSignedTask(t *testing.T) {
	task, cfg := signedTask(t)
	if err := Verify(task, "agent-1", cfg, time.Now().UTC()); err != nil {
		t.Fatalf("Verify() error = %v", err)
	}
}

func TestVerifyAcceptsV2AndBindsBothDigests(t *testing.T) {
	publicKey, privateKey, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC().Truncate(time.Second)
	task := client.OperationTask{
		Version: "v2", OperationID: "deploy-1", ActionType: "docker_compose_deploy",
		AgentID: "agent-1", ServiceKind: "docker", ServiceKey: "compose:demo:api:1",
		CurrentDigest: "ghcr.io/org/app@" + testDigestA,
		TargetDigest:  "ghcr.io/org/app@" + testDigestB,
		IssuedAt:      now.Add(-time.Second), ExpiresAt: now.Add(time.Minute),
		IdempotencyKey: "deploy-key", Attempt: 1, Nonce: "nonce-v2", KeyID: "m4-test",
	}
	fields := []string{
		"v2", task.OperationID, task.ActionType, task.AgentID, task.ServiceKind,
		task.ServiceKey, task.CurrentDigest, task.TargetDigest,
		task.IssuedAt.UTC().Format("2006-01-02T15:04:05Z"),
		task.ExpiresAt.UTC().Format("2006-01-02T15:04:05Z"), task.IdempotencyKey,
		"1", task.Nonce, task.KeyID,
	}
	task.Signature = base64.StdEncoding.EncodeToString(ed25519.Sign(privateKey, []byte(strings.Join(fields, "\n"))))
	cfg := config.Config{
		DeployPolicy:       config.DeployPolicyDockerComposeDeploy,
		DeployAllowedRoots: []string{t.TempDir()},
		OperationKeyID:     task.KeyID,
		OperationPublicKey: base64.StdEncoding.EncodeToString(publicKey),
	}
	if err = Verify(task, "agent-1", cfg, now); err != nil {
		t.Fatalf("Verify(v2) error = %v", err)
	}
	tampered := task
	tampered.TargetDigest = "ghcr.io/org/app@" + testDigestA
	if err = Verify(tampered, "agent-1", cfg, now); err == nil {
		t.Fatal("Verify(v2) accepted a tampered target digest")
	}
	cfg.DeployPolicy = config.DeployPolicyPlanOnly
	if err = Verify(task, "agent-1", cfg, now); err == nil {
		t.Fatal("plan-only policy accepted a v2 deployment task")
	}
}

func TestVerifyRejectsTamperExpiryReplayAndDisabledPolicy(t *testing.T) {
	task, cfg := signedTask(t)
	tampered := task
	tampered.ServiceKey = "docker:other"
	if err := Verify(tampered, "agent-1", cfg, time.Now().UTC()); err == nil {
		t.Fatal("Verify() accepted a tampered task")
	}
	if err := Verify(task, "agent-1", cfg, task.ExpiresAt); err == nil {
		t.Fatal("Verify() accepted an expired task")
	}
	cfg.OperationPolicy = "disabled"
	if err := Verify(task, "agent-1", cfg, time.Now().UTC()); err == nil {
		t.Fatal("Verify() accepted a task while write policy was disabled")
	}
}

func TestVerifyRejectsIdentityAttemptAndMalformedSignature(t *testing.T) {
	task, cfg := signedTask(t)

	wrongKey := task
	wrongKey.KeyID = "unexpected-key"
	if err := Verify(wrongKey, "agent-1", cfg, time.Now().UTC()); err == nil {
		t.Fatal("Verify() accepted a mismatched key id")
	}

	invalidAttempt := task
	invalidAttempt.Attempt = 0
	if err := Verify(invalidAttempt, "agent-1", cfg, time.Now().UTC()); err == nil {
		t.Fatal("Verify() accepted attempt zero")
	}

	malformedSignature := task
	malformedSignature.Signature = base64.StdEncoding.EncodeToString([]byte("short"))
	if err := Verify(malformedSignature, "agent-1", cfg, time.Now().UTC()); err == nil {
		t.Fatal("Verify() accepted a malformed signature length")
	}
}

func TestLedgerDoesNotReplayStartedOrCompletedTask(t *testing.T) {
	task, _ := signedTask(t)
	path := filepath.Join(t.TempDir(), "operations.json")
	ledger, err := OpenLedger(path)
	if err != nil {
		t.Fatal(err)
	}
	if _, execute, err := ledger.Prepare(task); err != nil || !execute {
		t.Fatalf("first Prepare() = execute %v, error %v", execute, err)
	}
	reopened, err := OpenLedger(path)
	if err != nil {
		t.Fatal(err)
	}
	result, execute, err := reopened.Prepare(task)
	if err != nil || execute || result.ErrorCode != "execution_outcome_unknown" {
		t.Fatalf("replay Prepare() = %#v, execute %v, error %v", result, execute, err)
	}
	if err = reopened.Complete(task.IdempotencyKey, result); err != nil {
		t.Fatal(err)
	}
	if len(reopened.Pending()) != 1 {
		t.Fatal("completed result was not retained for network retry")
	}
	if err = reopened.MarkDelivered(task.IdempotencyKey); err != nil {
		t.Fatal(err)
	}
	if len(reopened.Pending()) != 0 {
		t.Fatal("delivered result remained pending")
	}
}

func TestLedgerEvictsOnlyDeliveredRecords(t *testing.T) {
	task, _ := signedTask(t)
	task.IdempotencyKey = "new-task"
	ledger := &Ledger{
		path:    filepath.Join(t.TempDir(), "operations.json"),
		records: map[string]record{},
	}
	ledger.records["pending-result"] = record{
		OperationID: "pending-operation",
		Status:      "completed",
		Delivered:   false,
		UpdatedAt:   time.Now().UTC().Add(-time.Hour),
	}
	for index := 0; index < maxLedgerRecords-1; index++ {
		key := fmt.Sprintf("delivered-%04d", index)
		ledger.records[key] = record{
			OperationID: key,
			Status:      "completed",
			Delivered:   true,
			UpdatedAt:   time.Now().UTC().Add(time.Duration(index) * time.Second),
		}
	}

	if _, execute, err := ledger.Prepare(task); err != nil || !execute {
		t.Fatalf("Prepare() = execute %v, error %v", execute, err)
	}
	if _, ok := ledger.records["pending-result"]; !ok {
		t.Fatal("Prepare() evicted an undelivered result")
	}
	if _, ok := ledger.records[task.IdempotencyKey]; !ok {
		t.Fatal("Prepare() did not retain the new task")
	}
	if len(ledger.records) != maxLedgerRecords {
		t.Fatalf("ledger size = %d, want %d", len(ledger.records), maxLedgerRecords)
	}
}

func TestLedgerRejectsNewExecutionWhenAllRecordsAreUndelivered(t *testing.T) {
	task, _ := signedTask(t)
	task.IdempotencyKey = "must-not-start"
	ledger := &Ledger{
		path:    filepath.Join(t.TempDir(), "operations.json"),
		records: map[string]record{},
	}
	for index := 0; index < maxLedgerRecords; index++ {
		key := fmt.Sprintf("pending-%04d", index)
		ledger.records[key] = record{OperationID: key, Status: "completed", Delivered: false}
	}

	if _, execute, err := ledger.Prepare(task); err == nil || execute {
		t.Fatalf("Prepare() = execute %v, error %v; want safe rejection", execute, err)
	}
	if _, ok := ledger.records[task.IdempotencyKey]; ok {
		t.Fatal("rejected task was added to the full ledger")
	}
}
