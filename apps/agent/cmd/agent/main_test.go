package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/example/vps-agent-console/apps/agent/internal/client"
)

func TestIdentityRoundTrip(t *testing.T) {
	path := filepath.Join(t.TempDir(), "nested", "identity.json")
	want := client.Identity{AgentID: "agent-01", Credential: "agt_secret"}

	if err := saveIdentity(path, want); err != nil {
		t.Fatalf("save identity: %v", err)
	}
	got, err := loadIdentity(path)
	if err != nil || got != want {
		t.Fatalf("unexpected identity: got=%#v err=%v", got, err)
	}
}

func TestLoadIdentityRejectsMalformedAndIncompleteFiles(t *testing.T) {
	for name, content := range map[string]string{
		"malformed":  "not-json",
		"empty":      "{}",
		"credential": `{"credential":"agt_secret"}`,
		"agent":      `{"agent_id":"agent-01"}`,
	} {
		t.Run(name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "identity.json")
			if err := os.WriteFile(path, []byte(content), 0600); err != nil {
				t.Fatal(err)
			}
			if _, err := loadIdentity(path); err == nil {
				t.Fatal("expected invalid identity to be rejected")
			}
		})
	}
}

func TestSaveIdentityRejectsIncompleteIdentity(t *testing.T) {
	err := saveIdentity(filepath.Join(t.TempDir(), "identity.json"), client.Identity{})
	if err == nil || !strings.Contains(err.Error(), "incomplete") {
		t.Fatalf("expected incomplete identity error, got %v", err)
	}
}
