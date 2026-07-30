import { type Agent, type AlertEvent, type Principal, getAgents, getEvents, getPrincipal } from "@/lib/api";
import { summarizeFleet } from "@/lib/fleet";
import { getPrincipalForwardHeaders } from "@/lib/principal";

export const dynamic = "force-dynamic";

export default async function MobileStatusPage() {
  let agents: Agent[] = [];
  let events: AlertEvent[] = [];
  let principal: Principal | null = null;
  let error = "";
  try {
    const principalHeaders = await getPrincipalForwardHeaders();
    [agents, events] = await Promise.all([getAgents(principalHeaders ?? undefined), getEvents(principalHeaders ?? undefined)]);
    if (principalHeaders) principal = await getPrincipal(principalHeaders);
  } catch {
    error = "控制平面暂时不可用，请联网后重新加载。";
  }
  const fleet = summarizeFleet(agents);
  return (
    <main className="mobile-overview">
      <section className="hero compact">
        <div className="eyebrow"><span /> MOBILE · READ ONLY</div>
        <h1>运行<span>状态</span></h1>
        <p>当前在线数据 · 不提供离线快照 · 写操作仅在独立 Operation 审批页出现</p>
        {principal && <p>Principal: {principal.display_name} · viewer · {principal.authorization_mode === "shadow" ? "shadow，当前权限未改变" : "有限只读授权已生效"}</p>}
      </section>
      {error && <div className="empty error" role="alert">{error}</div>}
      <section className="mobile-summary" aria-label="Fleet 摘要">
        <div><span>机器</span><strong>{fleet.total}</strong></div>
        <div><span>在线</span><strong>{fleet.online}</strong></div>
        <div><span>异常服务</span><strong>{fleet.problems}</strong></div>
      </section>
      <section id="machines" className="section mobile-section">
        <div className="section-title"><h2>机器</h2><span>{agents.length} agents</span></div>
        <div className="mobile-list">
          {agents.map((agent) => (
            <article className="mobile-status-card" key={agent.id}>
              <div><span className={`status ${agent.online ? "" : "offline"}`}><i /> {agent.online ? "online" : "offline"}</span><strong>{agent.name}</strong></div>
              <p>{agent.hostname} · CPU {agent.latest_metrics ? `${agent.latest_metrics.cpu_percent.toFixed(1)}%` : "—"} · MEM {agent.latest_metrics ? `${agent.latest_metrics.memory_percent.toFixed(1)}%` : "—"} · {agent.service_problem_count ? `${agent.service_problem_count} 项需关注` : "服务正常"}</p>
            </article>
          ))}
          {!error && agents.length === 0 && <div className="empty">还没有已注册的 VPS。</div>}
        </div>
      </section>
      <section id="events" className="section mobile-section">
        <div className="section-title"><h2>最近事件</h2><span>{events.length} events</span></div>
        <div className="mobile-list">
          {events.slice(0, 20).map((event) => (
            <article className="mobile-status-card" key={event.id}>
              <div><span className="mobile-severity">{event.severity}</span><strong>{event.title}</strong></div>
              <p>{event.status} · {event.service_key ?? event.agent_id} · {new Date(event.last_observed_at).toLocaleString("zh-CN")}</p>
              {event.detail && <p>{event.detail}</p>}
            </article>
          ))}
          {!error && events.length === 0 && <div className="empty">当前没有事件。</div>}
        </div>
      </section>
    </main>
  );
}
