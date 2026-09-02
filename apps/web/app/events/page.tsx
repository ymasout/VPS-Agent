import Link from "next/link";

import { PageHeader, Panel, StateView, StatusBadge } from "@/app/ui/primitives";
import {
  ControlPlaneApiError,
  getAgents,
  getEvents,
  getServiceInstances,
} from "@/lib/api";
import { getPrincipalForwardHeaders } from "@/lib/principal";
import styles from "./events.module.css";

export const dynamic = "force-dynamic";

function valueOf(value: string | string[] | undefined) {
  return typeof value === "string" ? value : "";
}

function eventParams(query: Record<string, string | string[] | undefined>) {
  const params = new URLSearchParams();
  for (const key of ["cursor", "status", "severity", "agent_id", "service_id", "since", "until", "q"]) {
    const value = valueOf(query[key]);
    if (value) params.set(key, value);
  }
  params.set("limit", "50");
  return params;
}

function eventTone(status: string, severity: string) {
  if (status === "resolved") return "success" as const;
  if (severity === "critical") return "danger" as const;
  if (severity === "warning") return "warning" as const;
  return "info" as const;
}

export default async function EventsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = await searchParams;
  const principalHeaders = await getPrincipalForwardHeaders();
  const headers = principalHeaders ?? undefined;
  const [eventsResult, agentsResult, servicesResult] = await Promise.allSettled([
    getEvents(eventParams(query), headers),
    getAgents(headers),
    getServiceInstances(new URLSearchParams({ mapping: "mapped", limit: "100" }), headers),
  ]);
  if (eventsResult.status === "rejected") {
    const forbidden = eventsResult.reason instanceof ControlPlaneApiError && eventsResult.reason.status === 403;
    return (
      <main className={styles.workspace}>
        <PageHeader eyebrow="事件与处置" title="事件" description="从真实控制平面记录定位异常、证据与处置历史。" />
        <StateView state={forbidden ? "forbidden" : "error"} title={forbidden ? "无权读取事件" : "事件列表暂时不可用"} description={forbidden ? "当前 Principal 不具备 event:read。" : "控制平面没有返回事件列表，本状态不会伪装成没有事件。"} />
      </main>
    );
  }
  const page = eventsResult.value;
  const agents = agentsResult.status === "fulfilled" ? agentsResult.value : [];
  const services = servicesResult.status === "fulfilled" ? servicesResult.value.items : [];
  const nextParams = eventParams(query);
  if (page.next_cursor) nextParams.set("cursor", page.next_cursor);

  return (
    <main className={styles.workspace}>
      <PageHeader eyebrow="事件与处置" title="事件" description="活动事件优先；已恢复事件仍保留诊断、会话、操作与复盘证据。" />
      <Panel as="div">
        <form className={styles.filters} action="/events" method="get" aria-label="筛选事件">
          <label>搜索<input name="q" defaultValue={valueOf(query.q)} placeholder="标题、机器或服务" /></label>
          <label>状态<select name="status" defaultValue={valueOf(query.status)}><option value="">全部状态</option><option value="firing">触发中</option><option value="pending">待确认</option><option value="acknowledged">已确认</option><option value="silenced">已静默</option><option value="resolved">已恢复</option></select></label>
          <label>严重度<select name="severity" defaultValue={valueOf(query.severity)}><option value="">全部严重度</option><option value="critical">严重</option><option value="warning">警告</option><option value="info">信息</option></select></label>
          <label>机器<select name="agent_id" defaultValue={valueOf(query.agent_id)}><option value="">全部机器</option>{agents.map((agent) => <option value={agent.id} key={agent.id}>{agent.name}</option>)}</select></label>
          <label>服务<select name="service_id" defaultValue={valueOf(query.service_id)}><option value="">全部服务</option>{services.filter((item) => item.service_name && item.instance_id).map((item) => <option value={item.service_id ?? ""} key={item.inventory_id}>{item.service_name} · {item.agent_name}</option>)}</select></label>
          <label>起始时间<input type="datetime-local" name="since" defaultValue={valueOf(query.since)} /></label>
          <label>结束时间<input type="datetime-local" name="until" defaultValue={valueOf(query.until)} /></label>
          <div className={styles.actions}><button type="submit">应用筛选</button><Link href="/events">重置</Link></div>
        </form>
      </Panel>
      <div className={styles.summary}><span>共 <strong>{page.total}</strong> 项，当前显示 {page.items.length} 项</span><span>状态、严重度和时间均来自控制平面当前记录</span></div>
      {page.items.length === 0 ? (
        <StateView state="empty" title="没有匹配的事件" description="当前筛选范围内没有事件；调整条件不会触发诊断或写操作。" />
      ) : (
        <div className={styles.list}>
          {page.items.map((event) => (
            <Panel className={styles.event} key={event.id}>
              <div className={styles.eventMain}>
                <header><StatusBadge tone={eventTone(event.status, event.severity)}>{event.status} · {event.severity}</StatusBadge><h2><Link href={`/events/${event.id}`}>{event.title}</Link></h2></header>
                <p>{event.detail ?? "当前事件没有额外安全摘要。"}</p>
                <div className={styles.meta}><span>{event.agent_name}</span><span>{event.service_name ?? event.source}</span><span>观测 {event.observation_count} 次</span></div>
              </div>
              <div className={styles.observed}><time dateTime={event.last_observed_at}>{new Date(event.last_observed_at).toISOString().replace("T", " ").slice(0, 19)} UTC</time><Link href={`/events/${event.id}`}>查看事件</Link></div>
            </Panel>
          ))}
        </div>
      )}
      {page.next_cursor && <nav className={styles.pagination} aria-label="事件列表分页"><Link href={`/events?${nextParams.toString()}`}>下一页</Link></nav>}
    </main>
  );
}
