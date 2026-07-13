package collector

import (
	"bufio"
	"context"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"runtime"
	"strconv"
	"strings"
	"time"

	"github.com/example/vps-agent-console/apps/agent/internal/client"
)

type Host struct{ Hostname, MachineID, OS, Arch string }

func HostInfo() (Host, error) {
	hostname, err := os.Hostname()
	if err != nil {
		return Host{}, err
	}
	machineID := readTrimmed("/etc/machine-id")
	if machineID == "" {
		machineID = hostname
	}
	osName := readTrimmed("/etc/os-release")
	for _, line := range strings.Split(osName, "\n") {
		if strings.HasPrefix(line, "PRETTY_NAME=") {
			osName = strings.Trim(strings.TrimPrefix(line, "PRETTY_NAME="), "\"")
			break
		}
	}
	if osName == "" {
		osName = runtime.GOOS
	}
	return Host{hostname, machineID, osName, runtime.GOARCH}, nil
}

func Collect(ctx context.Context) (client.Metrics, []client.Service, error) {
	cpu, err := cpuPercent()
	if err != nil {
		return client.Metrics{}, nil, err
	}
	total, used, memPercent, err := memory()
	if err != nil {
		return client.Metrics{}, nil, err
	}
	disks := disk()
	services := append(dockerServices(ctx), systemdServices(ctx)...)
	return client.Metrics{CPUPercent: cpu, MemoryPercent: memPercent, MemoryUsedBytes: used, MemoryTotalBytes: total, Disks: disks}, services, nil
}

func HTTPHealthchecks(ctx context.Context, urls []string) []client.Service {
	httpClient := &http.Client{Timeout: 5 * time.Second}
	result := make([]client.Service, 0, len(urls))
	for _, url := range urls {
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
		healthy, state, detail := false, "unhealthy", "request failed"
		if err == nil {
			if response, requestErr := httpClient.Do(req); requestErr == nil {
				response.Body.Close()
				healthy = response.StatusCode >= 200 && response.StatusCode < 400
				state, detail = "healthy", response.Status
				if !healthy {
					state = "unhealthy"
				}
			} else {
				detail = requestErr.Error()
			}
		} else {
			detail = err.Error()
		}
		result = append(result, client.Service{Kind: "http", Key: url, Name: url, State: state, Detail: detail, Healthy: &healthy})
	}
	return result
}

func cpuPercent() (float64, error) {
	idle1, total1, err := cpuTimes()
	if err != nil {
		return 0, err
	}
	time.Sleep(200 * time.Millisecond)
	idle2, total2, err := cpuTimes()
	if err != nil {
		return 0, err
	}
	if total2 == total1 {
		return 0, nil
	}
	return float64((total2-total1)-(idle2-idle1)) * 100 / float64(total2-total1), nil
}

func cpuTimes() (uint64, uint64, error) {
	f, err := os.Open("/proc/stat")
	if err != nil {
		return 0, 0, err
	}
	defer f.Close()
	line, _ := bufio.NewReader(f).ReadString('\n')
	fields := strings.Fields(line)
	if len(fields) < 5 {
		return 0, 0, fmt.Errorf("invalid /proc/stat")
	}
	var values []uint64
	for _, field := range fields[1:] {
		value, _ := strconv.ParseUint(field, 10, 64)
		values = append(values, value)
	}
	var total uint64
	for _, value := range values {
		total += value
	}
	return values[3] + values[4], total, nil
}

func memory() (float64, float64, float64, error) {
	f, err := os.Open("/proc/meminfo")
	if err != nil {
		return 0, 0, 0, err
	}
	defer f.Close()
	values := map[string]float64{}
	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		fields := strings.Fields(scanner.Text())
		if len(fields) >= 2 {
			value, _ := strconv.ParseFloat(fields[1], 64)
			values[strings.TrimSuffix(fields[0], ":")] = value * 1024
		}
	}
	total := values["MemTotal"]
	available := values["MemAvailable"]
	if total == 0 {
		return 0, 0, 0, fmt.Errorf("MemTotal missing")
	}
	used := total - available
	return total, used, used * 100 / total, nil
}

func dockerServices(ctx context.Context) []client.Service {
	out, err := exec.CommandContext(ctx, "docker", "ps", "-a", "--format", "{{.ID}}|{{.Names}}|{{.State}}|{{.Status}}").Output()
	if err != nil {
		return nil
	}
	var result []client.Service
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		parts := strings.SplitN(line, "|", 4)
		if len(parts) == 4 {
			healthy := parts[2] == "running"
			result = append(result, client.Service{Kind: "docker", Key: parts[0], Name: parts[1], State: parts[2], Detail: parts[3], Healthy: &healthy})
		}
	}
	return result
}

func systemdServices(ctx context.Context) []client.Service {
	out, err := exec.CommandContext(ctx, "systemctl", "list-units", "--type=service", "--all", "--no-legend", "--no-pager", "--plain").Output()
	if err != nil {
		return nil
	}
	return parseSystemdServices(string(out))
}

func parseSystemdServices(output string) []client.Service {
	var result []client.Service
	scanner := bufio.NewScanner(strings.NewReader(output))
	for scanner.Scan() {
		fields := strings.Fields(scanner.Text())
		if len(fields) >= 5 {
			activeState := fields[2]
			subState := fields[3]
			var healthy *bool
			if activeState == "active" {
				value := true
				healthy = &value
			} else if activeState == "failed" {
				value := false
				healthy = &value
			}
			result = append(result, client.Service{
				Kind:    "systemd",
				Key:     fields[0],
				Name:    fields[0],
				State:   activeState,
				Detail:  subState + " · " + strings.Join(fields[4:], " "),
				Healthy: healthy,
			})
		}
	}
	return result
}

func readTrimmed(path string) string {
	data, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(data))
}
