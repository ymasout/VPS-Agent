//go:build linux

package collector

import (
	"syscall"

	"github.com/example/vps-agent-console/apps/agent/internal/client"
)

func disk() []client.DiskMetric {
	var stat syscall.Statfs_t
	if syscall.Statfs("/", &stat) != nil {
		return nil
	}
	total := float64(stat.Blocks) * float64(stat.Bsize)
	available := float64(stat.Bavail) * float64(stat.Bsize)
	used := total - available
	percent := 0.0
	if total > 0 {
		percent = used * 100 / total
	}
	return []client.DiskMetric{{Path: "/", UsedBytes: used, TotalBytes: total, UsedPercent: percent}}
}
