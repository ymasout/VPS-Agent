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
)

var version = "0.2.3-dev"

var capabilities = []string{"host.metrics", "docker.status", "systemd.status", "http.healthcheck"}

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
		report := client.Report{Hostname: host.Hostname, Version: version, Capabilities: capabilities, CollectedAt: time.Now().UTC(), Metrics: metrics, Services: services}
		if err = api.SendReport(ctx, identity.Credential, report); err != nil {
			logger.Error("report failed", "error", err)
			return
		}
		logger.Info("report accepted", "agent_id", identity.AgentID, "services", len(services))
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
	return identity, nil
}
func saveIdentity(path string, identity client.Identity) error {
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	data, err := json.Marshal(identity)
	if err != nil {
		return err
	}
	return os.WriteFile(path, data, 0600)
}
