import type { Operation } from "./api";

export type StatusTone = "neutral" | "info" | "warning" | "danger" | "success";
export type ActionFamily = "restart" | "deploy" | "rollback" | "maintenance" | "unknown";
const actions: Record<string, { label: string; family: ActionFamily }> = {
  docker_restart: { label: "安全重启", family: "restart" },
  docker_compose_deploy: { label: "受控部署", family: "deploy" },
};
export const operationStatuses: Record<string, { label: string; tone: StatusTone }> = {
  planned: { label: "已计划", tone: "neutral" },
  prechecking: { label: "前置检查中", tone: "info" },
  awaiting_confirmation: { label: "待独立确认", tone: "info" },
  queued: { label: "已排队", tone: "info" },
  claimed: { label: "已领取", tone: "info" },
  running: { label: "执行中", tone: "info" },
  verifying: { label: "健康验证中", tone: "info" },
  succeeded: { label: "已成功", tone: "success" },
  failed: { label: "已失败", tone: "danger" },
  expired: { label: "已过期", tone: "warning" },
  rejected: { label: "已拒绝", tone: "warning" },
  canceled: { label: "已取消", tone: "neutral" },
  cancelled: { label: "已取消", tone: "neutral" },
};
export function operationStatus(status: string) {
  return Object.hasOwn(operationStatuses, status)
    ? operationStatuses[status] : { label: `未知状态 · ${status}`, tone: "neutral" as const };
}
// Candidate aliases are not persisted Operation types and never enable controls.
export function candidateAction(actionType: string) {
  if (actionType === "docker_compose_rollback") return { label: "准备显式回滚计划", family: "rollback" as const };
  return persistedAction(actionType, null);
}
export function persistedAction(actionType: string, rollbackOf: string | null) {
  if (actionType === "docker_compose_deploy" && rollbackOf !== null) return { label: "显式回滚", family: "rollback" as const };
  return Object.hasOwn(actions, actionType)
    ? actions[actionType] : { label: `未知动作 · ${actionType}`, family: "unknown" as const };
}
export function displayValue(value: unknown, fallback = "未提供"): string {
  return typeof value === "string" || typeof value === "number" ? String(value).slice(0, 512) : fallback;
}
export function utcTime(value: string | null) {
  if (!value || !Number.isFinite(Date.parse(value))) return "未提供";
  return new Date(value).toISOString().replace("T", " ").slice(0, 19) + " UTC";
}
export function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}
export type OperationAccess = {
  namedAuthorization: boolean; canApprove: boolean; canPlan: boolean; currentPrincipalId: string | null;
};
export type OperationPresentation = {
  actionType: string; actionLabel: string; actionFamily: ActionFamily; rollbackOf: string | null;
  status: string; statusLabel: string; statusTone: StatusTone;
  target: { machine: string; service: string; environment: string };
  risk: string; expiresAt: string; canConfirm: boolean; canCreateFollowUp: boolean;
  confirmationReason: string | null;
  sections: Array<"summary" | "prechecks" | "verification" | "audit" | "technical">;
};
export function operationPresentation(operation: Operation, access: OperationAccess, now: number): OperationPresentation {
  const action = persistedAction(operation.action_type, operation.rollback_of);
  const status = operationStatus(operation.status);
  const plan = operation.plan_snapshot;
  const machine = record(plan.machine);
  const service = record(plan.service);
  const known = action.family !== "unknown" && Object.hasOwn(operationStatuses, operation.status);
  const planOnly = plan.permanently_non_executable === true;
  const executable = operation.action_type === "docker_restart" || (
    operation.action_type === "docker_compose_deploy" && Boolean(operation.current_digest && operation.target_digest) &&
    plan.plan_version === (operation.rollback_of !== null ? "m4.2c-rollback-v1" : "m4.2b-executable-v1")
  );
  let confirmationReason: string | null = null;
  if (!known) confirmationReason = "未知动作或状态，仅提供只读展示。";
  else if (planOnly || !executable) confirmationReason = "此计划仅供阅读，不能确认或签发任务。";
  else if (operation.authorization_mode === "break_glass") confirmationReason = "事故流程记录仅供审计，Web 不提供操作入口。";
  else if (operation.status !== "awaiting_confirmation") confirmationReason = "当前状态不接受确认。";
  else if (!Number.isFinite(Date.parse(operation.expires_at)) || Date.parse(operation.expires_at) <= now) confirmationReason = "计划有效期已结束或不可验证；服务端状态尚未更新时也不能确认。";
  else if (access.namedAuthorization && (!access.canApprove || !access.currentPrincipalId)) confirmationReason = "当前身份没有 operation:approve；请由独立审批人核对并确认。";
  else if (access.namedAuthorization && access.currentPrincipalId === operation.requested_by) confirmationReason = "计划创建人与审批人必须不同；请切换到独立审批身份。";
  else if (access.namedAuthorization && (operation.authorization_mode !== "named" || !operation.requested_principal_snapshot)) confirmationReason = "缺少具名请求者快照，不能通过 Web 确认。";
  return {
    actionType: operation.action_type, actionLabel: action.label, actionFamily: action.family,
    rollbackOf: operation.rollback_of, status: operation.status, statusLabel: status.label, statusTone: status.tone,
    target: {
      machine: displayValue(machine.name ?? machine.hostname, operation.agent_id),
      service: displayValue(service.name, operation.instance_id),
      environment: displayValue(service.environment, "环境未知"),
    },
    risk: operation.risk_level, expiresAt: operation.expires_at,
    canConfirm: confirmationReason === null, confirmationReason,
    canCreateFollowUp: known && !planOnly && operation.authorization_mode !== "break_glass" &&
      action.family === "deploy" && plan.plan_version === "m4.2b-executable-v1" &&
      operation.status === "failed" && operation.started_at !== null &&
      (!access.namedAuthorization || (access.canPlan && Boolean(access.currentPrincipalId))),
    sections: ["summary", "prechecks", "verification", "audit", "technical"],
  };
}
export function verificationSummary(result: Record<string, unknown> | null) {
  const labels: Record<string, string> = {
    passed: "健康验证通过", failed: "健康验证失败", stability_window: "正在观察健康稳定窗口",
    waiting_for_fresh_observation: "等待执行后的新观测", waiting_for_healthy_observation: "等待健康观测",
    waiting_for_deployment_observation: "等待目标镜像与健康的同次观测",
  };
  const status = result?.status;
  return typeof status === "string" && Object.hasOwn(labels, status)
    ? labels[status] : result ? "验证结论未知，请核对技术详情" : "尚无健康验证结果";
}
