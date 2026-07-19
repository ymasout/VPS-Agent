package collector

import (
	"bytes"
	"context"
	"fmt"
	"os/exec"
	"regexp"
	"strconv"
	"time"

	"github.com/example/vps-agent-console/apps/agent/internal/client"
	"github.com/example/vps-agent-console/apps/agent/internal/config"
)

const (
	maxEvidenceLines   = 500
	maxEvidenceBytes   = 65536
	maxEvidenceTimeout = 15 * time.Second
)

var evidenceRedactionRules = []*regexp.Regexp{
	regexp.MustCompile(`(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s,;]+`),
	regexp.MustCompile(`(?i)((?:password|passwd|token|secret|api[_-]?key|cookie|webhook)\s*[:=]\s*)[^\s,;]+`),
	regexp.MustCompile(`(?s)-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----.*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----`),
}

func CollectEvidence(ctx context.Context, source config.EvidenceSource, request client.EvidenceRequest) client.EvidenceResult {
	result := client.EvidenceResult{Status: "failed", CollectedAt: time.Now().UTC(), Redacted: true}
	if source.Kind != "docker_logs" && source.Kind != "systemd_journal" {
		result.Error = "unsupported evidence source kind"
		return result
	}
	lines := request.MaxLines
	if lines <= 0 || lines > maxEvidenceLines {
		lines = maxEvidenceLines
	}
	maxBytes := request.MaxBytes
	if maxBytes <= 0 || maxBytes > maxEvidenceBytes {
		maxBytes = maxEvidenceBytes
	}
	timeout := time.Duration(request.TimeoutSeconds) * time.Second
	if timeout <= 0 || timeout > maxEvidenceTimeout {
		timeout = maxEvidenceTimeout
	}
	collectCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	commandName := "docker"
	commandArgs := dockerLogArgs(source, request, lines)
	failureLabel := "docker log"
	if source.Kind == "systemd_journal" {
		commandName = "journalctl"
		commandArgs = systemdJournalArgs(source, request, lines)
		failureLabel = "systemd journal"
	}
	command := exec.CommandContext(collectCtx, commandName, commandArgs...)
	buffer := &boundedBuffer{limit: maxBytes}
	command.Stdout = buffer
	command.Stderr = buffer
	if err := command.Run(); err != nil {
		result.Error = fmt.Sprintf("%s collection failed: %v", failureLabel, err)
		return result
	}
	result.Status = "completed"
	result.Content = redactEvidence(buffer.String())
	result.Truncated = buffer.truncated
	return result
}

func systemdJournalArgs(
	source config.EvidenceSource, request client.EvidenceRequest, lines int,
) []string {
	// 旧版 systemd 的 journalctl 无法解析 RFC3339 的 "T...Z" 格式
	// （报 "Failed to parse timestamp"），改用空格分隔 + UTC 缩写以兼容更广的 systemd。
	return []string{
		"--unit", source.Target,
		"--since", request.SinceAt.UTC().Format("2006-01-02 15:04:05 MST"),
		"--until", request.UntilAt.UTC().Format("2006-01-02 15:04:05 MST"),
		"--lines", strconv.Itoa(lines),
		"--output=short-iso", "--no-pager",
	}
}

func dockerLogArgs(
	source config.EvidenceSource, request client.EvidenceRequest, lines int,
) []string {
	return []string{
		"logs",
		"--since", request.SinceAt.UTC().Format(time.RFC3339),
		"--until", request.UntilAt.UTC().Format(time.RFC3339),
		"--tail", strconv.Itoa(lines),
		"--", source.Target,
	}
}

type boundedBuffer struct {
	bytes.Buffer
	limit     int
	truncated bool
}

func (buffer *boundedBuffer) Write(value []byte) (int, error) {
	originalLength := len(value)
	remaining := buffer.limit - buffer.Len()
	if remaining <= 0 {
		buffer.truncated = buffer.truncated || originalLength > 0
		return originalLength, nil
	}
	if len(value) > remaining {
		value = value[:remaining]
		buffer.truncated = true
	}
	_, _ = buffer.Buffer.Write(value)
	return originalLength, nil
}

func redactEvidence(value string) string {
	redacted := value
	for _, rule := range evidenceRedactionRules {
		redacted = rule.ReplaceAllStringFunc(redacted, func(match string) string {
			parts := rule.FindStringSubmatch(match)
			if len(parts) > 1 {
				return parts[1] + "[REDACTED]"
			}
			return "[REDACTED]"
		})
	}
	return redacted
}
