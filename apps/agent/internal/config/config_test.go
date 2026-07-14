package config

import (
	"reflect"
	"testing"
	"time"
)

func TestLoadSupportsAgentMachineIDOverride(t *testing.T) {
	t.Setenv("AGENT_MACHINE_ID", "agent-installation-uuid")

	cfg := Load()

	if cfg.MachineID != "agent-installation-uuid" {
		t.Fatalf("unexpected machine id: %q", cfg.MachineID)
	}
}

func TestLoadUsesSafeDefaults(t *testing.T) {
	for _, key := range []string{
		"CONTROL_PLANE_URL",
		"AGENT_NAME",
		"AGENT_MACHINE_ID",
		"AGENT_REGISTRATION_TOKEN",
		"AGENT_CREDENTIAL_FILE",
		"AGENT_REPORT_INTERVAL",
		"AGENT_HEALTHCHECK_URLS",
	} {
		t.Setenv(key, "")
	}

	cfg := Load()

	if cfg.ControlPlaneURL != "http://localhost:8000" || cfg.AgentName != "VPS Agent" {
		t.Fatalf("unexpected defaults: %#v", cfg)
	}
	if cfg.ReportInterval != 30*time.Second || len(cfg.HealthcheckURLs) != 0 {
		t.Fatalf("unexpected reporting defaults: %#v", cfg)
	}
}

func TestLoadParsesIntervalAndHealthchecks(t *testing.T) {
	t.Setenv("AGENT_REPORT_INTERVAL", "45s")
	t.Setenv("AGENT_HEALTHCHECK_URLS", " https://one.example/health , ,https://two.example/ready ")

	cfg := Load()

	if cfg.ReportInterval != 45*time.Second {
		t.Fatalf("unexpected interval: %s", cfg.ReportInterval)
	}
	want := []string{"https://one.example/health", "https://two.example/ready"}
	if !reflect.DeepEqual(cfg.HealthcheckURLs, want) {
		t.Fatalf("unexpected healthchecks: %#v", cfg.HealthcheckURLs)
	}
}

func TestLoadRejectsInvalidAndNonPositiveIntervals(t *testing.T) {
	for _, value := range []string{"invalid", "0s", "-5s"} {
		t.Run(value, func(t *testing.T) {
			t.Setenv("AGENT_REPORT_INTERVAL", value)
			if got := Load().ReportInterval; got != 30*time.Second {
				t.Fatalf("expected fallback interval, got %s", got)
			}
		})
	}
}
