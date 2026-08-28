import Link from "next/link";

import type { ConsoleOverview, OverviewResourceMetric, OverviewTrendStatus } from "@/lib/api";
import { OverviewSparkline } from "./overview-sparkline";
import styles from "./overview.module.css";
import { Panel, StateView, StatusBadge } from "./ui/primitives";

const trendLabels: Record<OverviewTrendStatus, string> = {
  available: "24h 完整",
  gapped: "趋势有缺口",
  insufficient: "不足 24h",
  stale: "数据已过期",
  unavailable: "趋势不可用",
};

const statusTone = (value: string): "neutral" | "info" | "success" | "warning" | "danger" => {
  if (value === "resolved" || value === "succeeded") return "success";
  if (["critical", "failed", "expired", "offline"].includes(value)) return "danger";
  if (["warning", "awaiting_confirmation"].includes(value)) return "warning";
  if (["firing", "queued", "claimed", "running", "verifying"].includes(value)) return "info";
  return "neutral";
};

export function relativeTime(value: string, generatedAt: string): string {
  const seconds = Math.max(0, Math.round((Date.parse(generatedAt) - Date.parse(value)) / 1000));
  if (seconds < 60) return `${seconds} 秒前`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} 小时前`;
  return `${Math.floor(seconds / 86400)} 天前`;
}

function ResourceCell({ metric, label }: { metric: OverviewResourceMetric; label: string }) {
  const displayLabel = label.split(" ").at(-1);
  return (
    <div className={`${styles.resource} ${styles[`tone_${metric.tone}`]}`}>
      <span className={styles.resourceLabel}>{displayLabel}</span>
      <span className={styles.resourceValue}>{metric.current_percent === null ? "—" : `${metric.current_percent.toFixed(0)}%`}</span>
      <OverviewSparkline label={label} metric={metric} />
      <span className={styles.trendState}>{trendLabels[metric.trend.status]}</span>
    </div>
  );
}

function SectionHeading({ icon, title, meta }: { icon: string; title: string; meta?: string }) {
  return (
    <header className={styles.sectionHeading}>
      <div><span aria-hidden="true">{icon}</span><h2>{title}</h2></div>
      {meta && <span>{meta}</span>}
    </header>
  );
}

function KpiCard({ icon, label, value, detail, tone }: { icon: string; label: string; value: string | number; detail: string; tone: "success" | "info" | "warning" | "danger" }) {
  return (
    <Panel className={`${styles.kpi} ${styles[`tone_${tone}`]}`}>
      <span aria-hidden="true" className={styles.kpiIcon}>{icon}</span>
      <div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>
    </Panel>
  );
}

function OperationProgress({ item }: { item: ConsoleOverview["operations"]["items"][number] }) {
  const stages = ["计划创建", "独立审批", "Agent 执行", "健康验证"];
  const statusOrder: Record<string, number> = { planned: 0, prechecking: 0, awaiting_confirmation: 1, queued: 2, claimed: 2, running: 2, verifying: 3, succeeded: 4 };
  const current = statusOrder[item.status] ?? -1;
  return (
    <Link className={styles.operationCard} href={`/operations/${item.id}`}>
      <div className={styles.operationSummary}>
        <strong>{item.target}</strong><span>{item.impact_summary}</span>
        <StatusBadge tone={statusTone(item.status)}>{item.status}</StatusBadge>
      </div>
      <ol className={styles.operationStages} aria-label={`${item.target} Operation 进度`}>
        {stages.map((stage, index) => (
          <li className={index < current ? styles.stageDone : index === current ? styles.stageCurrent : ""} key={stage}>
            <span aria-hidden="true">{index < current ? "✓" : index + 1}</span>
            <div><strong>{stage}</strong><small>{index < current ? "已完成" : index === current ? "当前阶段" : "尚未开始"}</small></div>
          </li>
        ))}
      </ol>
    </Link>
  );
}

export function OverviewDashboard({ overview }: { overview: ConsoleOverview }) {
  const trustCommit = overview.trust.commit_sha === "unknown-build" ? overview.trust.commit_sha : overview.trust.commit_sha.slice(0, 12);
  return (
    <main className={styles.overview}>
      <header className={styles.pageIntro}>
        <div><p>CONTROL PLANE · READ ONLY</p><h1>运维总览</h1></div>
        <div className={styles.freshness}>
          <StatusBadge tone={overview.trust.schema_current ? "success" : "warning"}>Schema {overview.trust.schema_current ? "正常" : "需检查"}</StatusBadge>
          <span>刚刚刷新 · {new Date(overview.generated_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</span>
        </div>
      </header>

      <section aria-label="关键指标" className={styles.kpiGrid}>
        <KpiCard icon="▦" label="在线机器" value={`${overview.fleet.online} / ${overview.fleet.total}`} detail={overview.fleet.total === overview.fleet.online ? "全部在线" : `${overview.fleet.total - overview.fleet.online} 台离线`} tone={overview.fleet.total === overview.fleet.online ? "success" : "danger"} />
        <KpiCard icon="△" label="异常服务" value={overview.fleet.unhealthy_services} detail={overview.fleet.unhealthy_services ? "需要关注" : "没有已知异常"} tone={overview.fleet.unhealthy_services ? "warning" : "success"} />
        <KpiCard icon="◉" label="活跃事件" value={overview.events.active} detail={`严重 ${overview.events.critical} · 警告 ${overview.events.warning}`} tone={overview.events.critical ? "danger" : overview.events.active ? "warning" : "success"} />
        <KpiCard icon="▤" label="待审批" value={overview.operations.available ? overview.operations.pending_approval : "—"} detail={overview.operations.available ? (overview.operations.can_approve ? "具备审批入口权限" : "仅只读可见") : "当前角色无权读取"} tone={overview.operations.pending_approval ? "info" : "success"} />
      </section>

      <div className={styles.primaryGrid}>
        <Panel className={styles.panel}>
          <SectionHeading icon="△" title="需要关注" meta={`${overview.attention.length} 项`} />
          {overview.attention.length ? <div className={styles.attentionList}>{overview.attention.map((item) => (
            <Link href={item.href} key={`${item.kind}-${item.href}`}>
              <span className={`${styles.attentionMark} ${styles[`tone_${item.tone}`]}`} aria-hidden="true">!</span>
              <div><strong>{item.title}</strong><span>{item.target}</span></div>
              <StatusBadge tone={item.tone}>{item.kind === "event" ? "事件" : item.kind === "operation" ? "Operation" : "离线"}</StatusBadge>
              <time>{relativeTime(item.occurred_at, overview.generated_at)}</time>
            </Link>
          ))}</div> : <p className={styles.compactEmpty}>当前没有需要关注的项目。</p>}
        </Panel>

        <Panel className={`${styles.panel} ${styles.fleetPanel}`}>
          <SectionHeading icon="⌁" title="Fleet 健康" meta="过去 24 小时" />
          {overview.agents.length ? <div className={styles.tableWrap}>
            <div className={styles.fleetHeader} aria-hidden="true"><span>机器</span><span>状态</span><span>CPU</span><span>内存</span><span>磁盘</span><span>Agent / 新鲜度</span></div>
            <div className={styles.fleetRows}>{overview.agents.map((agent) => (
              <Link className={styles.fleetRow} href={`/servers/${agent.id}`} key={agent.id}>
                <div className={styles.machine}><span className={agent.online ? styles.onlineDot : styles.offlineDot} aria-hidden="true" /><strong>{agent.name}</strong><small>{agent.hostname}</small></div>
                <StatusBadge tone={agent.online ? "success" : "danger"}>{agent.online ? "在线" : "离线"}</StatusBadge>
                <ResourceCell label={`${agent.name} CPU`} metric={agent.cpu} /><ResourceCell label={`${agent.name} 内存`} metric={agent.memory} /><ResourceCell label={`${agent.name} 磁盘`} metric={agent.disk} />
                <div className={styles.agentMeta}><span>{agent.version}</span><small>{agent.last_seen_at ? relativeTime(agent.last_seen_at, overview.generated_at) : "从未上报"}</small></div>
              </Link>
            ))}</div>
          </div> : <p className={styles.compactEmpty}>尚无已注册机器。注册入口已移出总览。</p>}
        </Panel>
      </div>

      <div className={styles.secondaryGrid}>
        <Panel className={styles.panel}>
          <SectionHeading icon="☷" title="事件状态" meta="最近记录" />
          {overview.event_items.length ? <div className={styles.eventRows}>{overview.event_items.map((event) => (
            <Link href={`/events/${event.id}`} key={event.id}>
              <span className={`${styles.eventIcon} ${styles[`tone_${statusTone(event.severity)}`]}`} aria-hidden="true">!</span>
              <div><strong>{event.title}</strong><small>{event.target}</small></div>
              <StatusBadge tone={statusTone(event.severity)}>{event.severity}</StatusBadge><StatusBadge tone={statusTone(event.status)}>{event.status}</StatusBadge>
              <time>{relativeTime(event.occurred_at, overview.generated_at)}</time>
            </Link>
          ))}</div> : <p className={styles.compactEmpty}>没有事件记录。</p>}
        </Panel>

        <Panel className={styles.panel}>
          <SectionHeading icon="♢" title="Operation 进度" meta={overview.operations.available ? `${overview.operations.active} 个进行中` : "受权限保护"} />
          {!overview.operations.available ? <div className={styles.permissionState}><strong>没有 Operation 读取权限</strong><span>此分区按 Principal capability 关闭，未加载任何 Operation 摘要。</span></div> : overview.operations.items.length ? <div className={styles.operationList}>{overview.operations.items.slice(0, 2).map((item) => <OperationProgress item={item} key={item.id} />)}</div> : <p className={styles.compactEmpty}>当前没有进行中的 Operation。</p>}
          <p className={styles.safetyNote}>计划创建不等于确认执行；身份、capability、签名、Agent policy 与健康验证仍由服务端强制执行。</p>
        </Panel>
      </div>

      <div className={styles.bottomGrid}>
        <Panel className={styles.panel}>
          <SectionHeading icon="≡" title="近期活动" />
          {overview.recent_activity.length ? <div className={styles.activityList}>{overview.recent_activity.map((item) => (
            <Link href={item.href} key={`${item.kind}-${item.href}-${item.occurred_at}`}>
              <time>{new Date(item.occurred_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time><span className={`${styles.activityDot} ${styles[`tone_${item.tone}`]}`} aria-hidden="true" /><strong>{item.target}</strong><span>{item.label}</span>
            </Link>
          ))}</div> : <p className={styles.compactEmpty}>暂无近期活动。</p>}
        </Panel>

        <Panel className={`${styles.panel} ${styles.trustPanel}`}>
          <SectionHeading icon="◇" title="系统信任摘要" />
          <div className={styles.trustGrid}>
            <div><span>分析模式</span><strong className={styles.good}>{overview.trust.analysis_mode === "rules" ? "规则" : "模型"}</strong><small>{overview.trust.analysis_mode === "rules" ? "固定规则与已有证据" : "包含模型分析"}</small></div>
            <div><span>版本</span><strong>{overview.trust.version}</strong><small>{trustCommit}</small></div>
            <div><span>Schema</span><strong>{overview.trust.schema_revision.join(", ") || "未知"}</strong><small>{overview.trust.schema_current ? "与代码预期一致" : "需要检查"}</small></div>
            <div><span>数据来源</span><strong className={styles.good}>控制平面</strong><small>当前记录；无伪造成功数据</small></div>
          </div>
        </Panel>
      </div>
    </main>
  );
}

export function OverviewError({ forbidden = false }: { forbidden?: boolean }) {
  return <main className={styles.overview}><StateView state={forbidden ? "forbidden" : "error"} title={forbidden ? "无法读取运维总览" : "控制平面暂时不可用"} description={forbidden ? "当前可信 Principal 缺少总览所需的只读能力。" : "未使用虚假数据填充页面；请检查 API 服务后重试。"} /></main>;
}
