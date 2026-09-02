import Link from "next/link";
import { notFound } from "next/navigation";

import { ContextConversationPanel } from "@/app/context-conversation";
import { DeploymentPlanPanel } from "@/app/deployment-plan-panel";
import styles from "@/app/infrastructure.module.css";
import { ServiceMappingPanel } from "@/app/service-mapping-panel";
import { PageHeader, StateView, StatusBadge } from "@/app/ui/primitives";
import {
  AlertEvent,
  ContextConversation,
  Service,
  formatBytes,
  getAgent,
  getAgentConversation,
  getDeploymentCandidates,
  getEvents,
  getGitHubRepositories,
  getServiceMappingCandidates,
} from "@/lib/api";
import { getCurrentPrincipal, getPrincipalForwardHeaders } from "@/lib/principal";
import { isGoodState, isServiceProblem, serviceStatusTone } from "@/lib/service-status";

export const dynamic = "force-dynamic";

function ServiceRows({ services, empty }: { services: Service[]; empty?: string }) {
  return (
    <div className="rows">
      {services.length === 0 && <div className="row muted service-empty">{empty ?? "暂无服务"}</div>}
      {services.map((service) => (
        <div className="row" key={`${service.kind}-${service.key}`}>
          <em>{service.kind}</em><strong title={service.name}>{service.name}</strong>
          <span title={service.detail ?? undefined}>{service.detail ?? "—"}</span>
          <b className={serviceStatusTone(service)}>{service.state}</b>
        </div>
      ))}
    </div>
  );
}

function ServiceSection({ title, services, defaultOpen = true }: { title: string; services: Service[]; defaultOpen?: boolean }) {
  if (services.length === 0) return null;
  return <details className="service-group" open={defaultOpen}><summary><strong>{title}</strong><span>{services.length}</span></summary><ServiceRows services={services} /></details>;
}

function eventTone(event: AlertEvent) {
  if (event.status === "resolved") return "success" as const;
  return event.severity === "critical" ? "danger" as const : "warning" as const;
}

export default async function ServerPage({ params, searchParams }: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ service?: string | string[] }>;
}) {
  const { id } = await params;
  const query = await searchParams;
  const requestedService = typeof query.service === "string" ? query.service : "";
  const focusServiceKey = requestedService.length <= 255 ? requestedService : "";
  const principalHeaders = await getPrincipalForwardHeaders();
  const namedAuthorization = process.env.PRINCIPAL_WRITE_AUTHORIZATION_ENABLED === "true";
  const principal = namedAuthorization ? await getCurrentPrincipal().catch(() => null) : null;
  const canManageMappings = !namedAuthorization || principal?.capabilities.includes("operation:plan") === true;
  let agent;
  try { agent = await getAgent(id, principalHeaders ?? undefined); } catch { notFound(); }
  const [candidatesResult, repositoriesResult, deploymentsResult, conversationResult, eventsResult] = await Promise.allSettled([
    getServiceMappingCandidates(id, principalHeaders ?? undefined), getGitHubRepositories(), getDeploymentCandidates(id),
    getAgentConversation(id, principalHeaders ?? undefined), getEvents(new URLSearchParams({ agent_id: id, limit: "50" }), principalHeaders ?? undefined),
  ]);
  const candidates = candidatesResult.status === "fulfilled" ? candidatesResult.value : [];
  const repositories = repositoriesResult.status === "fulfilled" ? repositoriesResult.value : [];
  const deploymentCandidates = deploymentsResult.status === "fulfilled" ? deploymentsResult.value : [];
  const conversation: ContextConversation = conversationResult.status === "fulfilled" ? conversationResult.value : {
    scope_type: "agent", target_id: id, parent_agent_id: id, title: agent.name,
    session_id: null, available: false, unavailable_reason: "control_plane_unavailable", turns: [],
  };
  const machineEvents = eventsResult.status === "fulfilled" ? eventsResult.value.items : null;
  const metric = agent.latest_metrics;
  const problems = agent.services.filter(isServiceProblem);
  const normal = agent.services.filter((service) => !isServiceProblem(service));
  const docker = normal.filter((service) => service.kind === "docker");
  const http = normal.filter((service) => service.kind === "http");
  const systemdActive = normal.filter((service) => service.kind === "systemd" && isGoodState(service.state));
  const systemdInactive = normal.filter((service) => service.kind === "systemd" && !isGoodState(service.state));

  return (
    <main className={styles.workspace}>
      <Link className="back" href="/fleet">← 返回 Fleet</Link>
      <PageHeader eyebrow="机器详情" title={agent.name} description={`${agent.hostname} · ${agent.os} · ${agent.arch} · Agent ${agent.version}`} actions={<StatusBadge tone={agent.online ? "success" : "danger"}>{agent.online ? "在线" : "离线"}</StatusBadge>} />
      <nav className={styles.sectionNav} aria-label="机器详情分区">
        <a href="#overview">概览</a><a href="#services">服务</a><a href="#events">事件</a><a href="#assistant">助手</a><a href="#deployment-policy">部署与策略</a>
      </nav>

      <section className={styles.detailSection} id="overview" aria-labelledby="overview-title">
        <div className="section-title"><h2 id="overview-title">概览</h2><span>最新控制平面快照</span></div>
        <div className="summary-grid">
          <div><span>CPU</span><strong>{metric ? `${metric.cpu_percent.toFixed(1)}%` : "—"}</strong></div>
          <div><span>内存</span><strong>{metric ? `${metric.memory_percent.toFixed(1)}%` : "—"}</strong><small>{metric ? `${formatBytes(metric.memory_used_bytes)} / ${formatBytes(metric.memory_total_bytes)}` : "暂无数据"}</small></div>
          <div><span>最后心跳</span><strong className="date">{agent.last_seen_at ? `${new Date(agent.last_seen_at).toISOString().replace("T", " ").slice(0, 19)} UTC` : "—"}</strong></div>
        </div>
        <section className="section">
          <div className="section-title"><h3>磁盘</h3><span>{metric?.disks.length ?? 0} mounts</span></div>
          <div className="rows">{metric?.disks.map((disk) => <div className="row disk-row" key={disk.path}><strong>{disk.path}</strong><span>{formatBytes(disk.used_bytes)} / {formatBytes(disk.total_bytes)}</span><b>{disk.used_percent.toFixed(1)}%</b></div>)}{!metric?.disks.length && <div className="row muted">暂无磁盘指标</div>}</div>
        </section>
      </section>

      <section className={`${styles.detailSection} section`} id="services" aria-labelledby="services-title">
        <div className="section-title"><h2 id="services-title">服务</h2><span>{agent.services.length} services</span></div>
        <div className="service-overview"><div><span>需关注</span><strong className={problems.length ? "bad" : "good"}>{problems.length}</strong></div><div><span>Docker</span><strong>{agent.service_kind_counts.docker ?? 0}</strong></div><div><span>HTTP 检查</span><strong>{agent.service_kind_counts.http ?? 0}</strong></div><div><span>systemd</span><strong>{agent.service_kind_counts.systemd ?? 0}</strong></div></div>
        {agent.services.length === 0 && <ServiceRows services={[]} empty="当前环境未发现 Docker、systemd 或 HTTP 检查" />}
        <ServiceSection title="需关注" services={problems} /><ServiceSection title="Docker 容器" services={docker} /><ServiceSection title="HTTP 健康检查" services={http} /><ServiceSection title="运行中的 systemd 服务" services={systemdActive} /><ServiceSection title="未运行的 systemd 服务（正常待命或已停止）" services={systemdInactive} defaultOpen={false} />
        <ServiceMappingPanel candidates={candidates} repositories={repositories} canManage={canManageMappings} namedAuthorization={namedAuthorization} />
      </section>

      <section className={`${styles.detailSection} section`} id="events" aria-labelledby="events-title">
        <div className="section-title"><h2 id="events-title">事件</h2><span>{machineEvents?.length ?? "—"}</span></div>
        {machineEvents === null ? <StateView state="unavailable" title="事件分区不可用" description="机器数据仍可读取，但事件读取失败或当前 Principal 无 event:read。" /> : machineEvents.length === 0 ? <StateView state="empty" title="没有关联事件" description="控制平面当前没有这台机器的事件记录。" /> : <div className={styles.eventList}>{machineEvents.slice(0, 10).map((event) => <Link className={styles.eventItem} href={`/events/${event.id}`} key={event.id}><StatusBadge tone={eventTone(event)}>{event.status}</StatusBadge><strong>{event.title}</strong><time dateTime={event.last_observed_at}>{new Date(event.last_observed_at).toISOString().slice(0, 16).replace("T", " ")} UTC</time></Link>)}</div>}
      </section>

      <section className={styles.detailSection} id="assistant" aria-labelledby="assistant-title">
        <div className="section-title"><h2 id="assistant-title">助手</h2><span>现有机器上下文会话</span></div>
        <ContextConversationPanel endpoint={`/console/agents/${id}/conversation/turns`} initial={conversation} unavailable={conversationResult.status === "rejected"} lastSnapshot={!agent.online} />
      </section>
      <section className={styles.detailSection} id="deployment-policy" aria-labelledby="deployment-title">
        <div className="section-title"><h2 id="deployment-title">部署与策略</h2><span>沿用既有安全边界</span></div>
        <DeploymentPlanPanel candidates={deploymentCandidates} focusServiceKey={focusServiceKey || undefined} namedAuthorization={namedAuthorization} />
      </section>
    </main>
  );
}
