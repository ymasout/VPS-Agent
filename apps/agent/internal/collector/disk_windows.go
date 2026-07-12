//go:build windows

package collector

import "github.com/example/vps-agent-console/apps/agent/internal/client"

// Windows support is limited to compilation and local protocol development;
// production collection targets Linux VPS hosts.
func disk() []client.DiskMetric { return nil }
