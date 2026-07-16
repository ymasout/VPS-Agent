package collector

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/example/vps-agent-console/apps/agent/internal/client"
	"github.com/example/vps-agent-console/apps/agent/internal/config"
)

func TestParseSystemdServicesUsesActiveState(t *testing.T) {
	services := parseSystemdServices(`ssh.service loaded active running OpenBSD Secure Shell server
cron.service loaded inactive dead Regular background program processing daemon
broken.service loaded failed failed Broken service`)

	if len(services) != 3 {
		t.Fatalf("expected 3 services, got %d", len(services))
	}
	if services[0].State != "active" || services[0].Detail != "running · OpenBSD Secure Shell server" {
		t.Fatalf("unexpected active service: %#v", services[0])
	}
	if services[0].Healthy == nil || !*services[0].Healthy {
		t.Fatal("active service should be healthy")
	}
	if services[1].State != "inactive" || services[1].Healthy != nil {
		t.Fatalf("inactive service should be neutral: %#v", services[1])
	}
	if services[2].State != "failed" || services[2].Healthy == nil || *services[2].Healthy {
		t.Fatalf("failed service should be unhealthy: %#v", services[2])
	}
}

func TestParseSystemdServicesSkipsIncompleteLines(t *testing.T) {
	services := parseSystemdServices("invalid\nssh.service loaded active running SSH server\n")

	if len(services) != 1 || services[0].Key != "ssh.service" {
		t.Fatalf("unexpected services: %#v", services)
	}
}

func TestParseDockerServicesPreservesStatusDetail(t *testing.T) {
	services := parseDockerServices("abc|web|running|Up 2 hours (healthy)\ndef|worker|exited|Exited (1) 3 minutes ago\nmalformed")

	if len(services) != 2 {
		t.Fatalf("expected 2 services, got %d", len(services))
	}
	if services[0].Healthy == nil || !*services[0].Healthy || services[0].Detail != "Up 2 hours (healthy)" {
		t.Fatalf("unexpected running service: %#v", services[0])
	}
	if services[1].Healthy == nil || *services[1].Healthy || services[1].State != "exited" {
		t.Fatalf("unexpected exited service: %#v", services[1])
	}
}

func TestHTTPHealthchecksClassifiesResponsesAndInvalidURLs(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/redirect" {
			http.Redirect(w, r, "/ready", http.StatusTemporaryRedirect)
			return
		}
		if r.URL.Path == "/ready" {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer server.Close()

	services := HTTPHealthchecks(context.Background(), []string{
		server.URL + "/ready",
		server.URL + "/failed",
		server.URL + "/redirect",
		"://invalid",
	})

	if len(services) != 4 {
		t.Fatalf("expected 4 services, got %d", len(services))
	}
	if services[0].Healthy == nil || !*services[0].Healthy || services[0].State != "healthy" {
		t.Fatalf("unexpected healthy response: %#v", services[0])
	}
	if services[1].Healthy == nil || *services[1].Healthy || services[1].Detail != "503 Service Unavailable" {
		t.Fatalf("unexpected failed response: %#v", services[1])
	}
	if services[2].Healthy == nil || !*services[2].Healthy {
		t.Fatalf("redirect should resolve to a healthy response: %#v", services[2])
	}
	if services[3].Healthy == nil || *services[3].Healthy || services[3].Detail == "" {
		t.Fatalf("invalid URL should be unhealthy: %#v", services[3])
	}
}

func TestHTTPHealthchecksHonorsCancelledContext(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	services := HTTPHealthchecks(ctx, []string{"http://127.0.0.1/healthz"})

	if len(services) != 1 || services[0].Healthy == nil || *services[0].Healthy {
		t.Fatalf("cancelled request should be unhealthy: %#v", services)
	}
}

func TestEvidenceRedactionMasksSecretsBeforeUpload(t *testing.T) {
	value := "Authorization: Bearer live-token password=secret-value"
	redacted := redactEvidence(value)

	if redacted == value || containsAny(redacted, "live-token", "secret-value") || !strings.Contains(redacted, "[REDACTED]") {
		t.Fatalf("secret was not redacted: %q", redacted)
	}
}

func TestDockerLogArgsSeparateTargetFromOptions(t *testing.T) {
	request := client.EvidenceRequest{
		SinceAt: time.Date(2026, 7, 17, 0, 0, 0, 0, time.UTC),
		UntilAt: time.Date(2026, 7, 17, 0, 5, 0, 0, time.UTC),
	}
	args := dockerLogArgs(
		config.EvidenceSource{Kind: "docker_logs", Target: "--malicious-looking-target"},
		request,
		200,
	)

	if len(args) < 2 || args[len(args)-2] != "--" || args[len(args)-1] != "--malicious-looking-target" {
		t.Fatalf("target is not separated from options: %#v", args)
	}
}

func TestBoundedEvidenceBufferDiscardsExcessBytes(t *testing.T) {
	buffer := &boundedBuffer{limit: 5}
	written, err := buffer.Write([]byte("123456789"))

	if err != nil || written != 9 || buffer.String() != "12345" || !buffer.truncated {
		t.Fatalf("unexpected bounded buffer: written=%d value=%q truncated=%v err=%v", written, buffer.String(), buffer.truncated, err)
	}
}

func containsAny(value string, needles ...string) bool {
	for _, needle := range needles {
		if strings.Contains(value, needle) {
			return true
		}
	}
	return false
}
