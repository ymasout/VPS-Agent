import Link from "next/link";

import { ControlPlaneApiError, getAgents, getServiceInstances } from "@/lib/api";
import { getPrincipalForwardHeaders } from "@/lib/principal";
import { PageHeader, Panel, StateView, StatusBadge } from "@/app/ui/primitives";
import styles from "../infrastructure.module.css";

export const dynamic = "force-dynamic";

function valueOf(value: string | string[] | undefined) {
  return typeof value === "string" ? value : "";
}

function inventoryParams(query: Record<string, string | string[] | undefined>) {
  const params = new URLSearchParams();
  for (const key of ["cursor", "agent_id", "service_kind", "environment", "health", "mapping", "q"]) {
    const value = valueOf(query[key]);
    if (value) params.set(key, value);
  }
  params.set("limit", "50");
  return params;
}

function healthTone(healthy: boolean | null) {
  return healthy === true ? "success" : healthy === false ? "danger" : "neutral";
}

export default async function ServicesPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = await searchParams;
  const principalHeaders = await getPrincipalForwardHeaders();
  const headers = principalHeaders ?? undefined;
  const [inventoryResult, agentsResult] = await Promise.allSettled([
    getServiceInstances(inventoryParams(query), headers),
    getAgents(headers),
  ]);
  if (inventoryResult.status === "rejected") {
    const forbidden = inventoryResult.reason instanceof ControlPlaneApiError && inventoryResult.reason.status === 403;
    return (
      <main className={styles.workspace}>
        <PageHeader eyebrow="基础设施" title="服务" description="跨机器查看服务状态、映射与能力摘要。" />
        <StateView state={forbidden ? "forbidden" : "error"} title={forbidden ? "无权读取服务" : "服务清单暂时不可用"} description={forbidden ? "当前 Principal 不具备 fleet:read。" : "控制平面没有返回服务清单，请稍后重试。"} />
      </main>
    );
  }
  const inventory = inventoryResult.value;
  const agents = agentsResult.status === "fulfilled" ? agentsResult.value : [];
  const environments = Array.from(new Set([
    "production",
    "staging",
    "development",
    ...inventory.items.map((item) => item.environment).filter((item): item is string => Boolean(item)),
    valueOf(query.environment),
  ].filter(Boolean))).sort();
  const nextParams = inventoryParams(query);
  if (inventory.next_cursor) nextParams.set("cursor", inventory.next_cursor);

  return (
    <main className={styles.workspace}>
      <PageHeader eyebrow="基础设施" title="服务" description="跨机器服务清单只展示控制平面已观测的稳定摘要，不暴露容器 ID、Unit 参数或任意执行目标。" />
      <Panel as="div">
        <form className={styles.filters} action="/services" method="get" aria-label="筛选服务">
          <label>搜索服务<input name="q" defaultValue={valueOf(query.q)} placeholder="服务或机器名称" /></label>
          <label>机器<select name="agent_id" defaultValue={valueOf(query.agent_id)}><option value="">全部机器</option>{agents.map((agent) => <option value={agent.id} key={agent.id}>{agent.name}</option>)}</select></label>
          <label>类型<select name="service_kind" defaultValue={valueOf(query.service_kind)}><option value="">全部类型</option><option value="docker">Docker</option><option value="systemd">systemd</option><option value="http">HTTP</option></select></label>
          <label>健康<select name="health" defaultValue={valueOf(query.health)}><option value="">全部健康状态</option><option value="healthy">健康</option><option value="unhealthy">异常</option><option value="unknown">未知</option></select></label>
          <label>映射<select name="mapping" defaultValue={valueOf(query.mapping)}><option value="">全部映射状态</option><option value="mapped">已映射</option><option value="unmapped">待映射</option></select></label>
          <label>环境<input name="environment" list="service-environments" defaultValue={valueOf(query.environment)} placeholder="全部环境" /><datalist id="service-environments">{environments.map((item) => <option value={item} key={item} />)}</datalist></label>
          <div className={styles.filterActions}><button type="submit">应用筛选</button><Link href="/services">重置</Link></div>
        </form>
      </Panel>
      <div className={styles.resultSummary}><span>共 <strong>{inventory.total}</strong> 项，当前显示 {inventory.items.length} 项</span><span>能力标签只表示 Agent 声明与控制台映射，不构成执行授权</span></div>
      {inventory.items.length === 0 ? (
        <StateView state="empty" title="没有匹配的服务" description={inventory.total ? "调整筛选条件后重试。" : "尚未发现服务，或当前筛选范围为空。"} />
      ) : (
        <Panel as="div" className={styles.tableWrap}>
          <table className={styles.table}>
            <thead><tr><th>服务</th><th>机器</th><th>类型 / 环境</th><th>状态</th><th>映射</th><th>能力摘要</th></tr></thead>
            <tbody>{inventory.items.map((item) => (
              <tr key={item.inventory_id}>
                <td><div className={styles.identity}>{item.instance_id ? <Link className={styles.rowLink} href={`/servers/${item.agent_id}/services/${item.instance_id}`}>{item.service_name}</Link> : <strong>{item.service_name}</strong>}<span>观测于 {new Date(item.observed_at).toISOString().replace("T", " ").slice(0, 16)} UTC</span></div></td>
                <td><div className={styles.identity}><Link className={styles.rowLink} href={`/servers/${item.agent_id}`}>{item.agent_name}</Link><span>{item.agent_online ? "机器在线" : "机器离线"}</span></div></td>
                <td>{item.service_kind}<br /><span className={styles.meta}>{item.environment ?? "未映射环境"}</span></td>
                <td><StatusBadge tone={item.agent_online ? healthTone(item.healthy) : "warning"}>{item.agent_online ? item.healthy === true ? "健康" : item.healthy === false ? "异常" : "未知" : "机器离线 · 最后记录"} · {item.state}</StatusBadge></td>
                <td><StatusBadge tone={item.mapped ? "success" : item.evidence_capable ? "warning" : "neutral"}>{item.mapped ? "已映射" : item.evidence_capable ? "待复核" : "映射不可用"}</StatusBadge></td>
                <td><div className={styles.capabilities}><span className={`${styles.capability} ${item.evidence_capable ? "" : styles.capabilityOff}`}>证据 {item.evidence_capable ? "可用" : "不可用"}</span><span className={`${styles.capability} ${item.operation_capable ? "" : styles.capabilityOff}`}>操作 {item.operation_capable ? "声明" : "未声明"}</span></div></td>
              </tr>
            ))}</tbody>
          </table>
        </Panel>
      )}
      {inventory.next_cursor && <nav className={styles.pagination} aria-label="服务清单分页"><Link href={`/services?${nextParams.toString()}`}>下一页</Link></nav>}
    </main>
  );
}
