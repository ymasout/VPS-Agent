import { ContextConversationPanel } from "@/app/context-conversation";
import { EventConversationPanel } from "@/app/events/[id]/event-conversation";
import { RepositoryConversationPanel } from "@/app/repositories/[id]/repository-conversation";
import { PageHeader, Panel, StateView, StatusBadge } from "@/app/ui/primitives";
import {
  getAgentConversation,
  getAgents,
  getEventConversation,
  getEvents,
  getFleetConversation,
  getGitHubRepositories,
  getRepositoryConversation,
  getServiceConversation,
  getServiceInstances,
  type ContextConversation,
  type FleetConversation,
} from "@/lib/api";
import { getPrincipalForwardHeaders } from "@/lib/principal";
import styles from "./assistant.module.css";

export const dynamic = "force-dynamic";

type Scope = "fleet" | "agent" | "service" | "event" | "repository";

function parseContext(value: string | string[] | undefined): { scope: Scope; id: string | null } {
  if (typeof value !== "string" || value === "fleet") return { scope: "fleet", id: null };
  const separator = value.indexOf(":");
  if (separator < 1) return { scope: "fleet", id: null };
  const scope = value.slice(0, separator);
  const id = value.slice(separator + 1);
  if (!["agent", "service", "event", "repository"].includes(scope) || !id || id.length > 64) {
    return { scope: "fleet", id: null };
  }
  return { scope: scope as Scope, id };
}

export default async function AssistantPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = await searchParams;
  const selected = parseContext(query.context);
  const principalHeaders = await getPrincipalForwardHeaders();
  const headers = principalHeaders ?? undefined;
  const [agentsResult, servicesResult, eventsResult, repositoriesResult] = await Promise.allSettled([
    getAgents(headers),
    getServiceInstances(new URLSearchParams({ mapping: "mapped", limit: "100" }), headers),
    getEvents(new URLSearchParams({ limit: "100" }), headers),
    getGitHubRepositories(headers),
  ]);
  const agents = agentsResult.status === "fulfilled" ? agentsResult.value : [];
  const services = servicesResult.status === "fulfilled" ? servicesResult.value.items.filter((item) => item.instance_id) : [];
  const events = eventsResult.status === "fulfilled" ? eventsResult.value.items : [];
  const repositories = repositoriesResult.status === "fulfilled" ? repositoriesResult.value : [];

  let context: Awaited<ReturnType<typeof getFleetConversation>> | Awaited<ReturnType<typeof getEventConversation>> | Awaited<ReturnType<typeof getRepositoryConversation>> | ContextConversation | null = null;
  let unavailable = false;
  try {
    if (selected.scope === "agent" && selected.id) context = await getAgentConversation(selected.id, headers);
    else if (selected.scope === "service" && selected.id) context = await getServiceConversation(selected.id, headers);
    else if (selected.scope === "event" && selected.id) context = await getEventConversation(selected.id, headers);
    else if (selected.scope === "repository" && selected.id) context = await getRepositoryConversation(selected.id, headers);
    else context = await getFleetConversation(headers);
  } catch {
    unavailable = true;
  }

  const selectedAgent = selected.scope === "agent" ? agents.find((agent) => agent.id === selected.id) : null;
  const selectedService = selected.scope === "service" ? services.find((service) => service.instance_id === selected.id) : null;
  const selectedEvent = selected.scope === "event" ? events.find((event) => event.id === selected.id) : null;
  const selectedRepository = selected.scope === "repository" ? repositories.find((repository) => repository.id === selected.id) : null;
  const eventAgent = selectedEvent ? agents.find((agent) => agent.id === selectedEvent.agent_id) : null;
  const lastSnapshot = Boolean(
    (selectedAgent && !selectedAgent.online)
    || (selectedService && !selectedService.agent_online)
    || (eventAgent && !eventAgent.online),
  );
  let standardContext: ContextConversation | null = null;
  if (context && (selected.scope === "agent" || selected.scope === "service")) {
    standardContext = context as ContextConversation;
  } else if (context && selected.scope === "fleet") {
    const fleet = context as FleetConversation;
    standardContext = {
      scope_type: "fleet",
      target_id: "local",
      parent_agent_id: "local",
      title: "当前组织 Fleet",
      ...fleet,
    };
  }
  const fallbackScopeTitles: Record<Scope, string> = {
    fleet: "当前组织 Fleet",
    agent: "机器上下文",
    service: "服务上下文",
    event: "事件上下文",
    repository: "仓库上下文",
  };
  const scopeTitle = standardContext?.title ?? selectedEvent?.title ?? selectedRepository?.full_name ?? fallbackScopeTitles[selected.scope];

  return (
    <main className={styles.workspace}>
      <PageHeader eyebrow="知识 · 只读助手" title="Agent 对话" description="选择一个服务端固定的可信上下文，阅读结构化回答与真实引用；这不是 Web SSH，也不会直接操作 VPS。" />
      <Panel as="div">
        <form className={styles.selector} action="/assistant" method="get" aria-label="选择对话上下文">
          <label>当前上下文<select name="context" defaultValue={selected.id ? `${selected.scope}:${selected.id}` : "fleet"}>
            <option value="fleet">Fleet · 当前组织有界快照</option>
            {agents.length > 0 && <optgroup label="机器">{agents.map((agent) => <option key={agent.id} value={`agent:${agent.id}`}>{agent.name}{agent.online ? "" : " · 离线最后快照"}</option>)}</optgroup>}
            {services.length > 0 && <optgroup label="服务">{services.map((service) => <option key={service.inventory_id} value={`service:${service.instance_id}`}>{service.service_name} · {service.agent_name}</option>)}</optgroup>}
            {events.length > 0 && <optgroup label="事件">{events.map((event) => <option key={event.id} value={`event:${event.id}`}>{event.status} · {event.title}</option>)}</optgroup>}
            {repositories.length > 0 && <optgroup label="仓库">{repositories.map((repository) => <option key={repository.id} value={`repository:${repository.id}`}>{repository.full_name}</option>)}</optgroup>}
          </select></label>
          <button type="submit">切换上下文</button>
        </form>
      </Panel>
      <Panel className={styles.scopeSummary} as="div">
        <div><strong>{scopeTitle}</strong><span>{selected.scope === "fleet" ? "Fleet 聚合快照" : `${selected.scope} 固定作用域`}</span></div>
        <StatusBadge tone={lastSnapshot ? "warning" : "info"}>{lastSnapshot ? "离线 · 最后快照" : "只读上下文"}</StatusBadge>
        <p className={styles.safety}>浏览器选择只决定调用哪个固定资源路由；实际 scope、引用范围和可用候选继续由服务端外键、组织边界和功能开关决定。</p>
      </Panel>
      {unavailable || context === null ? (
        <StateView state="error" title="当前上下文暂时不可用" description="控制平面没有返回该上下文。本状态不会伪造空会话，也不会改用其他 scope。" />
      ) : selected.scope === "event" && "event_id" in context ? (
        <EventConversationPanel initial={context} showOperations={false} lastSnapshot={lastSnapshot} />
      ) : selected.scope === "repository" && "repository_id" in context ? (
        <RepositoryConversationPanel initial={context} />
      ) : standardContext ? (
        <ContextConversationPanel
          endpoint={selected.scope === "agent" && selected.id ? `/console/agents/${selected.id}/conversation/turns` : selected.scope === "service" && selected.id ? `/console/service-instances/${selected.id}/conversation/turns` : "/console/fleet/conversation/turns"}
          initial={standardContext}
          lastSnapshot={lastSnapshot}
        />
      ) : (
        <StateView state="error" title="上下文响应无法识别" description="控制平面响应与所选 scope 不一致，已停止显示且没有降级到其他上下文。" />
      )}
    </main>
  );
}
