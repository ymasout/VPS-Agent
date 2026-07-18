package config

import (
	"encoding/json"
	"os"
	"regexp"
	"strings"
	"time"
)

type Config struct {
	ControlPlaneURL   string
	AgentName         string
	MachineID         string
	RegistrationToken string
	CredentialFile    string
	ReportInterval    time.Duration
	HealthcheckURLs   []string
	EvidenceSources   []EvidenceSource
	EvidencePolicy    string
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

var sourceKeyPattern = regexp.MustCompile(`^[a-zA-Z0-9._-]+$`)

func Load() Config {
	interval := durationOrDefault("AGENT_REPORT_INTERVAL", 30*time.Second)
	return Config{
		ControlPlaneURL:   valueOrDefault("CONTROL_PLANE_URL", "http://localhost:8000"),
		AgentName:         valueOrDefault("AGENT_NAME", "VPS Agent"),
		MachineID:         os.Getenv("AGENT_MACHINE_ID"),
		RegistrationToken: os.Getenv("AGENT_REGISTRATION_TOKEN"),
		CredentialFile:    valueOrDefault("AGENT_CREDENTIAL_FILE", "/var/lib/vps-agent/identity.json"),
		ReportInterval:    interval,
		HealthcheckURLs:   splitList(os.Getenv("AGENT_HEALTHCHECK_URLS")),
		EvidenceSources:   parseEvidenceSources(os.Getenv("AGENT_EVIDENCE_SOURCES_JSON")),
		EvidencePolicy:    evidencePolicy(os.Getenv("AGENT_EVIDENCE_POLICY")),
	}
}

func evidencePolicy(value string) string {
	if strings.TrimSpace(value) == EvidencePolicyDockerLogs {
		return EvidencePolicyDockerLogs
	}
	return "disabled"
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
		if !sourceKeyPattern.MatchString(source.Key) || source.Kind != "docker_logs" ||
			strings.TrimSpace(source.Target) == "" || seen[source.Key] {
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
