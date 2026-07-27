"use client";

import React from "react";
import { Operation } from "@/lib/api";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { operationApprovalSummary } from "./operation-approval";

const active = new Set(["queued", "claimed", "running", "verifying"]);

export function OperationPanel({ operation }: { operation: Operation }) {
  const router = useRouter();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [online, setOnline] = useState(true);
  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    update();
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);
  useEffect(() => setAcknowledged(false), [operation.id, operation.status]);
  useEffect(() => {
    if (!active.has(operation.status)) return;
    const timer = window.setInterval(() => router.refresh(), 3000);
    return () => window.clearInterval(timer);
  }, [operation.status, router]);
  async function confirm() {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`/console/operations/${operation.id}/confirm`, { method: "POST" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "确认失败");
      router.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "确认失败");
    } finally {
      setLoading(false);
    }
  }
  async function createRollback() {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`/console/deployment-operations/${operation.id}/rollback`, { method: "POST" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "创建回滚计划失败");
      router.push(`/operations/${payload.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建回滚计划失败");
    } finally {
      setLoading(false);
    }
  }
  const plan = operation.plan_snapshot;
  const machine = typeof plan.machine === "object" && plan.machine ? plan.machine as Record<string, unknown> : {};
  const service = typeof plan.service === "object" && plan.service ? plan.service as Record<string, unknown> : {};
  const isDeploy = operation.action_type === "docker_compose_deploy";
  const conversationSource =
    typeof plan.conversation_source === "object" && plan.conversation_source
      ? (plan.conversation_source as Record<string, unknown>)
      : null;
  const isPlanOnly = isDeploy && plan.permanently_non_executable === true;
  const isRollback = isDeploy && Boolean(operation.rollback_of);
  const approval = operationApprovalSummary(operation);
  const canCreateRollback = isDeploy && !isRollback && plan.plan_version === "m4.2b-executable-v1" && operation.status === "failed" && operation.started_at !== null;
  if (isPlanOnly) return <>
    <section className="hero compact detail-head event-head">
      <div className="status"><span /> PLAN ONLY</div>
      <h1>只读部署计划 · {String(service.name ?? "服务")}</h1>
      <p>{String(machine.name ?? machine.hostname ?? "机器")} · {String(service.environment ?? "环境未知")} · {operation.risk_level} risk</p>
      <p className="section-copy">此 M4.2a 快照永久不可确认、排队或执行。M4.2b 必须重新创建可执行计划。</p>
    </section>
    <section className="diagnostic"><h2>冻结镜像计划</h2><p>{operation.impact_summary}</p><pre>{JSON.stringify(plan, null, 2)}</pre></section>
    <section className="diagnostic"><h2>只读前置检查</h2><div className="diagnostic-grid">{Object.entries(operation.precheck_result).filter(([key]) => key !== "passed").map(([key, passed]) => <article key={key}><strong>{passed ? "通过" : "拒绝"}</strong><p>{key}</p></article>)}</div></section>
    <section className="diagnostic"><h2>未来验证条件</h2><pre>{JSON.stringify(operation.verification_policy, null, 2)}</pre></section>
    <section className="diagnostic"><h2>审计时间线</h2>{operation.transitions.map((item, index) => <article key={`${item.created_at}-${index}`}><strong>{item.from_status ?? "created"} → {item.to_status}</strong><p>{item.actor_type}{item.actor_id ? ` · ${item.actor_id}` : ""}{item.reason ? ` · ${item.reason}` : ""}</p><time>{new Date(item.created_at).toLocaleString("zh-CN")}</time></article>)}</section>
  </>;
  return <>
    <section className="hero compact detail-head event-head">
      <div className={`status ${operation.status === "succeeded" ? "" : "offline"}`}><span /> {operation.status}</div>
      <h1>{isRollback ? "显式回滚" : isDeploy ? "受控部署" : "安全重启"} · {String(service.name ?? "服务")}</h1>
      <p>{String(machine.name ?? machine.hostname ?? "机器")} · {String(service.environment ?? "环境未知")} · {operation.risk_level} risk</p>
      {conversationSource && (
        <p className="section-copy">
          来源：事件会话显式交接 · 轮次{" "}
          {String(
            conversationSource.turn_id ??
              operation.source_conversation_turn_id ??
              "已删除",
          )}
          。创建计划不等于确认执行。
        </p>
      )}
      {isRollback && <p className="section-copy">独立回滚失败部署 {operation.rollback_of}；仍需本次人工确认并通过独立健康验证。</p>}
      {canCreateRollback && <button type="button" onClick={createRollback} disabled={loading}>{loading ? "创建中…" : "创建显式回滚计划"}</button>}
      {error && operation.status !== "awaiting_confirmation" && <p className="mapping-error" role="alert">{error}</p>}
    </section>
    {operation.status === "awaiting_confirmation" && (
      <section className="operation-approval" aria-labelledby="operation-approval-title">
        <header>
          <div><span className="eyebrow">INDEPENDENT CONFIRMATION</span><h2 id="operation-approval-title">核对后确认</h2></div>
          <strong className={`risk-badge risk-${approval.risk.toLowerCase()}`}>{approval.risk} risk</strong>
        </header>
        <div className="approval-grid">
          <div><span>动作</span><strong>{approval.action}</strong></div>
          <div><span>机器</span><strong>{approval.machine}</strong></div>
          <div><span>服务 / 环境</span><strong>{approval.service} · {approval.environment}</strong></div>
          <div><span>有效期</span><strong>{new Date(approval.expiresAt).toLocaleString("zh-CN")}</strong></div>
          <div><span>前置检查</span><strong>{approval.passedPrechecks} 通过 · {approval.failedPrechecks} 拒绝</strong></div>
        </div>
        <p className="approval-warning">创建计划不等于确认。确认后服务端仍会检查状态与有效期，签发任务，并等待 Agent 执行和独立健康验证；不会自动回滚。</p>
        {!online && <p className="approval-offline" role="alert">当前离线。审批不会排队，请恢复网络并重新核对最新状态。</p>}
        <label className="approval-check">
          <input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} />
          <span>我已核对目标、动作、风险和有效期，并确认这是本次独立人工授权。</span>
        </label>
        <button className="approval-submit" type="button" onClick={confirm} disabled={loading || !acknowledged || !online}>
          {loading ? "确认中…" : `确认并签发${approval.action}任务`}
        </button>
        {error && <p className="mapping-error" role="alert">{error}</p>}
      </section>
    )}
    <section className="diagnostic"><h2>计划与影响</h2><p>{operation.impact_summary}</p><pre>{JSON.stringify(plan, null, 2)}</pre></section>
    <section className="diagnostic"><h2>前置检查</h2><div className="diagnostic-grid">{Object.entries(operation.precheck_result).filter(([key]) => key !== "passed").map(([key, passed]) => <article key={key}><strong>{passed ? "通过" : "拒绝"}</strong><p>{key}</p></article>)}</div><p>任务有效期至 {new Date(operation.expires_at).toLocaleString("zh-CN")}</p></section>
    <section className="diagnostic"><h2>健康验证</h2><pre>{JSON.stringify(operation.verification_result ?? operation.verification_policy, null, 2)}</pre>{operation.error_detail && <div className="empty error">{operation.error_code} · {operation.error_detail}</div>}{operation.output && <pre>{operation.output}{operation.output_truncated ? "\n[已截断]" : ""}</pre>}</section>
    <section className="diagnostic"><h2>审计时间线</h2>{operation.transitions.map((item, index) => <article key={`${item.created_at}-${index}`}><strong>{item.from_status ?? "created"} → {item.to_status}</strong><p>{item.actor_type}{item.actor_id ? ` · ${item.actor_id}` : ""}{item.reason ? ` · ${item.reason}` : ""}</p><time>{new Date(item.created_at).toLocaleString("zh-CN")}</time></article>)}</section>
  </>;
}
