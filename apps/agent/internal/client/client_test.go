package client

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestRegisterSendsExpectedRequestAndDecodesIdentity(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost || r.URL.Path != "/api/v1/agents/register" {
			t.Fatalf("unexpected request: %s %s", r.Method, r.URL.Path)
		}
		if r.Header.Get("Content-Type") != "application/json" || r.Header.Get("Authorization") != "" {
			t.Fatalf("unexpected headers: %#v", r.Header)
		}
		var payload RegisterRequest
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Fatalf("decode request: %v", err)
		}
		if payload.Token != "reg_example_token" || payload.MachineID != "machine-01" {
			t.Fatalf("unexpected payload: %#v", payload)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"agent_id":"agent-01","credential":"agt_secret"}`))
	}))
	defer server.Close()

	identity, err := New(server.URL+"/").Register(context.Background(), RegisterRequest{
		Token: "reg_example_token", MachineID: "machine-01",
	})

	if err != nil || identity.AgentID != "agent-01" || identity.Credential != "agt_secret" {
		t.Fatalf("unexpected result: identity=%#v err=%v", identity, err)
	}
}

func TestSendReportUsesBearerCredential(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v1/agents/report" || r.Header.Get("Authorization") != "Bearer agt_secret" {
			t.Fatalf("unexpected report request: path=%s auth=%q", r.URL.Path, r.Header.Get("Authorization"))
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	err := New(server.URL).SendReport(context.Background(), "agt_secret", Report{})
	if err != nil {
		t.Fatalf("send report: %v", err)
	}
}

func TestRequestReturnsBoundedServerError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadGateway)
		_, _ = w.Write([]byte(strings.Repeat("failure", 400)))
	}))
	defer server.Close()

	err := New(server.URL).SendReport(context.Background(), "agt_secret", Report{})

	if err == nil || !strings.Contains(err.Error(), "502 Bad Gateway") {
		t.Fatalf("expected status error, got %v", err)
	}
	if len(err.Error()) > 1200 {
		t.Fatalf("server error was not bounded: %d bytes", len(err.Error()))
	}
}

func TestRegisterRejectsMalformedSuccessResponse(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("not-json"))
	}))
	defer server.Close()

	_, err := New(server.URL).Register(context.Background(), RegisterRequest{})
	if err == nil || !strings.Contains(err.Error(), "decode response") {
		t.Fatalf("expected decode error, got %v", err)
	}
}

func TestRequestHonorsContextCancellation(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(50 * time.Millisecond)
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	err := New(server.URL).SendReport(ctx, "agt_secret", Report{})
	if err == nil || !strings.Contains(err.Error(), "send request") {
		t.Fatalf("expected cancelled request error, got %v", err)
	}
}

func TestEvidencePollingAndCompletionUseOutboundAuthenticatedRequests(t *testing.T) {
	var completed EvidenceResult
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer agt_secret" {
			t.Fatalf("missing agent credential: %q", r.Header.Get("Authorization"))
		}
		switch r.URL.Path {
		case "/api/v1/agents/evidence-requests/next":
			_, _ = w.Write([]byte(`{"request":{"id":"request-1","source_key":"api-logs","since_at":"2026-07-17T00:00:00Z","until_at":"2026-07-17T00:05:00Z","max_lines":100,"max_bytes":4096,"timeout_seconds":5}}`))
		case "/api/v1/agents/evidence-requests/request-1/complete":
			if err := json.NewDecoder(r.Body).Decode(&completed); err != nil {
				t.Fatal(err)
			}
		default:
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
	}))
	defer server.Close()

	api := New(server.URL)
	claim, err := api.ClaimEvidence(context.Background(), "agt_secret")
	if err != nil || claim.Request == nil || claim.Request.SourceKey != "api-logs" {
		t.Fatalf("unexpected claim: %#v err=%v", claim, err)
	}
	want := EvidenceResult{Status: "completed", Content: "bounded", CollectedAt: time.Now().UTC(), Redacted: true}
	if err = api.CompleteEvidence(context.Background(), "agt_secret", claim.Request.ID, want); err != nil {
		t.Fatal(err)
	}
	if completed.Content != "bounded" || !completed.Redacted {
		t.Fatalf("unexpected completion: %#v", completed)
	}
}
