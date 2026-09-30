"use client";

import React, { useEffect, useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { Operation } from "@/lib/api";
import { PageHeader, StatusBadge } from "../../ui/primitives";
import { displayValue, operationPresentation, operationStatus, record, utcTime, verificationSummary } from "../../../lib/operation-presentation";
import { operationApprovalSummary } from "./operation-approval";
import styles from "../operations.module.css";

const active = new Set(["planned", "prechecking", "awaiting_confirmation", "queued", "claimed", "running", "verifying"]);
export function OperationPanel({
  operation, observedAt = operation.requested_at, namedAuthorization = false,
  canApprove = false, canPlan = false, currentPrincipalId = null,
}: {
  operation: Operation; observedAt?: string; namedAuthorization?: boolean;
  canApprove?: boolean; canPlan?: boolean; currentPrincipalId?: string | null;
}) {
  const router = useRouter();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [online, setOnline] = useState(false);
  const [now, setNow] = useState(Date.parse(observedAt));
  const [refreshing, startRefresh] = useTransition();
  const access = { namedAuthorization, canApprove, canPlan, currentPrincipalId };
  const presentation = operationPresentation(operation, access, now);
  const fresh = Number.isFinite(Date.parse(observedAt)) && now - Date.parse(observedAt) < 20000;
  const reviewKey = JSON.stringify([operation, access]);
  useEffect(() => {
    const update = () => { setOnline(navigator.onLine); setAcknowledged(false); setNow(Date.now()); };
    update();
    const clock = window.setInterval(() => setNow(Date.now()), 1000);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.clearInterval(clock);
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);
  useEffect(() => setAcknowledged(false), [reviewKey]);
  useEffect(() => {
    if (!fresh || !presentation.canConfirm) setAcknowledged(false);
  }, [fresh, presentation.canConfirm]);
  useEffect(() => {
    if (!active.has(operation.status) || !online || refreshing) return;
    const timer = window.setInterval(() => startRefresh(() => router.refresh()), 5000);
    return () => window.clearInterval(timer);
  }, [operation.status, online, refreshing, router]);
  useEffect(() => {
    if (presentation.actionFamily === "unknown" || operationStatus(operation.status).label.startsWith("未知")) {
      // Fixed event only: never log snapshots, output, identity or untrusted type text.
      console.warn("operation_presentation_unknown");
    }
  }, [presentation.actionFamily, operation.status]);

  async function confirm() {
    if (loading || !acknowledged || !navigator.onLine || refreshing ||
        Date.now() - Date.parse(observedAt) >= 20000 ||
        !operationPresentation(operation, access, Date.now()).canConfirm) return;
    setLoading(true);
    setAcknowledged(false);
    setError("");
    try {
      const response = await fetch(
        namedAuthorization ? `/api/v1/operations/${operation.id}/confirm` : `/console/operations/${operation.id}/confirm`,
        { method: "POST", headers: namedAuthorization ? { "content-type": "application/json" } : undefined },
      );
      if (!response.ok) {
        setError(response.status === 409 ? "状态已变化，请重新核对最新计划。" : "确认被拒绝或未完成，请重新读取状态。");
      }
    } catch {
      setError("连接中断，确认结果未知。请重新读取状态；不会自动重放。");
    } finally {
      startRefresh(() => router.refresh());
      setLoading(false);
    }
  }
  async function createRollback() {
    if (loading || !navigator.onLine || refreshing || !fresh ||
        !operationPresentation(operation, access, Date.now()).canCreateFollowUp) return;
    setLoading(true);
    setError("");
    try {
      const response = await fetch(
        namedAuthorization ? `/api/v1/deployment-operations/${operation.id}/rollback` : `/console/deployment-operations/${operation.id}/rollback`,
        { method: "POST", headers: namedAuthorization ? { "content-type": "application/json" } : undefined,
          body: namedAuthorization ? JSON.stringify({ expires_in_seconds: 300 }) : undefined },
      );
      if (!response.ok) { setError("创建回滚计划未完成，请重新读取记录后核对。"); return; }
      const payload = await response.json();
      if (typeof payload.id !== "string" || !/^[a-zA-Z0-9-]{1,36}$/.test(payload.id)) {
        setError("计划响应不可验证，请返回操作列表核对。"); return;
      }
      router.push("/operations/" + payload.id);
    } catch {
      setError("连接中断，计划创建结果未知。请先检查操作列表；不会自动重放。");
    } finally { setLoading(false); }
  }
  const approval = operationApprovalSummary(operation);
  const plan = operation.plan_snapshot;
  const requested = record(operation.requested_principal_snapshot);
  const confirmed = record(operation.confirmed_principal_snapshot);
  const checks = Object.entries(operation.precheck_result).filter(([key]) => key !== "passed");
  const verification = operation.verification_result;
  const sectionLabels = { summary: "计划与影响", prechecks: "前置检查", verification: "健康验证", audit: "审计时间线", technical: "技术详情" };
  return <div className={styles.workspace}>
    <PageHeader eyebrow="操作详情" title={presentation.actionLabel + " · " + presentation.target.service}
      description={presentation.target.machine + " · " + presentation.target.environment + " · 风险 " + presentation.risk} />
    <div className={styles.headline}>
      <span role="status" aria-live="polite"><StatusBadge tone={presentation.statusTone}>{presentation.statusLabel}</StatusBadge></span>
      <span className={styles.muted}>记录读取于 {utcTime(observedAt)} · {operation.authorization_mode}</span>
    </div>
    <nav className={styles.sectionNav} aria-label="操作详情分区">
      {presentation.sections.map((id) => <a key={id} href={"#" + id}>{sectionLabels[id]}</a>)}
    </nav>
    {(!online || !fresh) && <p className="approval-offline" role="status">{!online ? "当前离线或正在确认连接。审批不会排队，请恢复网络并重新核对最新状态。" : "状态刷新中断，当前为最后快照；写入控件已关闭。"}</p>}
    <div className={styles.actions}><button type="button" onClick={() => startRefresh(() => router.refresh())} disabled={refreshing || !online}>{refreshing ? "正在刷新…" : "刷新状态"}</button></div>
    {presentation.confirmationReason && <p className={styles.muted}>{presentation.confirmationReason}</p>}
    {error && <p className="mapping-error" role="alert">{error}</p>}

    {operation.status === "awaiting_confirmation" && presentation.actionFamily !== "unknown" && (
      <section className="operation-approval" aria-labelledby="operation-approval-title">
        <header><h2 id="operation-approval-title">核对后确认</h2><StatusBadge tone="warning">风险 · {approval.risk}</StatusBadge></header>
        <div className="approval-grid">
          <div><span>动作</span><strong>{approval.action}</strong></div>
          <div><span>机器</span><strong>{approval.machine}</strong></div>
          <div><span>服务 / 环境</span><strong>{approval.service} · {approval.environment}</strong></div>
          <div><span>有效期</span><strong>{utcTime(approval.expiresAt)}</strong></div>
          <div><span>前置检查</span><strong>{approval.passedPrechecks} 通过 · {approval.failedPrechecks} 拒绝</strong></div>
        </div>
        <p className="approval-warning">创建计划不等于确认。确认后服务端仍会检查状态与有效期，签发任务，并等待 Agent 执行和独立健康验证；不会自动回滚。</p>
        {presentation.canConfirm && <>
          <label className="approval-check"><input type="checkbox" checked={acknowledged} disabled={!online || !fresh || loading} onChange={(event) => setAcknowledged(event.target.checked)} />
            <span>我已核对目标、动作、风险和有效期，并确认这是本次独立人工授权。</span></label>
          <button className="approval-submit" type="button" onClick={confirm} disabled={loading || refreshing || !acknowledged || !online || !fresh}>
            {loading ? "确认中…" : "确认并签发" + approval.action + "任务"}
          </button>
        </>}
      </section>
    )}
    <section id="summary" className={"ui-panel " + styles.section}>
      <h2>计划与影响</h2><p>{operation.impact_summary}</p>
      <dl className={styles.facts}>
        <div><dt>请求者</dt><dd>{displayValue(requested.display_name, operation.requested_by)} · {operation.requested_by}</dd></div>
        <div><dt>审批者</dt><dd>{displayValue(confirmed.display_name, operation.confirmed_by ?? "尚未确认")} · {operation.confirmed_by ?? "—"}</dd></div>
        <div><dt>创建时间</dt><dd>{utcTime(operation.requested_at)}</dd></div>
        <div><dt>完成时间</dt><dd>{utcTime(operation.completed_at)}</dd></div>
        <div><dt>动作标识</dt><dd>{operation.action_type}</dd></div>
        <div><dt>有效期</dt><dd>{utcTime(operation.expires_at)}</dd></div>
      </dl>
      {(presentation.actionFamily === "deploy" || presentation.actionFamily === "rollback") && <dl className={styles.facts}>
        <div><dt>当前镜像</dt><dd>{operation.current_digest ?? "未冻结"}</dd></div><div><dt>目标镜像</dt><dd>{operation.target_digest ?? "未冻结"}</dd></div>
      </dl>}
      {operation.source_event_id && <Link className={styles.detailLink} href={"/events/" + operation.source_event_id}>查看来源事件</Link>}
      {operation.source_conversation_turn_id && <p>来源：事件会话显式交接 · 轮次 {operation.source_conversation_turn_id}。创建计划不等于确认执行。</p>}
      {presentation.rollbackOf && <p>独立回滚来源 <Link href={"/operations/" + presentation.rollbackOf}>{presentation.rollbackOf}</Link>；本次仍需确认与健康验证。</p>}
      {presentation.canCreateFollowUp && <div className={styles.actions}><button type="button" onClick={createRollback} disabled={loading || refreshing || !online || !fresh}>创建显式回滚计划</button><p>只创建计划；新计划仍需独立确认。</p></div>}
    </section>
    <section id="prechecks" className={"ui-panel " + styles.section}>
      <h2>前置检查</h2><p className={styles.muted}>冻结的检查记录；确认时服务端会再次预检。</p>
      {checks.length ? <ul className={styles.checks}>{checks.map(([key, passed]) => <li key={key}><StatusBadge tone={passed === true ? "success" : passed === false ? "warning" : "neutral"}>{passed === true ? "通过" : passed === false ? "拒绝" : "未知"}</StatusBadge><span>{key}</span></li>)}</ul> : <p>尚无前置检查记录。</p>}
    </section>
    <section id="verification" className={"ui-panel " + styles.section}>
      <h2>健康验证</h2><p>{verificationSummary(verification)}</p>
      <p className={styles.muted}>命令退出码 {operation.exit_code ?? "未返回"}；退出码为 0 不代表服务健康验证通过。</p>
      <dl className={styles.facts}>{["observed_at", "first_healthy_at", "last_healthy_at", "state", "healthy"].filter((key) => verification?.[key] !== undefined).map((key) => <div key={key}><dt>{({ observed_at: "观测时间", first_healthy_at: "首次健康", last_healthy_at: "最近健康", state: "观测状态", healthy: "健康" })[key]}</dt><dd>{typeof verification?.[key] === "boolean" ? verification[key] ? "是" : "否" : displayValue(verification?.[key])}</dd></div>)}</dl>
      {operation.error_code && <p role="status">错误标识：{operation.error_code} · {operation.error_detail}</p>}
      <details><summary>查看冻结验证条件</summary><pre>{JSON.stringify(operation.verification_policy, null, 2)}</pre></details>
    </section>
    <section id="audit" className={"ui-panel " + styles.section}>
      <h2>审计时间线</h2>
      {operation.transitions.length ? <ol className={styles.timeline}>{operation.transitions.map((item, index) => <li key={item.created_at + index}>
        <strong>{item.from_status ? operationStatus(item.from_status).label : "创建"} → {operationStatus(item.to_status).label}</strong>
        <p>{displayValue(record(item.actor_principal_snapshot).display_name, item.actor_id ?? item.actor_type)} · {item.actor_type}{item.reason ? " · " + item.reason : ""}</p>
        <time dateTime={item.created_at}>{utcTime(item.created_at)}</time>
      </li>)}</ol> : <p>尚无转换记录。</p>}
    </section>
    <section id="technical" className={"ui-panel " + styles.section}>
      <h2>技术详情</h2><p className={styles.muted}>控制平面提供的冻结快照和有界结果，仅供核对。</p>
      <details><summary>冻结计划</summary><pre>{JSON.stringify(plan, null, 2)}</pre></details>
      <details><summary>验证结果</summary><pre>{JSON.stringify(verification, null, 2)}</pre></details>
      <details><summary>执行结果{operation.output_truncated ? "（已截断）" : ""}</summary><pre>{operation.output ?? "尚无执行输出"}</pre></details>
      <details><summary>完整转换记录</summary><pre>{JSON.stringify(operation.transitions, null, 2)}</pre></details>
    </section>
  </div>;
}
