package collector

import (
	"context"
	"fmt"
	"os"
	"strings"
	"testing"
)

const testDigestA = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
const testDigestB = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

func TestDeploymentCandidatesAgainstDockerWhenRequested(t *testing.T) {
	expected := os.Getenv("M42_EXPECT_DEPLOY_CANDIDATE")
	if expected == "" {
		t.Skip("set M42_EXPECT_DEPLOY_CANDIDATE for the isolated Docker integration check")
	}
	for _, candidate := range DeploymentCandidates(context.Background()) {
		if candidate.ServiceKey == expected {
			if !candidate.Eligible || candidate.Repository == "" || candidate.CurrentDigest == "" {
				t.Fatalf("expected eligible immutable candidate, got %#v", candidate)
			}
			return
		}
	}
	t.Fatalf("expected candidate %q was not discovered", expected)
}

func TestNormalizeRepositorySharedVectors(t *testing.T) {
	tests := map[string]string{
		"ubuntu:24.04":                  "docker.io/library/ubuntu",
		"library/ubuntu":                "docker.io/library/ubuntu",
		"index.docker.io/library/nginx": "docker.io/library/nginx",
		"ghcr.io/Org/App:v1":            "ghcr.io/org/app",
		"localhost:5000/team/api:tag":   "localhost:5000/team/api",
	}
	for input, want := range tests {
		got, err := normalizeRepository(input)
		if err != nil || got != want {
			t.Fatalf("normalize %q: got=%q err=%v want=%q", input, got, err, want)
		}
	}
	for _, input := range []string{"https://ghcr.io/org/app", "bad path/app", "ghcr.io//app"} {
		if got, err := normalizeRepository(input); err == nil {
			t.Fatalf("expected %q to fail, got %q", input, got)
		}
	}
}

func TestDeploymentCandidateUsesContainerThenImageInspect(t *testing.T) {
	commands := make([]string, 0, 3)
	runner := func(_ context.Context, name string, args ...string) ([]byte, error) {
		commands = append(commands, name+" "+strings.Join(args, " "))
		switch {
		case len(args) >= 2 && args[0] == "ps":
			return []byte("abc123|demo-api-1|demo|api|1\n"), nil
		case len(args) == 2 && args[0] == "inspect":
			return []byte(`[{"Id":"abc123full","Image":"sha256:image1","Config":{"Image":"ghcr.io/Org/App:v1","Healthcheck":{"Test":["CMD","true"]}}}]`), nil
		case len(args) == 3 && args[0] == "image" && args[1] == "inspect":
			return []byte(fmt.Sprintf(`[{"Id":"sha256:image1","RepoDigests":["ghcr.io/org/app@%s"]}]`, testDigestA)), nil
		default:
			return nil, fmt.Errorf("unexpected command: %s %v", name, args)
		}
	}

	candidates := collectDeploymentCandidates(context.Background(), runner)

	if len(candidates) != 1 || !candidates[0].Eligible {
		t.Fatalf("unexpected candidates: %#v", candidates)
	}
	if candidates[0].ServiceKey != "compose:demo:api:1" || candidates[0].Repository != "ghcr.io/org/app" || candidates[0].CurrentDigest != "ghcr.io/org/app@"+testDigestA {
		t.Fatalf("candidate was not canonical and stable: %#v", candidates[0])
	}
	if len(commands) != 3 || !strings.HasPrefix(commands[1], "docker inspect") || !strings.HasPrefix(commands[2], "docker image inspect") {
		t.Fatalf("expected two-step inspect, got %#v", commands)
	}
}

func TestDeploymentCandidateRejectsAmbiguousDigestAndMissingHealthcheck(t *testing.T) {
	runner := func(_ context.Context, _ string, args ...string) ([]byte, error) {
		switch {
		case args[0] == "ps":
			return []byte("abc|demo-api-1|demo|api|1\ndef|demo-worker-1|demo|worker|1\n"), nil
		case args[0] == "inspect":
			return []byte(`[
                    {"Id":"abc-full","Image":"sha256:image1","Config":{"Image":"ghcr.io/org/api:v1","Healthcheck":{"Test":["CMD","true"]}}},
                    {"Id":"def-full","Image":"sha256:image2","Config":{"Image":"ghcr.io/org/worker:v1"}}
                ]`), nil
		case args[0] == "image":
			return []byte(fmt.Sprintf(`[
                    {"Id":"sha256:image1","RepoDigests":["ghcr.io/org/api@%s","ghcr.io/org/api@%s"]},
                    {"Id":"sha256:image2","RepoDigests":["ghcr.io/org/worker@%s"]}
                ]`, testDigestA, testDigestB, testDigestA)), nil
		default:
			return nil, fmt.Errorf("unexpected args: %v", args)
		}
	}

	candidates := collectDeploymentCandidates(context.Background(), runner)

	if len(candidates) != 2 || candidates[0].ReasonCode != "digest_ambiguous" || candidates[1].ReasonCode != "healthcheck_missing" {
		t.Fatalf("unexpected rejection reasons: %#v", candidates)
	}
}

func TestDeploymentCandidateCountsReplicasBeforeReportLimit(t *testing.T) {
	var lines []string
	for index := 0; index < maxDeploymentCandidates+1; index++ {
		lines = append(lines, fmt.Sprintf("id%d|api-%d|demo|api|%d", index, index, index+1))
	}
	containers := parseComposeContainers(strings.Join(lines, "\n"))
	groups := map[string]int{}
	for _, item := range containers {
		groups[item.Project+"\x00"+item.Service]++
	}
	if groups["demo\x00api"] != maxDeploymentCandidates+1 {
		t.Fatalf("replica count was truncated: %d", groups["demo\x00api"])
	}
}
