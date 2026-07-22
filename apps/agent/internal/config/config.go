package config

import (
	"encoding/json"
	"os"
	"regexp"
	"strings"
	"time"
)

type Config struct {
	ControlPlaneURL       string
	AgentName             string
	MachineID             string
	RegistrationToken     string
	CredentialFile        string
	ReportInterval        time.Duration
	HealthcheckURLs       []string
	EvidenceSources       []EvidenceSource
	EvidencePolicy        string
	OperationPolicy       string
	OperationKeyID        string
	OperationPublicKey    string
	OperationStateFile    string
	OperationPollInterval time.Duration
	DeployPolicy          string
}

type EvidenceSource struct {
	Key         string `json:"key"`
	Kind        string `json:"kind"`
	Target      string `json:"target"`
	DisplayName string `json:"display_name"`
	ServiceKind string `json:"-"`
	ServiceKey  string `json:"-"`
}

const EvidencePolicyDockerLogs = "docker_logs"
const EvidencePolicySystemdJournal = "systemd_journal"

var sourceKeyPattern = regexp.MustCompile(`^[a-zA-Z0-9._-]+$`)
var systemdUnitPattern = regexp.MustCompile(`^[a-zA-Z0-9_.@:-]+\.service$`)

func Load() Config {
	interval := durationOrDefault("AGENT_REPORT_INTERVAL", 30*time.Second)
	return Config{
		ControlPlaneURL:       valueOrDefault("CONTROL_PLANE_URL", "http://localhost:8000"),
		AgentName:             valueOrDefault("AGENT_NAME", "VPS Agent"),
		MachineID:             os.Getenv("AGENT_MACHINE_ID"),
		RegistrationToken:     os.Getenv("AGENT_REGISTRATION_TOKEN"),
		CredentialFile:        valueOrDefault("AGENT_CREDENTIAL_FILE", "/var/lib/vps-agent/identity.json"),
		ReportInterval:        interval,
		HealthcheckURLs:       splitList(os.Getenv("AGENT_HEALTHCHECK_URLS")),
		EvidenceSources:       parseEvidenceSources(os.Getenv("AGENT_EVIDENCE_SOURCES_JSON")),
		EvidencePolicy:        evidencePolicy(os.Getenv("AGENT_EVIDENCE_POLICY")),
		OperationPolicy:       operationPolicy(os.Getenv("AGENT_OPERATION_POLICY")),
		OperationKeyID:        os.Getenv("AGENT_OPERATION_KEY_ID"),
		OperationPublicKey:    os.Getenv("AGENT_OPERATION_PUBLIC_KEY_BASE64"),
		OperationStateFile:    valueOrDefault("AGENT_OPERATION_STATE_FILE", "/var/lib/vps-agent/operations.json"),
		OperationPollInterval: durationOrDefault("AGENT_OPERATION_POLL_INTERVAL", 5*time.Second),
		DeployPolicy:          deployPolicy(os.Getenv("AGENT_DEPLOY_POLICY")),
	}
}

const OperationPolicyDockerRestart = "docker_restart"
const DeployPolicyPlanOnly = "plan_only"

func operationPolicy(value string) string {
	if strings.TrimSpace(value) == OperationPolicyDockerRestart {
		return OperationPolicyDockerRestart
	}
	return "disabled"
}

func OperationPolicyAllows(policy, capability string) bool {
	return policy == capability
}

func deployPolicy(value string) string {
	if strings.TrimSpace(value) == DeployPolicyPlanOnly {
		return DeployPolicyPlanOnly
	}
	return "disabled"
}

func DeployPolicyAllows(policy, capability string) bool {
	return policy == capability
}

func evidencePolicy(value string) string {
	requested := map[string]bool{}
	for _, item := range strings.Split(value, ",") {
		item = strings.TrimSpace(item)
		if item == "" || item == "disabled" {
			continue
		}
		if item != EvidencePolicyDockerLogs && item != EvidencePolicySystemdJournal {
			return "disabled"
		}
		requested[item] = true
	}
	policies := make([]string, 0, 2)
	for _, item := range []string{EvidencePolicyDockerLogs, EvidencePolicySystemdJournal} {
		if requested[item] {
			policies = append(policies, item)
		}
	}
	if len(policies) == 0 {
		return "disabled"
	}
	return strings.Join(policies, ",")
}

func EvidencePolicyAllows(policy, capability string) bool {
	for _, item := range strings.Split(policy, ",") {
		if item == capability {
			return true
		}
	}
	return false
}

func parseEvidenceSources(value string) []EvidenceSource {
	if strings.TrimSpace(value) == "" {
		return nil
	}
	var sources []EvidenceSource
	if err := json.Unmarshal([]byte(value), &sources); err != nil {
		return nil
	}
	result := make([]EvidenceSource, 0, len(sources))
	seen := map[string]bool{}
	for _, source := range sources {
		validTarget := source.Kind == "docker_logs" && strings.TrimSpace(source.Target) != ""
		if source.Kind == "systemd_journal" {
			validTarget = !strings.HasPrefix(source.Target, "-") && systemdUnitPattern.MatchString(source.Target)
		}
		if !sourceKeyPattern.MatchString(source.Key) || !validTarget || seen[source.Key] {
			continue
		}
		if source.DisplayName == "" {
			source.DisplayName = source.Key
		}
		seen[source.Key] = true
		result = append(result, source)
	}
	return result
}

func splitList(value string) []string {
	var result []string
	for _, item := range strings.Split(value, ",") {
		if item = strings.TrimSpace(item); item != "" {
			result = append(result, item)
		}
	}
	return result
}

func durationOrDefault(key string, fallback time.Duration) time.Duration {
	if value := os.Getenv(key); value != "" {
		if parsed, err := time.ParseDuration(value); err == nil && parsed > 0 {
			return parsed
		}
	}
	return fallback
}

func valueOrDefault(key, fallback string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return fallback
}
