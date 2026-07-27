import type { Operation } from "@/lib/api";

export type OperationApprovalSummary = {
  action: string;
  machine: string;
  service: string;
  environment: string;
  risk: string;
  expiresAt: string;
  passedPrechecks: number;
  failedPrechecks: number;
};

export function operationApprovalSummary(operation: Operation): OperationApprovalSummary {
  const plan = operation.plan_snapshot;
  const machine = typeof plan.machine === "object" && plan.machine ? plan.machine as Record<string, unknown> : {};
  const service = typeof plan.service === "object" && plan.service ? plan.service as Record<string, unknown> : {};
  const checks = Object.entries(operation.precheck_result).filter(([key]) => key !== "passed");
  const isDeploy = operation.action_type === "docker_compose_deploy";
  const isRollback = isDeploy && Boolean(operation.rollback_of);
  return {
    action: isRollback ? "显式回滚" : isDeploy ? "受控部署" : "安全重启",
    machine: String(machine.name ?? machine.hostname ?? operation.agent_id),
    service: String(service.name ?? operation.instance_id),
    environment: String(service.environment ?? "环境未知"),
    risk: operation.risk_level,
    expiresAt: operation.expires_at,
    passedPrechecks: checks.filter(([, passed]) => passed).length,
    failedPrechecks: checks.filter(([, passed]) => !passed).length,
  };
}
