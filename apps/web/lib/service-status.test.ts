import { describe, expect, it } from "vitest";
import { Service } from "./api";
import { isServiceProblem, serviceStatusTone } from "./service-status";

function service(kind: string, state: string, healthy: boolean | null = null): Service {
  return { kind, state, healthy, key: "test", name: "test", detail: null, observed_at: "" };
}

describe("service status compatibility", () => {
  it("treats Docker exited as a problem", () => {
    expect(isServiceProblem(service("docker", "exited"))).toBe(true);
  });

  it("keeps legacy systemd exited neutral", () => {
    const item = service("systemd", "exited");
    expect(isServiceProblem(item)).toBe(false);
    expect(serviceStatusTone(item)).toBe("neutral");
  });

  it("always treats explicit failed health as a problem", () => {
    expect(isServiceProblem(service("systemd", "active", false))).toBe(true);
  });
});
