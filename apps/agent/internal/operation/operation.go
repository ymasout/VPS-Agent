package operation

import (
	"context"
	"crypto/ed25519"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/example/vps-agent-console/apps/agent/internal/client"
	"github.com/example/vps-agent-console/apps/agent/internal/collector"
	"github.com/example/vps-agent-console/apps/agent/internal/config"
)

const executionTimeout = 30 * time.Second
const maxLedgerRecords = 1024

type record struct {
	OperationID string                 `json:"operation_id"`
	Status      string                 `json:"status"`
	Result      client.OperationResult `json:"result"`
	Delivered   bool                   `json:"delivered"`
	UpdatedAt   time.Time              `json:"updated_at"`
}

type Ledger struct {
	path    string
	mu      sync.Mutex
	records map[string]record
}

type PendingResult struct {
	OperationID string
	Result      client.OperationResult
}

func OpenLedger(path string) (*Ledger, error) {
	ledger := &Ledger{path: path, records: map[string]record{}}
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return ledger, nil
	}
	if err != nil {
		return nil, err
	}
	if err = json.Unmarshal(data, &ledger.records); err != nil {
		return nil, fmt.Errorf("decode operation ledger: %w", err)
	}
	return ledger, nil
}

func (ledger *Ledger) Prepare(task client.OperationTask) (client.OperationResult, bool, error) {
	ledger.mu.Lock()
	defer ledger.mu.Unlock()
	if existing, ok := ledger.records[task.IdempotencyKey]; ok {
		if existing.Status == "completed" {
			return existing.Result, false, nil
		}
		result := failed("execution_outcome_unknown", "Agent restarted after execution began; task was not replayed")
		ledger.records[task.IdempotencyKey] = record{OperationID: task.OperationID, Status: "completed", Result: result, UpdatedAt: time.Now().UTC()}
		return result, false, ledger.save()
	}
	for len(ledger.records) >= maxLedgerRecords {
		oldestKey := ledger.oldestDeliveredKey()
		if oldestKey == "" {
			return client.OperationResult{}, false, errors.New("operation ledger is full with undelivered results")
		}
		delete(ledger.records, oldestKey)
	}
	ledger.records[task.IdempotencyKey] = record{OperationID: task.OperationID, Status: "started", UpdatedAt: time.Now().UTC()}
	return client.OperationResult{}, true, ledger.save()
}

func (ledger *Ledger) Complete(key string, result client.OperationResult) error {
	ledger.mu.Lock()
	defer ledger.mu.Unlock()
	item, ok := ledger.records[key]
	if !ok {
		return errors.New("operation ledger record is missing")
	}
	item.Status, item.Result, item.Delivered, item.UpdatedAt = "completed", result, false, time.Now().UTC()
	ledger.records[key] = item
	return ledger.save()
}

func (ledger *Ledger) oldestDeliveredKey() string {
	var oldestKey string
	var oldest time.Time
	for key, item := range ledger.records {
		if !item.Delivered {
			continue
		}
		if oldestKey == "" || item.UpdatedAt.Before(oldest) {
			oldestKey, oldest = key, item.UpdatedAt
		}
	}
	return oldestKey
}

func (ledger *Ledger) Pending() map[string]PendingResult {
	ledger.mu.Lock()
	defer ledger.mu.Unlock()
	result := map[string]PendingResult{}
	for key, item := range ledger.records {
		if item.Status == "completed" && !item.Delivered {
			result[key] = PendingResult{OperationID: item.OperationID, Result: item.Result}
		}
	}
	return result
}

func (ledger *Ledger) MarkDelivered(key string) error {
	ledger.mu.Lock()
	defer ledger.mu.Unlock()
	item, ok := ledger.records[key]
	if !ok {
		return nil
	}
	item.Delivered = true
	item.UpdatedAt = time.Now().UTC()
	ledger.records[key] = item
	return ledger.save()
}

func (ledger *Ledger) save() error {
	if err := os.MkdirAll(filepath.Dir(ledger.path), 0700); err != nil {
		return err
	}
	data, err := json.Marshal(ledger.records)
	if err != nil {
		return err
	}
	temporary := ledger.path + ".tmp"
	if err = os.WriteFile(temporary, data, 0600); err != nil {
		return err
	}
	if err = os.Chmod(temporary, 0600); err != nil {
		return err
	}
	return os.Rename(temporary, ledger.path)
}

func Verify(task client.OperationTask, agentID string, cfg config.Config, now time.Time) error {
	if !config.OperationPolicyAllows(cfg.OperationPolicy, config.OperationPolicyDockerRestart) {
		return errors.New("Docker restart policy is disabled")
	}
	if task.Version != "v1" || task.ActionType != "docker_restart" || task.ServiceKind != "docker" {
		return errors.New("unsupported operation task")
	}
	if task.AgentID != agentID || task.KeyID == "" || task.KeyID != cfg.OperationKeyID {
		return errors.New("operation task identity or key id mismatch")
	}
	if !task.IssuedAt.Before(task.ExpiresAt) || now.Before(task.IssuedAt.Add(-30*time.Second)) || !now.Before(task.ExpiresAt) {
		return errors.New("operation task is expired or not yet valid")
	}
	if task.OperationID == "" || task.ServiceKey == "" || task.IdempotencyKey == "" || task.Nonce == "" || task.Attempt < 1 {
		return errors.New("operation task is incomplete")
	}
	publicKey, err := base64.StdEncoding.DecodeString(cfg.OperationPublicKey)
	if err != nil || len(publicKey) != ed25519.PublicKeySize {
		return errors.New("operation verification key is invalid")
	}
	signature, err := base64.StdEncoding.DecodeString(task.Signature)
	if err != nil || len(signature) != ed25519.SignatureSize {
		return errors.New("operation signature is invalid")
	}
	fields := []string{
		"v1", task.OperationID, task.ActionType, task.AgentID, task.ServiceKind,
		task.ServiceKey, task.IssuedAt.UTC().Format("2006-01-02T15:04:05Z"),
		task.ExpiresAt.UTC().Format("2006-01-02T15:04:05Z"), task.IdempotencyKey,
		strconv.Itoa(task.Attempt), task.Nonce, task.KeyID,
	}
	if !ed25519.Verify(ed25519.PublicKey(publicKey), []byte(strings.Join(fields, "\n")), signature) {
		return errors.New("operation signature verification failed")
	}
	return nil
}

func ExecuteDockerRestart(ctx context.Context, task client.OperationTask) client.OperationResult {
	target, err := resolveDockerTarget(ctx, task.ServiceKey)
	if err != nil {
		return failed("target_resolution_failed", err.Error())
	}
	executionContext, cancel := context.WithTimeout(ctx, executionTimeout)
	defer cancel()
	command := exec.CommandContext(executionContext, "docker", "restart", "--", target)
	if err = command.Run(); err != nil {
		if errors.Is(executionContext.Err(), context.DeadlineExceeded) {
			return failed("execution_timeout", "Docker restart exceeded the fixed timeout")
		}
		return failed("execution_failed", "Docker restart returned a non-zero exit status")
	}
	exitCode := 0
	return client.OperationResult{
		Status: "completed", ExitCode: &exitCode,
		Output:      "Docker restart program exited successfully; awaiting independent health verification.",
		CompletedAt: time.Now().UTC(),
	}
}

func resolveDockerTarget(ctx context.Context, serviceKey string) (string, error) {
	output, err := exec.CommandContext(
		ctx, "docker", "ps", "-a", "--format",
		`{{.Names}}|{{.Label "com.docker.compose.project"}}|{{.Label "com.docker.compose.service"}}|{{.Label "com.docker.compose.container-number"}}`,
	).Output()
	if err != nil {
		return "", errors.New("Docker service discovery failed")
	}
	var matches []string
	for _, line := range strings.Split(strings.TrimSpace(string(output)), "\n") {
		parts := strings.SplitN(line, "|", 4)
		if len(parts) != 4 || parts[0] == "" {
			continue
		}
		if collector.StableDockerServiceKey(parts[0], parts[1], parts[2], parts[3]) == serviceKey {
			matches = append(matches, parts[0])
		}
	}
	if len(matches) == 0 {
		return "", errors.New("stable service identity is not present locally")
	}
	if len(matches) != 1 {
		return "", errors.New("stable service identity resolved ambiguously")
	}
	return matches[0], nil
}

func failed(code, detail string) client.OperationResult {
	exitCode := -1
	return client.OperationResult{
		Status: "failed", ExitCode: &exitCode, ErrorCode: code,
		ErrorDetail: detail, CompletedAt: time.Now().UTC(),
	}
}
