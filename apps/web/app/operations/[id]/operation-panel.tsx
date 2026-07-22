"use client";

import { Operation } from "@/lib/api";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

const active = new Set(["queued", "claimed", "running", "verifying"]);

export function OperationPanel({ operation }: { operation: Operation }) {
  const router = useRouter();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
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
  const plan = operation.plan_snapshot;
  const machine = typeof plan.machine === "object" && plan.machine ? plan.machine as Record<string, unknown> : {};
  const service = typeof plan.service === "object" && plan.service ? plan.service as Record<string, unknown> : {};
  if (operation.action_type === "docker_compose_deploy") return <>
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
      <h1>安全重启 · {String(service.name ?? "服务")}</h1>
      <p>{String(machine.name ?? machine.hostname ?? "机器")} · {String(service.environment ?? "环境未知")} · {operation.risk_level} risk</p>
      {operation.status === "awaiting_confirmation" && <button type="button" onClick={confirm} disabled={loading}>{loading ? "确认中…" : "确认并签发重启任务"}</button>}
      {error && <p className="mapping-error" role="alert">{error}</p>}
    </section>
    <section className="diagnostic"><h2>计划与影响</h2><p>{operation.impact_summary}</p><pre>{JSON.stringify(plan, null, 2)}</pre></section>
    <section className="diagnostic"><h2>前置检查</h2><div className="diagnostic-grid">{Object.entries(operation.precheck_result).filter(([key]) => key !== "passed").map(([key, passed]) => <article key={key}><strong>{passed ? "通过" : "拒绝"}</strong><p>{key}</p></article>)}</div><p>任务有效期至 {new Date(operation.expires_at).toLocaleString("zh-CN")}</p></section>
    <section className="diagnostic"><h2>健康验证</h2><pre>{JSON.stringify(operation.verification_result ?? operation.verification_policy, null, 2)}</pre>{operation.error_detail && <div className="empty error">{operation.error_code} · {operation.error_detail}</div>}{operation.output && <pre>{operation.output}{operation.output_truncated ? "\n[已截断]" : ""}</pre>}</section>
    <section className="diagnostic"><h2>审计时间线</h2>{operation.transitions.map((item, index) => <article key={`${item.created_at}-${index}`}><strong>{item.from_status ?? "created"} → {item.to_status}</strong><p>{item.actor_type}{item.actor_id ? ` · ${item.actor_id}` : ""}{item.reason ? ` · ${item.reason}` : ""}</p><time>{new Date(item.created_at).toLocaleString("zh-CN")}</time></article>)}</section>
  </>;
}
