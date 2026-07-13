import Link from "next/link";
import { Agent, formatBytes, getAgents } from "@/lib/api";
import { RegistrationPanel } from "./registration-panel";

export const dynamic = "force-dynamic";
const consoleVersion = "0.2.4";

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
  let error = "";
  try { agents = await getAgents(); } catch { error = "控制平面暂时不可用，请检查 API 服务。"; }
  const online = agents.filter((agent) => agent.online).length;
  return (
    <main>
      <section className="hero compact">
        <div className="eyebrow"><span /> M1 · FLEET</div>
        <h1>机器<span>可见</span></h1>
        <p>{agents.length} 台 VPS · {online} 台在线 · organization: local</p>
      </section>
      <RegistrationPanel />
      {error && <div className="empty error">{error}</div>}
      {!error && agents.length === 0 && <div className="empty"><strong>还没有已注册的 VPS</strong><span>启动带注册令牌的 Agent 后，机器会自动出现在这里。</span></div>}
      <section className="fleet">{agents.map((agent) => <AgentCard key={agent.id} agent={agent} />)}</section>
      <footer><span>control plane</span> trusted <i /> <span>mode</span> self-hosted <i /> <span>console</span> {consoleVersion}</footer>
    </main>
  );
}
