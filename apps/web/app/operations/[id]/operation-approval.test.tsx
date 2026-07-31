import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { Operation } from "@/lib/api";
import { operationApprovalSummary } from "./operation-approval";
import { OperationPanel } from "./operation-panel";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }) }));

function operation(overrides: Partial<Operation> = {}): Operation {
  return {
    id: "operation-1",
    instance_id: "instance-1",
    agent_id: "agent-1",
    source_event_id: null,
    source_diagnostic_id: null,
    source_conversation_turn_id: null,
    action_type: "docker_compose_restart",
    status: "awaiting_confirmation",
    requested_by: "local-admin",
    confirmed_by: null,
    risk_level: "medium",
    impact_summary: "restart the selected service",
    plan_snapshot: {
      machine: { name: "edge-01" },
      service: { name: "gateway", environment: "production" },
    },
    precheck_result: { passed: true, capability_allowed: true, target_frozen: true },
    verification_policy: { health: "stable" },
    verification_result: null,
    expires_at: "2026-07-27T14:00:00Z",
    requested_at: "2026-07-27T13:00:00Z",
    confirmed_at: null,
    claimed_at: null,
    started_at: null,
    execution_completed_at: null,
    completed_at: null,
    exit_code: null,
    output: null,
    output_truncated: false,
    error_code: null,
    error_detail: null,
    transitions: [],
    current_digest: null,
    target_digest: null,
    rollback_of: null,
    ...overrides,
  };
}

describe("mobile operation approval", () => {
  it("derives display-only targets from the frozen operation", () => {
    expect(operationApprovalSummary(operation())).toEqual(expect.objectContaining({
      action: "安全重启",
      machine: "edge-01",
      service: "gateway",
      environment: "production",
      passedPrechecks: 2,
      failedPrechecks: 0,
    }));
    expect(operationApprovalSummary(operation({ rollback_of: "failed-deploy", action_type: "docker_compose_deploy" })).action).toBe("显式回滚");
  });

  it("renders the frozen target and keeps confirmation disabled by default", () => {
    const markup = renderToStaticMarkup(<OperationPanel operation={operation()} />);
    expect(markup).toContain("核对后确认");
    expect(markup).toContain("edge-01");
    expect(markup).toContain("gateway · production");
    expect(markup).toContain("我已核对目标、动作、风险和有效期");
    expect(markup).toContain("disabled");
    expect(markup).not.toContain('name="machine"');
    expect(markup).not.toContain('name="action"');
  });

  it("shows named confirmation only to an independent approver", () => {
    const named = operation({
      requested_by: "local:operator",
      authorization_mode: "named",
    });
    const approverMarkup = renderToStaticMarkup(
      <OperationPanel
        operation={named}
        namedAuthorization
        canApprove
        currentPrincipalId="local:approver"
      />,
    );
    expect(approverMarkup).toContain("我已核对目标、动作、风险和有效期");
    expect(approverMarkup).not.toContain("当前身份没有 operation:approve");

    const operatorMarkup = renderToStaticMarkup(
      <OperationPanel
        operation={named}
        namedAuthorization
        currentPrincipalId="local:operator"
      />,
    );
    expect(operatorMarkup).toContain("当前身份没有 operation:approve");
    expect(operatorMarkup).not.toContain("我已核对目标、动作、风险和有效期");

    const sameActorMarkup = renderToStaticMarkup(
      <OperationPanel
        operation={named}
        namedAuthorization
        canApprove
        currentPrincipalId="local:operator"
      />,
    );
    expect(sameActorMarkup).toContain("计划创建人与审批人必须不同");
    expect(sameActorMarkup).not.toContain("我已核对目标、动作、风险和有效期");
  });
});
