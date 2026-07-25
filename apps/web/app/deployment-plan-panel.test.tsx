import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { DeploymentCandidate } from "@/lib/api";
import { DeploymentPlanPanel } from "./deployment-plan-panel";

function candidate(serviceKey: string): DeploymentCandidate {
  return {
    agent_id: "agent-1",
    service_kind: "docker",
    service_key: serviceKey,
    repository: "ghcr.io/example/api",
    current_digest: `ghcr.io/example/api@sha256:${"a".repeat(64)}`,
    eligible: true,
    reason_code: null,
    observed_at: "2026-07-25T00:00:00Z",
    mapped: true,
    instance_id: `instance-${serviceKey}`,
    service_name: serviceKey,
    criticality: "non_critical",
    state: "running",
    healthy: true,
    deploy_capable: true,
    deploy_enabled: true,
  };
}

describe("deployment plan trusted navigation focus", () => {
  it("only highlights an already returned candidate and keeps the selector independent", () => {
    const markup = renderToStaticMarkup(
      <DeploymentPlanPanel
        candidates={[candidate("other"), candidate("compose:demo:api:1")]}
        focusServiceKey="compose:demo:api:1"
      />,
    );

    expect(markup).toContain('id="deployment-plans"');
    expect(markup).toContain('aria-current="true"');
    expect(markup.indexOf("compose:demo:api:1")).toBeLessThan(markup.indexOf("other"));
    expect(markup).toContain("目标 repo@sha256 digest");
  });
});
