package collector

import (
	"context"
	"encoding/json"
	"errors"
	"os/exec"
	"regexp"
	"sort"
	"strings"

	"github.com/example/vps-agent-console/apps/agent/internal/client"
)

const maxDeploymentCandidates = 128

var digestPattern = regexp.MustCompile(`^sha256:[0-9a-f]{64}$`)
var registryPattern = regexp.MustCompile(`^(?:[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?)(?::[0-9]{1,5})?$`)
var repositoryPartPattern = regexp.MustCompile(`^[a-z0-9]+(?:(?:[._]|__|[-]+)[a-z0-9]+)*$`)

type dockerCommand func(context.Context, string, ...string) ([]byte, error)

type composeContainer struct {
	ID      string
	Name    string
	Project string
	Service string
	Replica string
}

type containerInspect struct {
	ID     string `json:"Id"`
	Image  string `json:"Image"`
	Config struct {
		Image       string `json:"Image"`
		Healthcheck *struct {
			Test []string `json:"Test"`
		} `json:"Healthcheck"`
	} `json:"Config"`
}

type imageInspect struct {
	ID          string   `json:"Id"`
	RepoDigests []string `json:"RepoDigests"`
}

func runDocker(ctx context.Context, name string, args ...string) ([]byte, error) {
	return exec.CommandContext(ctx, name, args...).Output()
}

// DeploymentCandidates performs Docker metadata reads only. It never reads Compose files or runs Compose.
func DeploymentCandidates(ctx context.Context) []client.DeploymentCandidate {
	return collectDeploymentCandidates(ctx, runDocker)
}

func collectDeploymentCandidates(ctx context.Context, command dockerCommand) []client.DeploymentCandidate {
	output, err := command(ctx, "docker", "ps", "-a", "--format", `{{.ID}}|{{.Names}}|{{.Label "com.docker.compose.project"}}|{{.Label "com.docker.compose.service"}}|{{.Label "com.docker.compose.container-number"}}`)
	if err != nil {
		return nil
	}
	containers := parseComposeContainers(string(output))
	if len(containers) == 0 {
		return nil
	}
	groups := map[string]int{}
	for _, container := range containers {
		groups[container.Project+"\x00"+container.Service]++
	}
	if len(containers) > maxDeploymentCandidates {
		containers = containers[:maxDeploymentCandidates]
	}
	ids := make([]string, 0, len(containers))
	for _, container := range containers {
		ids = append(ids, container.ID)
	}
	inspectArgs := append([]string{"inspect"}, ids...)
	containerJSON, err := command(ctx, "docker", inspectArgs...)
	if err != nil {
		return candidatesWithReason(containers, "inspect_failed")
	}
	var inspected []containerInspect
	if json.Unmarshal(containerJSON, &inspected) != nil {
		return candidatesWithReason(containers, "inspect_failed")
	}
	byContainer := map[string]containerInspect{}
	imageIDs := make([]string, 0, len(inspected))
	seenImages := map[string]bool{}
	for _, item := range inspected {
		byContainer[item.ID] = item
		if !seenImages[item.Image] {
			seenImages[item.Image] = true
			imageIDs = append(imageIDs, item.Image)
		}
	}
	if len(imageIDs) == 0 {
		return candidatesWithReason(containers, "inspect_failed")
	}
	imageArgs := append([]string{"image", "inspect"}, imageIDs...)
	imageJSON, err := command(ctx, "docker", imageArgs...)
	if err != nil {
		return candidatesWithReason(containers, "digest_unresolved")
	}
	var images []imageInspect
	if json.Unmarshal(imageJSON, &images) != nil {
		return candidatesWithReason(containers, "digest_unresolved")
	}
	byImage := map[string]imageInspect{}
	for _, image := range images {
		byImage[image.ID] = image
	}
	result := make([]client.DeploymentCandidate, 0, len(containers))
	for _, container := range containers {
		candidate := client.DeploymentCandidate{
			ServiceKind: "docker",
			ServiceKey:  StableDockerServiceKey(container.Name, container.Project, container.Service, container.Replica),
		}
		inspectedContainer, ok := findContainerInspect(byContainer, container.ID)
		if !ok {
			candidate.ReasonCode = "inspect_failed"
			result = append(result, candidate)
			continue
		}
		repository, normalizeErr := normalizeRepository(inspectedContainer.Config.Image)
		if normalizeErr != nil {
			candidate.ReasonCode = "repository_unresolved"
			result = append(result, candidate)
			continue
		}
		candidate.Repository = repository
		image, ok := byImage[inspectedContainer.Image]
		if !ok {
			candidate.ReasonCode = "digest_unresolved"
			result = append(result, candidate)
			continue
		}
		matches := map[string]bool{}
		for _, repoDigest := range image.RepoDigests {
			matchRepository, canonical, parseErr := parseDigestReference(repoDigest)
			if parseErr == nil && matchRepository == repository {
				matches[canonical] = true
			}
		}
		if len(matches) == 0 {
			candidate.ReasonCode = "digest_unresolved"
			result = append(result, candidate)
			continue
		}
		if len(matches) > 1 {
			candidate.ReasonCode = "digest_ambiguous"
			result = append(result, candidate)
			continue
		}
		for digest := range matches {
			candidate.CurrentDigest = digest
		}
		if groups[container.Project+"\x00"+container.Service] != 1 {
			candidate.ReasonCode = "multiple_replicas"
			result = append(result, candidate)
			continue
		}
		if !hasHealthcheck(inspectedContainer) {
			candidate.ReasonCode = "healthcheck_missing"
			result = append(result, candidate)
			continue
		}
		candidate.Eligible = true
		result = append(result, candidate)
	}
	return uniqueDeploymentCandidates(result)
}

func parseComposeContainers(output string) []composeContainer {
	result := make([]composeContainer, 0)
	for _, line := range strings.Split(strings.TrimSpace(output), "\n") {
		parts := strings.SplitN(line, "|", 5)
		if len(parts) != 5 || parts[0] == "" || parts[1] == "" || parts[2] == "" || parts[3] == "" {
			continue
		}
		result = append(result, composeContainer{ID: parts[0], Name: parts[1], Project: parts[2], Service: parts[3], Replica: parts[4]})
	}
	sort.Slice(result, func(i, j int) bool {
		left := result[i].Project + "\x00" + result[i].Service + "\x00" + result[i].Replica + "\x00" + result[i].Name
		right := result[j].Project + "\x00" + result[j].Service + "\x00" + result[j].Replica + "\x00" + result[j].Name
		return left < right
	})
	return result
}

func candidatesWithReason(containers []composeContainer, reason string) []client.DeploymentCandidate {
	result := make([]client.DeploymentCandidate, 0, len(containers))
	for _, item := range containers {
		result = append(result, client.DeploymentCandidate{ServiceKind: "docker", ServiceKey: StableDockerServiceKey(item.Name, item.Project, item.Service, item.Replica), ReasonCode: reason})
	}
	return uniqueDeploymentCandidates(result)
}

func uniqueDeploymentCandidates(items []client.DeploymentCandidate) []client.DeploymentCandidate {
	result := make([]client.DeploymentCandidate, 0, len(items))
	byKey := map[string]int{}
	for _, item := range items {
		if index, exists := byKey[item.ServiceKey]; exists {
			result[index].Eligible = false
			result[index].ReasonCode = "multiple_replicas"
			continue
		}
		byKey[item.ServiceKey] = len(result)
		result = append(result, item)
	}
	return result
}

func findContainerInspect(items map[string]containerInspect, shortID string) (containerInspect, bool) {
	if item, ok := items[shortID]; ok {
		return item, true
	}
	var found containerInspect
	count := 0
	for id, item := range items {
		if strings.HasPrefix(id, shortID) {
			found = item
			count++
		}
	}
	return found, count == 1
}

func hasHealthcheck(item containerInspect) bool {
	return item.Config.Healthcheck != nil && len(item.Config.Healthcheck.Test) > 0 && strings.ToUpper(item.Config.Healthcheck.Test[0]) != "NONE"
}

func normalizeRepository(reference string) (string, error) {
	if reference == "" || strings.TrimSpace(reference) != reference || strings.ContainsAny(reference, " \t\r\n") || strings.Contains(reference, "://") {
		return "", errors.New("invalid image repository")
	}
	name := strings.SplitN(reference, "@", 2)[0]
	if colon, slash := strings.LastIndex(name, ":"), strings.LastIndex(name, "/"); colon > slash {
		name = name[:colon]
	}
	parts := strings.Split(name, "/")
	for _, part := range parts {
		if part == "" {
			return "", errors.New("invalid image repository")
		}
	}
	first := strings.ToLower(parts[0])
	registry := "docker.io"
	path := parts
	if strings.Contains(first, ".") || strings.Contains(first, ":") || first == "localhost" {
		registry = first
		path = parts[1:]
	}
	if registry == "index.docker.io" {
		registry = "docker.io"
	}
	for index := range path {
		path[index] = strings.ToLower(path[index])
	}
	if registry == "docker.io" && len(path) == 1 {
		path = append([]string{"library"}, path...)
	}
	if len(path) == 0 || !registryPattern.MatchString(registry) {
		return "", errors.New("invalid image repository")
	}
	for _, part := range path {
		if !repositoryPartPattern.MatchString(part) {
			return "", errors.New("invalid image repository")
		}
	}
	return strings.Join(append([]string{registry}, path...), "/"), nil
}

func parseDigestReference(reference string) (string, string, error) {
	if strings.Count(reference, "@") != 1 {
		return "", "", errors.New("invalid digest reference")
	}
	parts := strings.SplitN(reference, "@", 2)
	if !digestPattern.MatchString(parts[1]) {
		return "", "", errors.New("invalid digest")
	}
	repository, err := normalizeRepository(parts[0])
	if err != nil {
		return "", "", err
	}
	return repository, repository + "@" + parts[1], nil
}

// ParseDigestReference exposes the shared strict repository/digest rules to the executor.
func ParseDigestReference(reference string) (string, string, error) {
	return parseDigestReference(reference)
}
