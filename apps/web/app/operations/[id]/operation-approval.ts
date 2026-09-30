import type { Operation } from "@/lib/api";
import { persistedAction, displayValue } from "../../../lib/operation-presentation";

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
  return {
    action: persistedAction(operation.action_type, operation.rollback_of).label,
    machine: displayValue(machine.name ?? machine.hostname, operation.agent_id),
    service: displayValue(service.name, operation.instance_id),
    environment: displayValue(service.environment, "环境未知"),
    risk: operation.risk_level,
    expiresAt: operation.expires_at,
    passedPrechecks: checks.filter(([, passed]) => passed === true).length,
    failedPrechecks: checks.filter(([, passed]) => passed === false).length,
  };
}
