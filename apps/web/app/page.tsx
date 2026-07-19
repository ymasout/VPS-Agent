import Link from "next/link";
import { Agent, AlertEvent, GitHubRepository, GitHubStatus, formatBytes, getAgents, getEvents, getGitHubRepositories, getGitHubStatus } from "@/lib/api";
import { summarizeFleet } from "@/lib/fleet";
import { RegistrationPanel } from "./registration-panel";
import { GitHubPanel } from "./github-panel";

export const dynamic = "force-dynamic";
const consoleVersion = "0.3.4-dev";

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong></div>;
}

function AgentCard({ agent }: { agent: Agent }) {
  const metrics = agent.latest_metrics;
  const problems = agent.service_problem_count;
  const docker = agent.service_kind_counts.docker ?? 0;
  return (
    <Link className="agent-card" href={`/servers/${agent.id}`}>
      <div className={`status ${agent.online ? "online" : "offline"}`}><span /> {agent.online ? "online" : "offline"}</div>
      <h2>{agent.name}</h2>
      <p className="hostname">{agent.hostname} · {agent.os} · {agent.arch}</p>
      <div className="metrics">
        <Metric label="CPU" value={metrics ? `${metrics.cpu_percent.toFixed(1)}%` : "—"} />
        <Metric label="MEM" value={metrics ? `${metrics.memory_percent.toFixed(1)}%` : "—"} />
        <Metric label="RAM" value={metrics ? formatBytes(metrics.memory_used_bytes) : "—"} />
      </div>
      <div className="card-foot"><span>Agent {agent.version}</span><span className={problems ? "bad" : ""}>{problems ? `${problems} 需关注` : `${docker} containers · 正常`}</span></div>
    </Link>
  );
}

export default async function Home() {
  let agents: Agent[] = [];
  let events: AlertEvent[] = [];
  let githubStatus: GitHubStatus | null = null;
  let repositories: GitHubRepository[] = [];
  let error = "";
  try {
    [agents, events, githubStatus] = await Promise.all([getAgents(), getEvents(), getGitHubStatus()]);
    if (githubStatus.configured) repositories = await getGitHubRepositories();
  } catch { error = "控制平面暂时不可用，请检查 API 服务。"; }
  const fleet = summarizeFleet(agents);
  return (
    <main>
      <section className="hero compact">
        <div className="eyebrow"><span /> M1 · FLEET</div>
        <h1>机器<span>可见</span></h1>
        <p>{fleet.total} 台 VPS · {fleet.online} 台在线 · organization: local</p>
      </section>
      <RegistrationPanel />
      {githubStatus?.configured && <GitHubPanel status={githubStatus} repositories={repositories} />}
      {error && <div className="empty error">{error}</div>}
      {!error && agents.length === 0 && <div className="empty"><strong>还没有已注册的 VPS</strong><span>启动带注册令牌的 Agent 后，机器会自动出现在这里。</span></div>}
      <section className="fleet">{agents.map((agent) => <AgentCard key={agent.id} agent={agent} />)}</section>
      {!error && events.length > 0 && <section className="section">
        <div className="section-title"><h2>最近事件</h2><span>{events.length} events</span></div>
        <div className="event-list">{events.slice(0, 8).map((event) =>
          <Link className="event-card" href={`/events/${event.id}`} key={event.id}>
            <div><span>{event.status}</span><strong>{event.title}</strong></div>
            <p>{event.service_kind ?? event.source} · {event.service_key ?? event.agent_id}</p>
            <time>{new Date(event.last_observed_at).toLocaleString("zh-CN")}</time>
          </Link>)}</div>
      </section>}
      <footer><span>control plane</span> trusted <i /> <span>mode</span> self-hosted <i /> <span>console</span> {consoleVersion}</footer>
    </main>
  );
}
