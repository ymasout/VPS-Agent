import { describe, expect, it } from "vitest";
import type { Operation } from "./api";
import { candidateAction, operationPresentation, operationStatus, persistedAction, verificationSummary } from "./operation-presentation";

const now = Date.parse("2026-09-08T12:00:00Z");
const access = { namedAuthorization: true, canApprove: true, canPlan: true, currentPrincipalId: "approver" };
function operation(extra: Partial<Operation> = {}): Operation {
  return {
    id: "op-1", agent_id: "agent-1", instance_id: "instance-1", action_type: "docker_restart",
    status: "awaiting_confirmation", rollback_of: null, requested_by: "operator", confirmed_by: null,
    authorization_mode: "named", requested_principal_snapshot: { principal_id: "operator" }, confirmed_principal_snapshot: null,
    plan_snapshot: { machine: { name: "web-01" }, service: { name: "api", environment: "production" } },
    precheck_result: { passed: true }, verification_policy: {}, verification_result: null,
    risk_level: "medium", impact_summary: "bounded restart", expires_at: "2026-09-08T12:05:00Z",
    requested_at: "2026-09-08T12:00:00Z", confirmed_at: null, claimed_at: null, started_at: null,
    execution_completed_at: null, completed_at: null, exit_code: null, output: null, output_truncated: false,
    error_code: null, error_detail: null, transitions: [], current_digest: null, target_digest: null,
    source_event_id: null, source_diagnostic_id: null, source_conversation_turn_id: null, ...extra,
  };
}
describe("Operation display normalization and controls", () => {
  it("keeps candidate aliases separate and uses only top-level rollback_of", () => {
    expect(candidateAction("docker_compose_rollback").family).toBe("rollback");
    expect(persistedAction("docker_compose_rollback", "op-0").family).toBe("unknown");
    expect(persistedAction("docker_compose_deploy", null).family).toBe("deploy");
    expect(persistedAction("docker_compose_deploy", "op-0").family).toBe("rollback");
    const model = operationPresentation(operation({ action_type: "docker_compose_deploy", plan_snapshot: { rollback_of: "untrusted" } }), access, now);
    expect(model.actionFamily).toBe("deploy");
    expect(model.rollbackOf).toBeNull();
  });
  it.each(["systemd_restart", "docker_compose_rollback", "unknown", "toString", "__proto__"])("fails closed for persisted action %s", (action_type) => {
    const model = operationPresentation(operation({ action_type }), access, now);
    expect(model.actionFamily).toBe("unknown");
    expect(model.actionLabel).not.toBe("安全重启");
    expect(model.canConfirm).toBe(false);
    expect(model.canCreateFollowUp).toBe(false);
  });
  it("requires a fresh unexpired known plan and independent trusted approver", () => {
    expect(operationPresentation(operation(), access, now).canConfirm).toBe(true);
    for (const override of [
      { canApprove: false }, { currentPrincipalId: null }, { currentPrincipalId: "operator" },
    ]) expect(operationPresentation(operation(), { ...access, ...override }, now).canConfirm).toBe(false);
    for (const override of [
      { expires_at: "invalid" }, { expires_at: "2026-09-08T12:00:00Z" }, { status: "running" },
      { status: "new_state" }, { requested_principal_snapshot: null },
      { authorization_mode: "break_glass" as const }, { plan_snapshot: { permanently_non_executable: true } },
    ]) expect(operationPresentation(operation(override), access, now).canConfirm).toBe(false);
  });
  it("supports known deploy and rollback versions and hides unsupported versions", () => {
    const deploy = operation({ action_type: "docker_compose_deploy", current_digest: "a", target_digest: "b", plan_snapshot: { plan_version: "m4.2b-executable-v1" } });
    expect(operationPresentation(deploy, access, now).canConfirm).toBe(true);
    expect(operationPresentation({ ...deploy, rollback_of: "op-0" }, access, now).canConfirm).toBe(false);
    expect(operationPresentation({ ...deploy, rollback_of: "op-0", plan_snapshot: { plan_version: "m4.2c-rollback-v1" } }, access, now).canConfirm).toBe(true);
    const failed = { ...deploy, status: "failed", started_at: "2026-09-08T12:00:00Z" };
    expect(operationPresentation(failed, access, now).canCreateFollowUp).toBe(true);
    expect(operationPresentation(failed, { ...access, canPlan: false }, now).canCreateFollowUp).toBe(false);
    expect(operationPresentation({ ...failed, rollback_of: "op-0" }, access, now).canCreateFollowUp).toBe(false);
  });
  it("does not equate non-success states or exit zero with failure or verified success", () => {
    for (const state of ["planned", "awaiting_confirmation", "queued", "claimed", "running", "verifying"]) {
      expect(operationStatus(state).tone).not.toBe("danger");
    }
    expect(operationStatus("canceled").label).toBe("已取消");
    expect(operationStatus("future").tone).toBe("neutral");
    expect(verificationSummary(null)).toBe("尚无健康验证结果");
    expect(verificationSummary({ status: "passed" })).toBe("健康验证通过");
    expect(verificationSummary({ status: "toString" })).toContain("未知");
  });
});
