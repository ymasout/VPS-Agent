package operation

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/example/vps-agent-console/apps/agent/internal/client"
	"github.com/example/vps-agent-console/apps/agent/internal/config"
)

const testDigestA = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
const testDigestB = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"

type fakeDeployDocker struct {
	configFile       string
	workingDir       string
	configHash       string
	configFilesLabel string
	upArgs           []string
	replicas         int
}

func (fake *fakeDeployDocker) run(_ context.Context, name string, args ...string) ([]byte, error) {
	if name != "docker" {
		return nil, os.ErrInvalid
	}
	joined := strings.Join(args, "\x00")
	switch {
	case len(args) > 0 && args[0] == "ps":
		output := "abc123|demo-api-1|demo|api|1\n"
		if fake.replicas > 1 {
			output += "def456|demo-api-2|demo|api|2\n"
		}
		return []byte(output), nil
	case len(args) > 0 && args[0] == "inspect":
		value := []deploymentContainerInspect{{ID: "abc123-full", Name: "/demo-api-1", Image: "sha256:image"}}
		value[0].Config.Image = "ghcr.io/org/app:stable"
		value[0].Config.Labels = map[string]string{
			"com.docker.compose.project":              "demo",
			"com.docker.compose.service":              "api",
			"com.docker.compose.project.config_files": fake.configFiles(),
			"com.docker.compose.project.working_dir":  fake.workingDir,
			"com.docker.compose.config-hash":          fake.configHash,
			"com.docker.compose.container-number":     "1",
		}
		return json.Marshal(value)
	case len(args) > 1 && args[0] == "image" && args[1] == "inspect":
		return json.Marshal([]deploymentImageInspect{{
			ID: "sha256:image", RepoDigests: []string{"ghcr.io/org/app@" + testDigestA},
		}})
	case strings.Contains(joined, "\x00config\x00--hash\x00api"):
		fileCount := 0
		for _, value := range args {
			if value == "-f" {
				fileCount++
			}
		}
		if fileCount == 1 {
			return []byte("api " + strings.Repeat("a", 64) + "\n"), nil
		}
		return []byte("api " + strings.Repeat("b", 64) + "\n"), nil
	case len(args) > 0 && args[0] == "pull":
		return nil, nil
	case strings.Contains(joined, "\x00up\x00"):
		fake.upArgs = append([]string{}, args...)
		return nil, nil
	default:
		return nil, os.ErrInvalid
	}
}

func (fake *fakeDeployDocker) configFiles() string {
	if fake.configFilesLabel != "" {
		return fake.configFilesLabel
	}
	return fake.configFile
}

func deployTestConfig(t *testing.T) (config.Config, *fakeDeployDocker) {
	t.Helper()
	root := t.TempDir()
	composeFile := filepath.Join(root, "compose.yaml")
	if err := os.WriteFile(composeFile, []byte("services: {}\n"), 0600); err != nil {
		t.Fatal(err)
	}
	fake := &fakeDeployDocker{
		configFile: composeFile,
		workingDir: root,
		configHash: strings.Repeat("a", 64),
	}
	cfg := config.Config{
		OperationStateFile: filepath.Join(root, "agent-state", "operations.json"),
		DeployAllowedRoots: []string{root},
	}
	return cfg, fake
}

func TestComposePreflightAcceptsOriginalAndCurrentDigestBaselines(t *testing.T) {
	cfg, fake := deployTestConfig(t)
	key := "compose:demo:api:1"
	if code := canDeploy(context.Background(), key, "ghcr.io/org/app@"+testDigestA, cfg, fake.run); code != "" {
		t.Fatalf("original baseline rejected: %s", code)
	}
	fake.configHash = strings.Repeat("b", 64)
	if code := canDeploy(context.Background(), key, "ghcr.io/org/app@"+testDigestA, cfg, fake.run); code != "" {
		t.Fatalf("current-digest baseline rejected: %s", code)
	}
}

func TestComposePreflightRejectsConfigDriftAndUntrustedPath(t *testing.T) {
	cfg, fake := deployTestConfig(t)
	fake.configHash = strings.Repeat("c", 64)
	if code := canDeploy(context.Background(), "compose:demo:api:1", "ghcr.io/org/app@"+testDigestA, cfg, fake.run); code != "compose_config_drift" {
		t.Fatalf("unexpected drift result: %s", code)
	}
	fake.configHash = strings.Repeat("a", 64)
	cfg.DeployAllowedRoots = []string{t.TempDir()}
	if code := canDeploy(context.Background(), "compose:demo:api:1", "ghcr.io/org/app@"+testDigestA, cfg, fake.run); code != "compose_path_untrusted" {
		t.Fatalf("unexpected path result: %s", code)
	}
}

func TestComposePreflightRejectsReplicaDrift(t *testing.T) {
	cfg, fake := deployTestConfig(t)
	fake.replicas = 2
	if code := canDeploy(context.Background(), "compose:demo:api:1", "ghcr.io/org/app@"+testDigestA, cfg, fake.run); code != "drift_rejected" {
		t.Fatalf("unexpected replica drift result: %s", code)
	}
}

func TestComposePreflightReconstructsOriginalFilesAfterAgentDeploy(t *testing.T) {
	cfg, fake := deployTestConfig(t)
	staleOverride := filepath.Join(
		filepath.Dir(cfg.OperationStateFile), "deploy-previous", "image-target.yaml",
	)
	fake.configFilesLabel = fake.configFile + "," + staleOverride
	if code := canDeploy(context.Background(), "compose:demo:api:1", "ghcr.io/org/app@"+testDigestA, cfg, fake.run); code != "" {
		t.Fatalf("Agent-owned stale override was not reconstructed: %s", code)
	}

	fake.configFilesLabel = fake.configFile + "," + filepath.Join(filepath.Dir(cfg.OperationStateFile), "unknown.yaml")
	if code := canDeploy(context.Background(), "compose:demo:api:1", "ghcr.io/org/app@"+testDigestA, cfg, fake.run); code != "compose_path_untrusted" {
		t.Fatalf("unknown extra config file was not rejected: %s", code)
	}
}

func TestComposeDeployUsesOnlyFixedSingleServiceArguments(t *testing.T) {
	cfg, fake := deployTestConfig(t)
	result := executeDockerComposeDeploy(
		context.Background(),
		client.OperationTask{
			ServiceKey:    "compose:demo:api:1",
			CurrentDigest: "ghcr.io/org/app@" + testDigestA,
			TargetDigest:  "ghcr.io/org/app@" + testDigestB,
		},
		cfg,
		fake.run,
	)
	if result.Status != "completed" || result.ExitCode == nil || *result.ExitCode != 0 {
		t.Fatalf("unexpected deployment result: %#v", result)
	}
	joined := strings.Join(fake.upArgs, " ")
	for _, required := range []string{
		"--project-name demo", "--no-deps", "--no-build", "--pull never",
		"--force-recreate", "--scale api=1 api",
	} {
		if !strings.Contains(joined, required) {
			t.Fatalf("missing fixed argument %q in %q", required, joined)
		}
	}
	if strings.Contains(joined, "ghcr.io/org/app@"+testDigestA) || strings.Contains(joined, "ghcr.io/org/app@"+testDigestB) {
		t.Fatalf("digest must be supplied only through protected override files: %q", joined)
	}
}

func TestComposeDeployRejectsCrossRepositoryBeforeDocker(t *testing.T) {
	cfg, fake := deployTestConfig(t)
	result := executeDockerComposeDeploy(
		context.Background(),
		client.OperationTask{
			ServiceKey:    "compose:demo:api:1",
			CurrentDigest: "ghcr.io/org/app@" + testDigestA,
			TargetDigest:  "ghcr.io/org/other@" + testDigestB,
		},
		cfg,
		fake.run,
	)
	if result.Status != "failed" || result.ErrorCode != "task_rejected" {
		t.Fatalf("unexpected invalid digest result: %#v", result)
	}
}
