package client

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

type Client struct {
	baseURL string
	http    *http.Client
}

type RegisterRequest struct {
	Token        string   `json:"token"`
	Name         string   `json:"name"`
	Hostname     string   `json:"hostname"`
	MachineID    string   `json:"machine_id"`
	OS           string   `json:"os"`
	Arch         string   `json:"arch"`
	Version      string   `json:"version"`
	Capabilities []string `json:"capabilities"`
}

type Identity struct {
	AgentID    string `json:"agent_id"`
	Credential string `json:"credential"`
}
type DiskMetric struct {
	Path        string  `json:"path"`
	UsedBytes   float64 `json:"used_bytes"`
	TotalBytes  float64 `json:"total_bytes"`
	UsedPercent float64 `json:"used_percent"`
}
type Metrics struct {
	CPUPercent       float64      `json:"cpu_percent"`
	MemoryPercent    float64      `json:"memory_percent"`
	MemoryUsedBytes  float64      `json:"memory_used_bytes"`
	MemoryTotalBytes float64      `json:"memory_total_bytes"`
	Disks            []DiskMetric `json:"disks"`
}
type Service struct {
	Kind    string `json:"kind"`
	Key     string `json:"key"`
	Name    string `json:"name"`
	State   string `json:"state"`
	Detail  string `json:"detail,omitempty"`
	Healthy *bool  `json:"healthy,omitempty"`
}
type Report struct {
	Hostname        string           `json:"hostname"`
	Version         string           `json:"version"`
	Capabilities    []string         `json:"capabilities"`
	CollectedAt     time.Time        `json:"collected_at"`
	Metrics         Metrics          `json:"metrics"`
	Services        []Service        `json:"services"`
	EvidenceSources []EvidenceSource `json:"evidence_sources"`
}

type EvidenceSource struct {
	Key         string `json:"key"`
	Kind        string `json:"kind"`
	DisplayName string `json:"display_name"`
}

type EvidenceRequest struct {
	ID             string    `json:"id"`
	SourceKey      string    `json:"source_key"`
	SinceAt        time.Time `json:"since_at"`
	UntilAt        time.Time `json:"until_at"`
	MaxLines       int       `json:"max_lines"`
	MaxBytes       int       `json:"max_bytes"`
	TimeoutSeconds int       `json:"timeout_seconds"`
}

type EvidenceClaim struct {
	Request *EvidenceRequest `json:"request"`
}

type EvidenceResult struct {
	Status      string    `json:"status"`
	Content     string    `json:"content"`
	CollectedAt time.Time `json:"collected_at"`
	Redacted    bool      `json:"redacted"`
	Truncated   bool      `json:"truncated"`
	Error       string    `json:"error,omitempty"`
}

func New(baseURL string) *Client {
	return &Client{strings.TrimRight(baseURL, "/"), &http.Client{Timeout: 15 * time.Second}}
}

func (c *Client) Register(ctx context.Context, payload RegisterRequest) (Identity, error) {
	var identity Identity
	if err := c.request(ctx, http.MethodPost, "/api/v1/agents/register", "", payload, &identity); err != nil {
		return identity, err
	}
	return identity, nil
}

func (c *Client) SendReport(ctx context.Context, credential string, payload Report) error {
	return c.request(ctx, http.MethodPost, "/api/v1/agents/report", credential, payload, nil)
}

func (c *Client) ClaimEvidence(ctx context.Context, credential string) (EvidenceClaim, error) {
	var claim EvidenceClaim
	err := c.request(ctx, http.MethodGet, "/api/v1/agents/evidence-requests/next", credential, nil, &claim)
	return claim, err
}

func (c *Client) CompleteEvidence(ctx context.Context, credential, requestID string, payload EvidenceResult) error {
	return c.request(ctx, http.MethodPost, "/api/v1/agents/evidence-requests/"+requestID+"/complete", credential, payload, nil)
}

func (c *Client) request(ctx context.Context, method, path, credential string, input, output any) error {
	var body io.Reader
	if input != nil {
		encoded, err := json.Marshal(input)
		if err != nil {
			return fmt.Errorf("marshal request: %w", err)
		}
		body = bytes.NewReader(encoded)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, body)
	if err != nil {
		return fmt.Errorf("create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")
	if credential != "" {
		req.Header.Set("Authorization", "Bearer "+credential)
	}
	res, err := c.http.Do(req)
	if err != nil {
		return fmt.Errorf("send request: %w", err)
	}
	defer res.Body.Close()
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		data, _ := io.ReadAll(io.LimitReader(res.Body, 1024))
		return fmt.Errorf("request returned %s: %s", res.Status, strings.TrimSpace(string(data)))
	}
	if output != nil {
		if err := json.NewDecoder(res.Body).Decode(output); err != nil {
			return fmt.Errorf("decode response: %w", err)
		}
	}
	return nil
}
