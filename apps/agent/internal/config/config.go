package config

import (
	"os"
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
}

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
	}
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
