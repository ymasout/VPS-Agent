import Link from "next/link";
import { Service, formatBytes, getAgent } from "@/lib/api";
import { notFound } from "next/navigation";

export const dynamic = "force-dynamic";

const goodStates = new Set(["active", "running", "healthy"]);
const warningStates = new Set(["activating", "deactivating", "reloading"]);
const badStates = new Set(["failed", "unhealthy", "exited"]);

function isProblem(service: Service) {
  return service.healthy === false || badStates.has(service.state);
}

function statusTone(service: Service) {
  if (isProblem(service)) return "bad";
  if (service.healthy === true || goodStates.has(service.state)) return "good";
  if (warningStates.has(service.state)) return "warn";
  return "neutral";
}

function ServiceRows({ services, empty }: { services: Service[]; empty?: string }) {
  return (
    <div className="rows">
      {services.length === 0 && <div className="row muted service-empty">{empty ?? "暂无服务"}</div>}
      {services.map((service) => (
        <div className="row" key={`${service.kind}-${service.key}`}>
          <em>{service.kind}</em>
          <strong title={service.name}>{service.name}</strong>
          <span title={service.detail ?? undefined}>{service.detail ?? "—"}</span>
          <b className={statusTone(service)}>{service.state}</b>
        </div>
      ))}
    </div>
  );
}

function ServiceSection({ title, services, defaultOpen = true }: { title: string; services: Service[]; defaultOpen?: boolean }) {
  if (services.length === 0) return null;
  return (
    <details className="service-group" open={defaultOpen}>
      <summary><strong>{title}</strong><span>{services.length}</span></summary>
      <ServiceRows services={services} />
    </details>
  );
}

export default async function ServerPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let agent;
  try { agent = await getAgent(id); } catch { notFound(); }

  const metric = agent.latest_metrics;
  const problems = agent.services.filter(isProblem);
  const normal = agent.services.filter((service) => !isProblem(service));
  const docker = normal.filter((service) => service.kind === "docker");
  const http = normal.filter((service) => service.kind === "http");
  const systemdActive = normal.filter((service) => service.kind === "systemd" && goodStates.has(service.state));
  const systemdInactive = normal.filter((service) => service.kind === "systemd" && !goodStates.has(service.state));

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

      <section className="section">
        <div className="section-title"><h2>磁盘</h2><span>{metric?.disks.length ?? 0} mounts</span></div>
        <div className="rows">
          {metric?.disks.map((disk) => <div className="row disk-row" key={disk.path}><strong>{disk.path}</strong><span>{formatBytes(disk.used_bytes)} / {formatBytes(disk.total_bytes)}</span><b>{disk.used_percent.toFixed(1)}%</b></div>)}
        </div>
      </section>

      <section className="section">
        <div className="section-title"><h2>服务状态</h2><span>{agent.services.length} services</span></div>
        <div className="service-overview">
          <div><span>需关注</span><strong className={problems.length ? "bad" : "good"}>{problems.length}</strong></div>
          <div><span>Docker</span><strong>{agent.service_kind_counts.docker ?? 0}</strong></div>
          <div><span>HTTP 检查</span><strong>{agent.service_kind_counts.http ?? 0}</strong></div>
          <div><span>systemd</span><strong>{agent.service_kind_counts.systemd ?? 0}</strong></div>
        </div>

        {agent.services.length === 0 && <ServiceRows services={[]} empty="当前环境未发现 Docker、systemd 或 HTTP 检查" />}
        <ServiceSection title="需关注" services={problems} />
        <ServiceSection title="Docker 容器" services={docker} />
        <ServiceSection title="HTTP 健康检查" services={http} />
        <ServiceSection title="运行中的 systemd 服务" services={systemdActive} />
        <ServiceSection title="未运行的 systemd 服务（正常待命或已停止）" services={systemdInactive} defaultOpen={false} />
      </section>
    </main>
  );
}
