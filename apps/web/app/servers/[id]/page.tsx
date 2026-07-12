import Link from "next/link";
import { formatBytes, getAgent } from "@/lib/api";
import { notFound } from "next/navigation";

export const dynamic = "force-dynamic";

export default async function ServerPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let agent; try { agent = await getAgent(id); } catch { notFound(); }
  const metric = agent.latest_metrics;
  return (
    <main>
      <Link className="back" href="/">← Fleet</Link>
      <section className="hero compact detail-head">
        <div className={`status ${agent.online ? "online" : "offline"}`}><span /> {agent.online ? "online" : "offline"}</div>
        <h1>{agent.name}</h1>
        <p>{agent.hostname} · {agent.os} · {agent.arch} · Agent {agent.version}</p>
      </section>
      <section className="summary-grid">
        <div><span>CPU</span><strong>{metric ? `${metric.cpu_percent.toFixed(1)}%` : "—"}</strong></div>
        <div><span>内存</span><strong>{metric ? `${metric.memory_percent.toFixed(1)}%` : "—"}</strong><small>{metric ? `${formatBytes(metric.memory_used_bytes)} / ${formatBytes(metric.memory_total_bytes)}` : "暂无数据"}</small></div>
        <div><span>最后心跳</span><strong className="date">{agent.last_seen_at ? new Date(agent.last_seen_at).toLocaleString("zh-CN") : "—"}</strong></div>
      </section>
      <section className="section"><div className="section-title"><h2>磁盘</h2><span>{metric?.disks.length ?? 0} mounts</span></div><div className="rows">{metric?.disks.map((disk) => <div className="row" key={disk.path}><strong>{disk.path}</strong><span>{formatBytes(disk.used_bytes)} / {formatBytes(disk.total_bytes)}</span><b>{disk.used_percent.toFixed(1)}%</b></div>)}</div></section>
      <section className="section"><div className="section-title"><h2>服务状态</h2><span>{agent.services.length} services</span></div><div className="rows">{agent.services.length === 0 && <div className="row muted">当前环境未发现 Docker 或 systemd 服务</div>}{agent.services.map((service) => <div className="row" key={`${service.kind}-${service.key}`}><em>{service.kind}</em><strong>{service.name}</strong><span>{service.detail}</span><b className={service.state === "running" || service.state === "active" ? "good" : "warn"}>{service.state}</b></div>)}</div></section>
    </main>
  );
}

