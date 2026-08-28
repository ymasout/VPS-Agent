import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { Agent } from "../lib/api";
import { summarizeFleet } from "../lib/fleet";
import { relativeTime } from "./overview-dashboard";

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

  it("keeps the M7.1b overview read-only and exposes explicit trend states", () => {
    const page = readFileSync(resolve(process.cwd(), "app/overview-dashboard.tsx"), "utf8");
    const chart = readFileSync(resolve(process.cwd(), "app/overview-sparkline.tsx"), "utf8");
    const api = readFileSync(resolve(process.cwd(), "../api/app/overview.py"), "utf8");

    expect(page).toContain("需要关注");
    expect(page).toContain("Fleet 健康");
    expect(page).toContain("Operation 进度");
    expect(page).toContain("系统信任摘要");
    expect(page).toContain("趋势不可用");
    expect(page).toContain("数据已过期");
    expect(page).not.toMatch(/<button|<form/);
    expect(chart).toContain('isAnimationActive={false}');
    expect(chart).toContain('role="img"');
    expect(chart).toContain('danger: "var(--color-danger)"');
    expect(chart).toContain("lastPointIndex");
    expect(api).toContain("MAX_RAW_POINTS_PER_AGENT = 1440");
    expect(api).toContain("MAX_TREND_POINTS = 48");
  });

  it("formats overview activity relative to the server generation time", () => {
    expect(relativeTime("2026-08-28T11:59:51Z", "2026-08-28T12:00:00Z")).toBe("9 秒前");
    expect(relativeTime("2026-08-28T11:44:00Z", "2026-08-28T12:00:00Z")).toBe("16 分钟前");
  });
});
