package operation

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"time"

	"github.com/example/vps-agent-console/apps/agent/internal/client"
	"github.com/example/vps-agent-console/apps/agent/internal/collector"
	"github.com/example/vps-agent-console/apps/agent/internal/config"
)

const deployExecutionTimeout = 300 * time.Second

var composeNamePattern = regexp.MustCompile(`^[a-zA-Z0-9][a-zA-Z0-9_.-]*$`)
var configHashPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)

type deployCommand func(context.Context, string, ...string) ([]byte, error)

type deploymentTarget struct {
	ID              string
	Name            string
	Project         string
	Service         string
	WorkingDir      string
	ConfigFiles     []string
	EnvironmentFile string
	ConfigHash      string
	CurrentDigest   string
}

type deploymentContainerInspect struct {
	ID     string `json:"Id"`
	Name   string `json:"Name"`
	Image  string `json:"Image"`
	Config struct {
		Image  string            `json:"Image"`
		Labels map[string]string `json:"Labels"`
	} `json:"Config"`
}

type deploymentImageInspect struct {
	ID          string   `json:"Id"`
	RepoDigests []string `json:"RepoDigests"`
}

func runDeployCommand(ctx context.Context, name string, args ...string) ([]byte, error) {
	return exec.CommandContext(ctx, name, args...).Output()
}

// CanDeploy performs the local, fail-closed Compose/path/config preflight.
// It returns a fixed candidate reason code and never returns local paths.
func CanDeploy(ctx context.Context, serviceKey, currentDigest string, cfg config.Config) string {
	return canDeploy(ctx, serviceKey, currentDigest, cfg, runDeployCommand)
}

func canDeploy(
	ctx context.Context, serviceKey, currentDigest string, cfg config.Config, command deployCommand,
) string {
	if len(cfg.DeployAllowedRoots) == 0 {
		return "compose_path_untrusted"
	}
	preflightContext, cancel := context.WithTimeout(ctx, 30*time.Second)
	defer cancel()
	_, cleanup, err := prepareComposeDeployment(
		preflightContext, serviceKey, currentDigest, cfg, command,
	)
	if cleanup != nil {
		cleanup()
	}
	if err == nil {
		return ""
	}
	var deploymentError *deployError
	if errors.As(err, &deploymentError) {
		return deploymentError.code
	}
	return "compose_metadata_invalid"
}

func ExecuteDockerComposeDeploy(
	ctx context.Context, task client.OperationTask, cfg config.Config,
) client.OperationResult {
	return executeDockerComposeDeploy(ctx, task, cfg, runDeployCommand)
}

func executeDockerComposeDeploy(
	ctx context.Context, task client.OperationTask, cfg config.Config, command deployCommand,
) client.OperationResult {
	if err := validateDeploymentDigestPair(task.CurrentDigest, task.TargetDigest); err != nil {
		return failed("task_rejected", "Signed deployment digest pair is invalid")
	}
	executionContext, cancel := context.WithTimeout(ctx, deployExecutionTimeout)
	defer cancel()
	prepared, cleanup, err := prepareComposeDeployment(
		executionContext, task.ServiceKey, task.CurrentDigest, cfg, command,
	)
	if cleanup != nil {
		defer cleanup()
	}
	if err != nil {
		return deploymentFailure(err)
	}
	if _, err = command(executionContext, "docker", "pull", task.TargetDigest); err != nil {
		if errors.Is(executionContext.Err(), context.DeadlineExceeded) {
			return failed("execution_timeout", "Docker image pull exceeded the fixed timeout")
		}
		return failed("pull_failed", "Docker could not pull the signed target digest")
	}

	// Re-resolve immediately before recreation so a pull-time container/config drift fails closed.
	latest, secondCleanup, err := prepareComposeDeployment(
		executionContext, task.ServiceKey, task.CurrentDigest, cfg, command,
	)
	if secondCleanup != nil {
		defer secondCleanup()
	}
	if err != nil {
		return deploymentFailure(err)
	}
	if latest.target.ID != prepared.target.ID {
		return failed("drift_rejected", "Compose target changed after the task was claimed")
	}
	targetOverride, err := writeImageOverride(latest.tempDir, latest.target.Service, task.TargetDigest, "target")
	if err != nil {
		return failed("compose_metadata_invalid", "Agent could not create the protected override")
	}
	args := composeBaseArgs(latest.target, targetOverride)
	args = append(
		args,
		"up", "-d", "--no-deps", "--no-build", "--pull", "never",
		"--force-recreate", "--scale", latest.target.Service+"=1", latest.target.Service,
	)
	if _, err = command(executionContext, "docker", args...); err != nil {
		if errors.Is(executionContext.Err(), context.DeadlineExceeded) {
			return failed("execution_timeout", "Docker Compose deployment exceeded the fixed timeout")
		}
		return failed("compose_failed", "Docker Compose returned a non-zero exit status")
	}
	exitCode := 0
	return client.OperationResult{
		Status: "completed", ExitCode: &exitCode,
		Output:      "Compose recreated the single service; awaiting same-report digest and health verification.",
		CompletedAt: time.Now().UTC(),
	}
}

type preparedDeployment struct {
	target  deploymentTarget
	tempDir string
}

func prepareComposeDeployment(
	ctx context.Context,
	serviceKey string,
	currentDigest string,
	cfg config.Config,
	command deployCommand,
) (preparedDeployment, func(), error) {
	target, err := resolveDeploymentTarget(ctx, serviceKey, currentDigest, command)
	if err != nil {
		return preparedDeployment{}, nil, err
	}
	target.ConfigFiles, err = originalComposeFiles(
		target.ConfigFiles, filepath.Dir(cfg.OperationStateFile),
	)
	if err != nil {
		return preparedDeployment{}, nil, err
	}
	if err = validateComposePaths(target, cfg.DeployAllowedRoots); err != nil {
		return preparedDeployment{}, nil, err
	}
	baseDir := filepath.Dir(cfg.OperationStateFile)
	if err = os.MkdirAll(baseDir, 0700); err != nil {
		return preparedDeployment{}, nil, newDeployError(
			"compose_metadata_invalid", "Agent state directory is unavailable",
		)
	}
	tempDir, err := os.MkdirTemp(baseDir, "deploy-")
	if err != nil {
		return preparedDeployment{}, nil, newDeployError(
			"compose_metadata_invalid", "Agent could not create a protected temporary directory",
		)
	}
	cleanup := func() { _ = os.RemoveAll(tempDir) }
	currentOverride, err := writeImageOverride(tempDir, target.Service, currentDigest, "current")
	if err != nil {
		cleanup()
		return preparedDeployment{}, nil, newDeployError(
			"compose_metadata_invalid", "Agent could not create the current-image override",
		)
	}
	originalHash, err := composeConfigHash(ctx, target, "", command)
	if err != nil {
		cleanup()
		return preparedDeployment{}, nil, newDeployError(
			"compose_config_drift", "Original Compose configuration could not be reproduced",
		)
	}
	currentHash, err := composeConfigHash(ctx, target, currentOverride, command)
	if err != nil {
		cleanup()
		return preparedDeployment{}, nil, newDeployError(
			"compose_config_drift", "Current-image Compose configuration could not be reproduced",
		)
	}
	if target.ConfigHash == "" || (target.ConfigHash != originalHash && target.ConfigHash != currentHash) {
		cleanup()
		return preparedDeployment{}, nil, newDeployError(
			"compose_config_drift", "Running container does not match either safe Compose baseline",
		)
	}
	return preparedDeployment{target: target, tempDir: tempDir}, cleanup, nil
}

// Compose records every -f argument in the recreated container label. The Agent's
// target override is deliberately ephemeral, so a later preflight must remove only
// that exact, final Agent-owned entry before validating the original file list.
func originalComposeFiles(configFiles []string, stateDirectory string) ([]string, error) {
	if len(configFiles) == 0 {
		return nil, newDeployError("compose_metadata_invalid", "Compose configuration file labels are missing")
	}
	last := configFiles[len(configFiles)-1]
	if isAgentTargetOverride(last, stateDirectory) {
		configFiles = configFiles[:len(configFiles)-1]
	}
	if len(configFiles) == 0 {
		return nil, newDeployError("compose_metadata_invalid", "Original Compose configuration files are missing")
	}
	return configFiles, nil
}

func isAgentTargetOverride(path, stateDirectory string) bool {
	if !filepath.IsAbs(path) || filepath.Clean(path) != path || stateDirectory == "" {
		return false
	}
	relative, err := filepath.Rel(filepath.Clean(stateDirectory), path)
	if err != nil {
		return false
	}
	parts := strings.Split(relative, string(os.PathSeparator))
	return len(parts) == 2 && strings.HasPrefix(parts[0], "deploy-") && parts[0] != "deploy-" && parts[1] == "image-target.yaml"
}

func resolveDeploymentTarget(
	ctx context.Context, serviceKey, currentDigest string, command deployCommand,
) (deploymentTarget, error) {
	output, err := command(
		ctx,
		"docker",
		"ps",
		"-a",
		"--format",
		`{{.ID}}|{{.Names}}|{{.Label "com.docker.compose.project"}}|{{.Label "com.docker.compose.service"}}|{{.Label "com.docker.compose.container-number"}}`,
	)
	if err != nil {
		return deploymentTarget{}, newDeployError(
			"compose_metadata_invalid", "Docker Compose service discovery failed",
		)
	}
	type composeContainer struct {
		id, name, project, service, number string
	}
	var containersFromPS []composeContainer
	for _, line := range strings.Split(strings.TrimSpace(string(output)), "\n") {
		parts := strings.SplitN(line, "|", 5)
		if len(parts) != 5 || parts[0] == "" || parts[1] == "" {
			continue
		}
		containersFromPS = append(containersFromPS, composeContainer{
			id: parts[0], name: parts[1], project: parts[2], service: parts[3], number: parts[4],
		})
	}
	var matches []composeContainer
	for _, item := range containersFromPS {
		if collector.StableDockerServiceKey(item.name, item.project, item.service, item.number) == serviceKey {
			matches = append(matches, item)
		}
	}
	if len(matches) != 1 {
		return deploymentTarget{}, newDeployError(
			"drift_rejected", "Stable Compose service identity is missing or ambiguous",
		)
	}
	matched := matches[0]
	replicas := 0
	for _, item := range containersFromPS {
		if item.project == matched.project && item.service == matched.service {
			replicas++
		}
	}
	if replicas != 1 {
		return deploymentTarget{}, newDeployError(
			"drift_rejected", "Compose service no longer has exactly one container",
		)
	}
	containerJSON, err := command(ctx, "docker", "inspect", matched.id)
	if err != nil {
		return deploymentTarget{}, newDeployError(
			"compose_metadata_invalid", "Docker container metadata is unavailable",
		)
	}
	var containers []deploymentContainerInspect
	if json.Unmarshal(containerJSON, &containers) != nil || len(containers) != 1 {
		return deploymentTarget{}, newDeployError(
			"compose_metadata_invalid", "Docker container metadata is invalid",
		)
	}
	container := containers[0]
	labels := container.Config.Labels
	project, service := labels["com.docker.compose.project"], labels["com.docker.compose.service"]
	if !composeNamePattern.MatchString(project) || !composeNamePattern.MatchString(service) {
		return deploymentTarget{}, newDeployError(
			"compose_metadata_invalid", "Compose project or service label is invalid",
		)
	}
	containerName := strings.TrimPrefix(container.Name, "/")
	containerNumber := labels["com.docker.compose.container-number"]
	if !strings.HasPrefix(container.ID, matched.id) || collector.StableDockerServiceKey(containerName, project, service, containerNumber) != serviceKey {
		return deploymentTarget{}, newDeployError(
			"drift_rejected", "Compose service identity changed during inspection",
		)
	}
	configFiles := strings.Split(labels["com.docker.compose.project.config_files"], ",")
	if len(configFiles) == 0 || (len(configFiles) == 1 && configFiles[0] == "") {
		return deploymentTarget{}, newDeployError(
			"compose_metadata_invalid", "Compose configuration file labels are missing",
		)
	}
	imageJSON, err := command(ctx, "docker", "image", "inspect", container.Image)
	if err != nil {
		return deploymentTarget{}, newDeployError(
			"drift_rejected", "Current container image metadata is unavailable",
		)
	}
	var images []deploymentImageInspect
	if json.Unmarshal(imageJSON, &images) != nil || len(images) != 1 {
		return deploymentTarget{}, newDeployError(
			"drift_rejected", "Current container image metadata is invalid",
		)
	}
	repository, canonicalCurrent, parseErr := collector.ParseDigestReference(currentDigest)
	if parseErr != nil || canonicalCurrent != currentDigest {
		return deploymentTarget{}, newDeployError("drift_rejected", "Signed current digest is invalid")
	}
	digestMatches := map[string]bool{}
	for _, value := range images[0].RepoDigests {
		matchRepository, canonical, digestErr := collector.ParseDigestReference(value)
		if digestErr == nil && matchRepository == repository {
			digestMatches[canonical] = true
		}
	}
	if len(digestMatches) != 1 || !digestMatches[currentDigest] {
		return deploymentTarget{}, newDeployError(
			"drift_rejected", "Running image digest no longer matches the signed current digest",
		)
	}
	return deploymentTarget{
		ID: container.ID, Name: containerName, Project: project, Service: service,
		WorkingDir:      labels["com.docker.compose.project.working_dir"],
		ConfigFiles:     configFiles,
		EnvironmentFile: labels["com.docker.compose.project.environment_file"],
		ConfigHash:      labels["com.docker.compose.config-hash"], CurrentDigest: currentDigest,
	}, nil
}

func validateComposePaths(target deploymentTarget, roots []string) error {
	if len(roots) == 0 || target.WorkingDir == "" {
		return newDeployError("compose_path_untrusted", "Compose paths are not locally allowed")
	}
	if err := validateAllowedPath(target.WorkingDir, roots, true); err != nil {
		return err
	}
	for _, path := range target.ConfigFiles {
		if err := validateAllowedPath(path, roots, false); err != nil {
			return err
		}
	}
	if target.EnvironmentFile != "" {
		if strings.Contains(target.EnvironmentFile, ",") {
			return newDeployError("compose_metadata_invalid", "Multiple Compose env files are unsupported")
		}
		if err := validateAllowedPath(target.EnvironmentFile, roots, false); err != nil {
			return err
		}
	}
	return nil
}

func validateAllowedPath(path string, roots []string, directory bool) error {
	if !filepath.IsAbs(path) || filepath.Clean(path) != path {
		return newDeployError("compose_path_untrusted", "Compose path is not canonical")
	}
	resolved, err := filepath.EvalSymlinks(path)
	if err != nil {
		return newDeployError("compose_path_untrusted", "Compose path cannot be resolved")
	}
	info, err := os.Stat(resolved)
	if err != nil || info.IsDir() != directory || (!directory && !info.Mode().IsRegular()) {
		return newDeployError("compose_path_untrusted", "Compose path has an unsupported file type")
	}
	for _, root := range roots {
		resolvedRoot, rootErr := filepath.EvalSymlinks(root)
		if rootErr != nil {
			continue
		}
		relative, relErr := filepath.Rel(resolvedRoot, resolved)
		if relErr == nil && relative != ".." && !strings.HasPrefix(relative, ".."+string(os.PathSeparator)) {
			return nil
		}
	}
	return newDeployError("compose_path_untrusted", "Compose path escapes the local allowlist")
}

func composeBaseArgs(target deploymentTarget, extraFile string) []string {
	args := []string{"compose"}
	if target.EnvironmentFile != "" {
		args = append(args, "--env-file", target.EnvironmentFile)
	}
	for _, path := range target.ConfigFiles {
		args = append(args, "-f", path)
	}
	if extraFile != "" {
		args = append(args, "-f", extraFile)
	}
	return append(
		args,
		"--project-name", target.Project,
		"--project-directory", target.WorkingDir,
	)
}

func composeConfigHash(
	ctx context.Context, target deploymentTarget, extraFile string, command deployCommand,
) (string, error) {
	args := composeBaseArgs(target, extraFile)
	args = append(args, "config", "--hash", target.Service)
	output, err := command(ctx, "docker", args...)
	if err != nil {
		return "", err
	}
	fields := strings.Fields(strings.TrimSpace(string(output)))
	if len(fields) != 2 || fields[0] != target.Service || !configHashPattern.MatchString(fields[1]) {
		return "", errors.New("unexpected Compose config hash output")
	}
	return fields[1], nil
}

func writeImageOverride(directory, service, digest, suffix string) (string, error) {
	serviceJSON, err := json.Marshal(service)
	if err != nil {
		return "", err
	}
	digestJSON, err := json.Marshal(digest)
	if err != nil {
		return "", err
	}
	path := filepath.Join(directory, "image-"+suffix+".yaml")
	content := fmt.Sprintf("services:\n  %s:\n    image: %s\n", serviceJSON, digestJSON)
	if err = os.WriteFile(path, []byte(content), 0600); err != nil {
		return "", err
	}
	if err = os.Chmod(path, 0600); err != nil {
		return "", err
	}
	return path, nil
}

type deployError struct {
	code   string
	detail string
}

func (err *deployError) Error() string { return err.detail }

func newDeployError(code, detail string) error {
	return &deployError{code: code, detail: detail}
}

func deploymentFailure(err error) client.OperationResult {
	var typed *deployError
	if errors.As(err, &typed) {
		return failed(typed.code, typed.detail)
	}
	return failed("compose_metadata_invalid", "Compose deployment preflight failed")
}
