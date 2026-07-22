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

func TestLoadParsesOnlyValidEvidenceAllowlistEntries(t *testing.T) {
	t.Setenv("AGENT_EVIDENCE_SOURCES_JSON", `[
		{"key":"api-logs","kind":"docker_logs","target":"api","display_name":"API logs"},
		{"key":"api-logs","kind":"docker_logs","target":"duplicate"},
		{"key":"bad key","kind":"docker_logs","target":"bad"},
		{"key":"api-journal","kind":"systemd_journal","target":"api.service"},
		{"key":"bad-journal","kind":"systemd_journal","target":"--system.service"},
		{"key":"shell","kind":"shell","target":"whoami"}
	]`)

	sources := Load().EvidenceSources

	if len(sources) != 2 || sources[0].Key != "api-logs" || sources[1].Key != "api-journal" {
		t.Fatalf("unexpected evidence sources: %#v", sources)
	}
}

func TestLoadRejectsMalformedEvidenceAllowlist(t *testing.T) {
	t.Setenv("AGENT_EVIDENCE_SOURCES_JSON", `not-json`)
	if sources := Load().EvidenceSources; len(sources) != 0 {
		t.Fatalf("malformed allowlist should be empty: %#v", sources)
	}
}

func TestEvidencePolicyRequiresExplicitDockerLogsOptIn(t *testing.T) {
	t.Setenv("AGENT_EVIDENCE_POLICY", "docker_logs")
	if policy := Load().EvidencePolicy; policy != EvidencePolicyDockerLogs {
		t.Fatalf("unexpected policy: %q", policy)
	}
	t.Setenv("AGENT_EVIDENCE_POLICY", "anything-else")
	if policy := Load().EvidencePolicy; policy != "disabled" {
		t.Fatalf("unknown policy must be disabled: %q", policy)
	}
}

func TestEvidencePolicySupportsExplicitCombinedReadOnlySources(t *testing.T) {
	t.Setenv("AGENT_EVIDENCE_POLICY", "systemd_journal,docker_logs")
	policy := Load().EvidencePolicy
	if policy != "docker_logs,systemd_journal" {
		t.Fatalf("unexpected canonical policy: %q", policy)
	}
	if !EvidencePolicyAllows(policy, EvidencePolicyDockerLogs) ||
		!EvidencePolicyAllows(policy, EvidencePolicySystemdJournal) {
		t.Fatalf("combined policy did not enable both capabilities: %q", policy)
	}
	t.Setenv("AGENT_EVIDENCE_POLICY", "docker_logs,unknown")
	if policy := Load().EvidencePolicy; policy != "disabled" {
		t.Fatalf("unknown combined policy must fail closed: %q", policy)
	}
}

func TestDeployPolicyRequiresExplicitPlanOnlyOptIn(t *testing.T) {
	t.Setenv("AGENT_DEPLOY_POLICY", "plan_only")
	if policy := Load().DeployPolicy; policy != DeployPolicyPlanOnly {
		t.Fatalf("unexpected deploy policy: %q", policy)
	}
	if !DeployPolicyAllows(Load().DeployPolicy, DeployPolicyPlanOnly) {
		t.Fatal("plan-only discovery was not enabled")
	}
	t.Setenv("AGENT_DEPLOY_POLICY", "docker_compose_deploy")
	if policy := Load().DeployPolicy; policy != "disabled" {
		t.Fatalf("M4.2a must reject executable deploy policy, got %q", policy)
	}
}
