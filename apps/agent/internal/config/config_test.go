package config

import "testing"

func TestLoadSupportsAgentMachineIDOverride(t *testing.T) {
	t.Setenv("AGENT_MACHINE_ID", "agent-installation-uuid")

	cfg := Load()

	if cfg.MachineID != "agent-installation-uuid" {
		t.Fatalf("unexpected machine id: %q", cfg.MachineID)
	}
}
