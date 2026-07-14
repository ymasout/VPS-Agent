import { describe, expect, it } from "vitest";
import { Agent } from "../lib/api";
import { summarizeFleet } from "../lib/fleet";

function agent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: "agent-01",
    name: "test-vps",
    hostname: "test-vps",
    os: "Linux",
    arch: "amd64",
    version: "0.2.4",
    online: true,
    last_seen_at: null,
    latest_metrics: null,
    service_counts: {},
    service_kind_counts: {},
    service_problem_count: 0,
    ...overrides,
  };
}

describe("Fleet overview", () => {
  it("summarizes online, offline, and problem counts", () => {
    expect(
      summarizeFleet([
        agent({ service_problem_count: 2 }),
        agent({ id: "agent-02", online: false, service_problem_count: 1 }),
      ]),
    ).toEqual({ total: 2, online: 1, offline: 1, problems: 3 });
  });

  it("returns a stable empty summary", () => {
    expect(summarizeFleet([])).toEqual({ total: 0, online: 0, offline: 0, problems: 0 });
  });
});
