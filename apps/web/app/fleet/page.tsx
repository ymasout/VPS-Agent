import Link from "next/link";

import { ControlPlaneApiError, getAgents } from "@/lib/api";
import { getPrincipalForwardHeaders } from "@/lib/principal";
import { PageHeader, Panel, StateView, StatusBadge } from "@/app/ui/primitives";
import styles from "../infrastructure.module.css";

export const dynamic = "force-dynamic";

function valueOf(value: string | string[] | undefined) {
  return typeof value === "string" ? value : "";
}

function relativeTime(value: string | null) {
  if (!value) return "从未上报";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value)) + " UTC";
}

export default async function FleetPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = await searchParams;
  const search = valueOf(query.q).trim().toLowerCase();
  const status = valueOf(query.status);
  const platform = valueOf(query.platform).trim().toLowerCase();
  const attention = valueOf(query.attention);
  const principalHeaders = await getPrincipalForwardHeaders();
  let agents;
  try {
    agents = await getAgents(principalHeaders ?? undefined);
  } catch (error) {
    const forbidden = error instanceof ControlPlaneApiError && error.status === 403;
    return (
      <main className={styles.workspace}>
        <PageHeader eyebrow="基础设施" title="Fleet" description="机器身份、在线状态、平台、版本与待处理问题。" />
        <StateView
          state={forbidden ? "forbidden" : "error"}
          title={forbidden ? "无权读取 Fleet" : "Fleet 暂时不可用"}
          description={forbidden ? "当前 Principal 不具备 fleet:read。" : "无法从控制平面读取机器列表，请稍后重试。"}
        />
      </main>
    );
  }
  const platforms = Array.from(new Set(agents.map((agent) => `${agent.os} · ${agent.arch}`))).sort();
  const filtered = agents.filter((agent) => {
    const matchesSearch = !search || `${agent.name} ${agent.hostname} ${agent.version}`.toLowerCase().includes(search);
    const matchesStatus = status === "online" ? agent.online : status === "offline" ? !agent.online : true;
    const matchesPlatform = !platform || `${agent.os} · ${agent.arch}`.toLowerCase() === platform;
    const matchesAttention = attention !== "problems" || agent.service_problem_count > 0;
    return matchesSearch && matchesStatus && matchesPlatform && matchesAttention;
  });

  return (
    <main className={styles.workspace}>
      <PageHeader eyebrow="基础设施" title="Fleet" description="查看真实 Agent 心跳、平台、版本与服务问题；详情页保留原有深链。" />
      <Panel as="div">
        <form className={styles.filters} action="/fleet" method="get" aria-label="筛选 Fleet">
          <label>搜索机器<input name="q" defaultValue={valueOf(query.q)} placeholder="名称、主机名或版本" /></label>
          <label>状态<select name="status" defaultValue={status}><option value="">全部状态</option><option value="online">在线</option><option value="offline">离线</option></select></label>
          <label>平台<select name="platform" defaultValue={valueOf(query.platform)}><option value="">全部平台</option>{platforms.map((item) => <option value={item} key={item}>{item}</option>)}</select></label>
          <label>问题<select name="attention" defaultValue={attention}><option value="">全部机器</option><option value="problems">仅需关注</option></select></label>
          <div className={styles.filterActions}><button type="submit">应用筛选</button><Link href="/fleet">重置</Link></div>
        </form>
      </Panel>
      <div className={styles.resultSummary}><span>显示 <strong>{filtered.length}</strong> / {agents.length} 台机器</span><span>在线 {agents.filter((agent) => agent.online).length} · 离线 {agents.filter((agent) => !agent.online).length}</span></div>
      {filtered.length === 0 ? (
        <StateView state="empty" title="没有匹配的机器" description={agents.length ? "调整筛选条件后重试。" : "控制平面尚未收到任何 Agent 注册与上报。"} />
      ) : (
        <Panel as="div" className={styles.tableWrap}>
          <table className={styles.table}>
            <thead><tr><th>机器</th><th>状态</th><th>平台</th><th>Agent 版本</th><th>最后心跳</th><th>服务问题</th></tr></thead>
            <tbody>{filtered.map((agent) => (
              <tr key={agent.id}>
                <td><div className={styles.identity}><Link className={styles.rowLink} href={`/servers/${agent.id}`}>{agent.name}</Link><span>{agent.hostname}</span></div></td>
                <td><StatusBadge tone={agent.online ? "success" : "danger"}>{agent.online ? "在线" : "离线"}</StatusBadge></td>
                <td>{agent.os} · {agent.arch}</td>
                <td><span className={styles.meta}>{agent.version}</span></td>
                <td><time dateTime={agent.last_seen_at ?? undefined}>{relativeTime(agent.last_seen_at)}</time></td>
                <td><StatusBadge tone={agent.service_problem_count ? "warning" : "success"}>{agent.service_problem_count ? `${agent.service_problem_count} 项` : "无"}</StatusBadge></td>
              </tr>
            ))}</tbody>
          </table>
        </Panel>
      )}
    </main>
  );
}
