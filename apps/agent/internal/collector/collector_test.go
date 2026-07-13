package collector

import "testing"

func TestParseSystemdServicesUsesActiveState(t *testing.T) {
	services := parseSystemdServices(`ssh.service loaded active running OpenBSD Secure Shell server
cron.service loaded inactive dead Regular background program processing daemon
broken.service loaded failed failed Broken service`)

	if len(services) != 3 {
		t.Fatalf("expected 3 services, got %d", len(services))
	}
	if services[0].State != "active" || services[0].Detail != "running · OpenBSD Secure Shell server" {
		t.Fatalf("unexpected active service: %#v", services[0])
	}
	if services[0].Healthy == nil || !*services[0].Healthy {
		t.Fatal("active service should be healthy")
	}
	if services[1].State != "inactive" || services[1].Healthy != nil {
		t.Fatalf("inactive service should be neutral: %#v", services[1])
	}
	if services[2].State != "failed" || services[2].Healthy == nil || *services[2].Healthy {
		t.Fatalf("failed service should be unhealthy: %#v", services[2])
	}
}
