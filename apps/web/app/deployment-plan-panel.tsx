"use client";

import { DeploymentCandidate } from "@/lib/api";
import { FormEvent, useState } from "react";

const reasonLabels: Record<string, string> = {
  multiple_replicas: "不是单副本服务",
  healthcheck_missing: "镜像没有 healthcheck",
  digest_unresolved: "无法解析当前 RepoDigest",
  digest_ambiguous: "当前仓库对应多个 RepoDigest",
  repository_unresolved: "无法标准化当前镜像仓库",
  inspect_failed: "Docker 元数据读取失败",
  compose_metadata_invalid: "Compose 本地元数据不可验证",
  compose_path_untrusted: "Compose 路径不在 Agent 允许目录",
  compose_config_drift: "运行容器与安全 Compose 基线不一致",
  drift_rejected: "容器、单副本或当前镜像在执行前发生漂移",
};

export function DeploymentPlanPanel({ candidates }: { candidates: DeploymentCandidate[] }) {
  const [targets, setTargets] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState("");
  const [error, setError] = useState("");
  const [deployEnabled, setDeployEnabled] = useState<Record<string, boolean>>(
    Object.fromEntries(candidates.map((candidate) => [candidate.service_key, candidate.deploy_enabled])),
  );

  async function createPlan(event: FormEvent, candidate: DeploymentCandidate) {
    event.preventDefault();
    if (!candidate.instance_id) return;
    setLoading(candidate.service_key);
    setError("");
    try {
      const executable = candidate.deploy_capable && deployEnabled[candidate.service_key];
      const response = await fetch(executable ? "/console/deployment-operations" : "/console/deployment-plans", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          instance_id: candidate.instance_id,
          target_digest: targets[candidate.service_key] ?? "",
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "创建部署计划失败");
      window.location.assign(`/operations/${payload.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建部署计划失败");
    } finally {
      setLoading("");
    }
  }

  async function enableDeploy(candidate: DeploymentCandidate) {
    if (!candidate.instance_id) return;
    setLoading(candidate.service_key);
    setError("");
    try {
      const response = await fetch(`/console/service-instances/${candidate.instance_id}/deploy-policy`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ enabled: true, criticality: "non_critical" }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "部署授权失败");
      setDeployEnabled((current) => ({ ...current, [candidate.service_key]: true }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "部署授权失败");
    } finally {
      setLoading("");
    }
  }

  return (
    <section className="section">
      <div className="section-title"><h2>M4.2 部署计划</h2><span>EXPLICIT OPT-IN</span></div>
      <p className="section-copy">plan-only 仍只生成永久不可执行快照；只有 Agent 显式声明执行能力且控制台单独授权后，才会创建需再次确认的签名部署操作。</p>
      {candidates.length === 0 && <div className="empty"><strong>没有部署候选</strong><span>Agent 必须显式启用 deploy policy: plan-only。</span></div>}
      <div className="mapping-list">
        {candidates.map((candidate) => {
          const serviceHealthy = candidate.state === "running" && candidate.healthy === true;
          const allowed = candidate.eligible && candidate.mapped && candidate.criticality === "non_critical" && serviceHealthy && Boolean(candidate.instance_id);
          const executable = candidate.deploy_capable && deployEnabled[candidate.service_key];
          const reason = candidate.reason_code ? reasonLabels[candidate.reason_code] ?? candidate.reason_code : !candidate.mapped ? "尚未映射到服务" : candidate.criticality !== "non_critical" ? "服务未标记为 non_critical" : !serviceHealthy ? "服务当前不是 running + healthy" : executable ? "可创建受控部署操作" : candidate.deploy_capable ? "Agent 已授权，控制台尚未授权" : "可创建只读计划";
          return (
            <form className="mapping-card" key={`${candidate.service_kind}:${candidate.service_key}`} onSubmit={(event) => createPlan(event, candidate)}>
              <header><div><span>{allowed ? "READY" : "BLOCKED"}</span><strong>{candidate.service_name ?? candidate.service_key}</strong></div><small>{reason}</small></header>
              <p className="section-copy">{candidate.current_digest ?? candidate.repository ?? "当前 digest 不可用"}</p>
              <label htmlFor={`target-${candidate.service_key}`}>目标 repo@sha256 digest</label>
              <input id={`target-${candidate.service_key}`} value={targets[candidate.service_key] ?? ""} onChange={(event) => setTargets((current) => ({ ...current, [candidate.service_key]: event.target.value }))} placeholder={candidate.repository ? `${candidate.repository}@sha256:...` : "不可创建计划"} maxLength={512} disabled={!allowed} required />
              {candidate.deploy_capable && !deployEnabled[candidate.service_key] && allowed && <button type="button" onClick={() => enableDeploy(candidate)} disabled={loading === candidate.service_key}>{loading === candidate.service_key ? "授权中…" : "显式授权此服务部署"}</button>}
              <button type="submit" disabled={!allowed || loading === candidate.service_key}>{loading === candidate.service_key ? "创建中…" : executable ? "创建待确认部署操作" : "创建只读计划"}</button>
            </form>
          );
        })}
      </div>
      {error && <p className="mapping-error" role="alert">{error}</p>}
    </section>
  );
}
