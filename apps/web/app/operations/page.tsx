import Link from "next/link";
import React from "react";
import { PageHeader, Panel, StateView, StatusBadge } from "@/app/ui/primitives";
import { ControlPlaneApiError, getOperations } from "@/lib/api";
import { getPrincipalForwardHeaders } from "@/lib/principal";
import { operationStatus, operationStatuses, persistedAction, utcTime } from "@/lib/operation-presentation";
import styles from "./operations.module.css";

export const dynamic = "force-dynamic";
type Query = Record<string, string | string[] | undefined>;
const value = (input: string | string[] | undefined) => typeof input === "string" ? input : "";
function paramsFor(query: Query) {
  const params = new URLSearchParams({ limit: "50" });
  for (const key of ["status", "action_type", "agent_id", "requested_by", "confirmed_by", "since", "until", "cursor"]) {
    if (value(query[key])) params.set(key, value(query[key]));
  }
  return params;
}
export default async function OperationsPage({ searchParams }: { searchParams: Promise<Query> }) {
  const query = await searchParams;
  let page;
  try {
    page = await getOperations(paramsFor(query), await getPrincipalForwardHeaders() ?? undefined);
  } catch (error) {
    const code = error instanceof ControlPlaneApiError ? error.status : 0;
    return <main className={styles.workspace}>
      <PageHeader title="操作" eyebrow="事件与处置" />
      <StateView state={code === 401 || code === 403 ? "forbidden" : "error"}
        title={code === 401 || code === 403 ? "无权读取操作" : code === 422 ? "筛选或分页条件无效" : "操作列表暂时不可用"}
        description={code === 401 || code === 403 ? "请使用具备 operation:read 的可信身份。" : code === 422 ? "检查 UTC 时间范围，或重置筛选后重新翻页。" : "控制平面未返回记录，请稍后重新读取。"}>
        <Link href="/operations">重新读取操作列表</Link>
      </StateView>
    </main>;
  }
  const next = paramsFor(query);
  if (page.next_cursor) next.set("cursor", page.next_cursor);
  return <main className={styles.workspace}>
    <PageHeader title="操作" eyebrow="事件与处置" description="计划、独立审批、执行与健康验证。创建计划不等于确认执行。" />
    <Panel><form className={styles.filters} action="/operations" method="get" aria-label="筛选操作">
      <label>状态<select name="status" defaultValue={value(query.status)}><option value="">全部状态</option>{Object.entries(operationStatuses).map(([key, status]) => <option key={key} value={key}>{status.label}</option>)}{value(query.status) && !Object.hasOwn(operationStatuses, value(query.status)) && <option value={value(query.status)}>{value(query.status)}</option>}</select></label>
      <label>动作标识<input name="action_type" list="operation-action-types" maxLength={32} defaultValue={value(query.action_type)} placeholder="全部动作" /><datalist id="operation-action-types"><option value="docker_restart">安全重启</option><option value="docker_compose_deploy">部署及显式回滚</option></datalist></label>
      <label>机器 ID<input name="agent_id" maxLength={36} defaultValue={value(query.agent_id)} placeholder="全部机器" /></label>
      <label>请求者 ID<input name="requested_by" maxLength={128} defaultValue={value(query.requested_by)} placeholder="全部请求者" /></label>
      <label>审批者 ID<input name="confirmed_by" maxLength={128} defaultValue={value(query.confirmed_by)} placeholder="全部审批者" /></label>
      <label>起始时间（UTC）<input type="datetime-local" name="since" defaultValue={value(query.since)} /></label>
      <label>结束时间（UTC）<input type="datetime-local" name="until" defaultValue={value(query.until)} /></label>
      <div className={styles.actions}><button type="submit">应用筛选</button><Link href="/operations">重置</Link></div>
    </form></Panel>
    <p className={styles.muted}>共 {page.total} 项，当前显示 {page.items.length} 项 · 按计划创建时间从新到旧 · 目标来自冻结快照</p>
    {!page.items.length ? <StateView state="empty" title="没有匹配的操作" description="当前筛选范围没有记录。计划需从明确的事件或服务上下文创建。" /> :
      <div className={styles.list}>{page.items.map((item) => {
        const action = persistedAction(item.action_type, item.rollback_of);
        const status = operationStatus(item.status);
        return <Panel key={item.id} className={styles.item}>
          <header><StatusBadge tone={status.tone}>{status.label}</StatusBadge><span>风险 · {item.risk_level}</span></header>
          <h2><Link href={`/operations/${item.id}`}>{action.label} · {item.service}</Link></h2>
          <p>{item.impact_summary}</p>
          <dl className={styles.facts}>
            <div><dt>机器 / 环境</dt><dd>{item.machine} · {item.environment}</dd></div>
            <div><dt>请求者 / 审批者</dt><dd>{item.requested_by} / {item.confirmed_by ?? "尚未确认"}</dd></div>
            <div><dt>创建时间</dt><dd><time dateTime={item.requested_at}>{utcTime(item.requested_at)}</time></dd></div>
            <div><dt>有效期</dt><dd>{utcTime(item.expires_at)}</dd></div>
          </dl>
          {item.rollback_of && <p>回滚来源 <Link href={`/operations/${item.rollback_of}`}>{item.rollback_of}</Link></p>}
          <Link className={styles.detailLink} href={`/operations/${item.id}`}>查看计划、验证与审计 →</Link>
        </Panel>;
      })}</div>}
    {page.next_cursor && <nav className={styles.actions} aria-label="操作列表分页"><Link href={`/operations?${next.toString()}`}>下一页</Link></nav>}
  </main>;
}
