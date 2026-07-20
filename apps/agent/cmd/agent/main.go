package main

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"github.com/example/vps-agent-console/apps/agent/internal/client"
	"github.com/example/vps-agent-console/apps/agent/internal/collector"
	"github.com/example/vps-agent-console/apps/agent/internal/config"
	operationexecutor "github.com/example/vps-agent-console/apps/agent/internal/operation"
)

var version = "0.4.0-dev"

var capabilities = []string{"host.metrics", "docker.status", "systemd.status", "http.healthcheck", "evidence.docker_logs.v1", "evidence.systemd_journal.v1"}

func main() {
	if len(os.Args) == 2 && os.Args[1] == "--version" {
		println("vps-agent " + version)
		return
	}
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	cfg := config.Load()
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	host, err := collector.HostInfo()
	if err != nil {
		logger.Error("host discovery failed", "error", err)
		os.Exit(1)
	}
	if cfg.MachineID != "" {
		host.MachineID = cfg.MachineID
	}
	api := client.New(cfg.ControlPlaneURL)
	identity, err := loadIdentity(cfg.CredentialFile)
	if errors.Is(err, os.ErrNotExist) {
		if cfg.RegistrationToken == "" {
			logger.Error("agent is not registered and AGENT_REGISTRATION_TOKEN is empty")
			os.Exit(1)
		}
		identity, err = api.Register(ctx, client.RegisterRequest{Token: cfg.RegistrationToken, Name: cfg.AgentName, Hostname: host.Hostname, MachineID: host.MachineID, OS: host.OS, Arch: host.Arch, Version: version, Capabilities: capabilities})
		if err == nil {
			err = saveIdentity(cfg.CredentialFile, identity)
		}
	}
	if err != nil {
		logger.Error("agent identity initialization failed", "error", err)
		os.Exit(1)
	}
	send := func() {
		metrics, services, err := collector.Collect(ctx)
		if err != nil {
			logger.Error("collection failed", "error", err)
			return
		}
		services = append(services, collector.HTTPHealthchecks(ctx, cfg.HealthcheckURLs)...)
		localSources := collector.EvidenceSourcesForServices(
			services,
			cfg.EvidenceSources,
			config.EvidencePolicyAllows(cfg.EvidencePolicy, config.EvidencePolicyDockerLogs),
			config.EvidencePolicyAllows(cfg.EvidencePolicy, config.EvidencePolicySystemdJournal),
		)
		sources := make([]client.EvidenceSource, 0, len(localSources))
		for _, source := range localSources {
			sources = append(sources, client.EvidenceSource{
				Key: source.Key, Kind: source.Kind, DisplayName: source.DisplayName,
				ServiceKind: source.ServiceKind, ServiceKey: source.ServiceKey,
			})
		}
		operationCapabilities := make([]client.OperationCapability, 0)
		if config.OperationPolicyAllows(cfg.OperationPolicy, config.OperationPolicyDockerRestart) && cfg.OperationKeyID != "" && cfg.OperationPublicKey != "" {
			for _, service := range services {
				if service.Kind == "docker" {
					operationCapabilities = append(operationCapabilities, client.OperationCapability{
						ActionType: "docker_restart", ServiceKind: "docker", ServiceKey: service.Key,
					})
				}
			}
		}
		report := client.Report{Hostname: host.Hostname, Version: version, Capabilities: capabilities, CollectedAt: time.Now().UTC(), Metrics: metrics, Services: services, EvidenceSources: sources, OperationCapabilities: operationCapabilities}
		if err = api.SendReport(ctx, identity.Credential, report); err != nil {
			logger.Error("report failed", "error", err)
			return
		}
		logger.Info("report accepted", "agent_id", identity.AgentID, "services", len(services))
		claim, claimErr := api.ClaimEvidence(ctx, identity.Credential)
		if claimErr != nil {
			logger.Error("evidence request poll failed", "error", claimErr)
			return
		}
		if claim.Request == nil {
			return
		}
		var selected *config.EvidenceSource
		for index := range localSources {
			if localSources[index].Key == claim.Request.SourceKey {
				selected = &localSources[index]
				break
			}
		}
		result := client.EvidenceResult{Status: "failed", CollectedAt: time.Now().UTC(), Redacted: true, Error: "source is not in local allowlist"}
		if selected != nil {
			result = collector.CollectEvidence(ctx, *selected, *claim.Request)
		}
		if completeErr := api.CompleteEvidence(ctx, identity.Credential, claim.Request.ID, result); completeErr != nil {
			logger.Error("evidence result upload failed", "request_id", claim.Request.ID, "error", completeErr)
			return
		}
		logger.Info("evidence request completed", "request_id", claim.Request.ID, "status", result.Status, "truncated", result.Truncated)
	}
	ledger, ledgerErr := operationexecutor.OpenLedger(cfg.OperationStateFile)
	if ledgerErr != nil {
		logger.Error("operation ledger initialization failed; write operations disabled", "error", ledgerErr)
	} else {
		pollOperations := func() {
			for key, pending := range ledger.Pending() {
				if err := api.CompleteOperation(ctx, identity.Credential, pending.OperationID, pending.Result); err != nil {
					logger.Error("operation result retry failed", "operation_id", pending.OperationID, "error", err)
					return
				}
				if err := ledger.MarkDelivered(key); err != nil {
					logger.Error("operation ledger delivery update failed", "operation_id", pending.OperationID, "error", err)
					return
				}
			}
			claim, err := api.ClaimOperation(ctx, identity.Credential)
			if err != nil {
				logger.Error("operation poll failed", "error", err)
				return
			}
			if claim.Task == nil {
				return
			}
			task := *claim.Task
			if err = operationexecutor.Verify(task, identity.AgentID, cfg, time.Now().UTC()); err != nil {
				exitCode := -1
				result := client.OperationResult{Status: "failed", ExitCode: &exitCode, ErrorCode: "task_rejected", ErrorDetail: err.Error(), CompletedAt: time.Now().UTC()}
				if completeErr := api.CompleteOperation(ctx, identity.Credential, task.OperationID, result); completeErr != nil {
					logger.Error("operation rejection upload failed", "operation_id", task.OperationID, "error", completeErr)
				}
				return
			}
			cached, execute, err := ledger.Prepare(task)
			if err != nil {
				logger.Error("operation ledger prepare failed", "operation_id", task.OperationID, "error", err)
				exitCode := -1
				result := client.OperationResult{Status: "failed", ExitCode: &exitCode, ErrorCode: "ledger_unavailable", ErrorDetail: "operation ledger could not safely retain the task", CompletedAt: time.Now().UTC()}
				if completeErr := api.CompleteOperation(ctx, identity.Credential, task.OperationID, result); completeErr != nil {
					logger.Error("operation ledger rejection upload failed", "operation_id", task.OperationID, "error", completeErr)
				}
				return
			}
			if err = api.StartOperation(ctx, identity.Credential, task.OperationID); err != nil {
				logger.Error("operation start acknowledgement failed", "operation_id", task.OperationID, "error", err)
				return
			}
			result := cached
			if execute {
				result = operationexecutor.ExecuteDockerRestart(ctx, task)
				if err = ledger.Complete(task.IdempotencyKey, result); err != nil {
					logger.Error("operation ledger completion failed", "operation_id", task.OperationID, "error", err)
					return
				}
			}
			if err = api.CompleteOperation(ctx, identity.Credential, task.OperationID, result); err != nil {
				logger.Error("operation result upload failed", "operation_id", task.OperationID, "error", err)
				return
			}
			if err = ledger.MarkDelivered(task.IdempotencyKey); err != nil {
				logger.Error("operation ledger delivery update failed", "operation_id", task.OperationID, "error", err)
				return
			}
			logger.Info("operation execution reported", "operation_id", task.OperationID, "status", result.Status)
		}
		go func() {
			pollOperations()
			ticker := time.NewTicker(cfg.OperationPollInterval)
			defer ticker.Stop()
			for {
				select {
				case <-ctx.Done():
					return
				case <-ticker.C:
					pollOperations()
				}
			}
		}()
	}
	send()
	ticker := time.NewTicker(cfg.ReportInterval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			logger.Info("agent stopped")
			return
		case <-ticker.C:
			send()
		}
	}
}

func loadIdentity(path string) (client.Identity, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return client.Identity{}, err
	}
	var identity client.Identity
	if err = json.Unmarshal(data, &identity); err != nil {
		return identity, err
	}
	if identity.AgentID == "" || identity.Credential == "" {
		return client.Identity{}, errors.New("agent identity is incomplete")
	}
	return identity, nil
}
func saveIdentity(path string, identity client.Identity) error {
	if identity.AgentID == "" || identity.Credential == "" {
		return errors.New("agent identity is incomplete")
	}
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	data, err := json.Marshal(identity)
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0600)
}
