import Link from "next/link";
import {
  ControlPlaneApiError,
  getConversationOperationCandidates,
  getEvent,
  getEventConversation,
  getEventDiagnostics,
  type AlertEvent,
  type ConversationOperationCandidate,
  type EventConversation,
} from "@/lib/api";
import { notFound } from "next/navigation";
import { DiagnosticTrigger } from "./diagnostic-trigger";
import { OperationCreate } from "./operation-create";
import { EventConversationPanel } from "./event-conversation";

export const dynamic = "force-dynamic";

export default async function EventPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  let event: AlertEvent | null = null;
  try {
    event = await getEvent(id);
  } catch (reason) {
    if (reason instanceof ControlPlaneApiError && reason.status === 404) notFound();
  }
  if (event === null) {
    return (
      <main>
        <Link className="back" href="/">← 总览</Link>
        <div className="empty error">
          <strong>控制平面暂时不可用</strong>
          <span>事件是否存在尚未确认，请稍后刷新；本状态不会显示为事件不存在。</span>
        </div>
      </main>
    );
  }
  const [diagnosticsResult, conversationResult, operationCandidatesResult] =
    await Promise.allSettled([
      getEventDiagnostics(id),
      getEventConversation(id),
      getConversationOperationCandidates(id),
    ]);
  const diagnostics = diagnosticsResult.status === "fulfilled" ? diagnosticsResult.value : [];
  const conversation: EventConversation =
    conversationResult.status === "fulfilled"
      ? conversationResult.value
      : { event_id: event.id, session_id: null, turns: [] };
  const conversationUnavailable = conversationResult.status === "rejected";
  const operationCandidate: ConversationOperationCandidate | null =
    operationCandidatesResult.status === "fulfilled"
      ? operationCandidatesResult.value.candidates[0] ?? null
      : null;
  const active = diagnostics.some((item) => item.status === "pending" || item.status === "running");
  const machineEvent = event.source === "agent";

  return <main>
    <Link className="back" href="/">← 总览</Link>
    <section className="hero compact detail-head event-head">
      <div className={`status ${event.status === "resolved" ? "" : "offline"}`}><span /> {event.status}</div>
      <h1>{event.title}</h1>
      <p>{event.service_kind ?? event.source} · {event.service_key ?? event.agent_id} · 观测 {event.observation_count} 次</p>
      <DiagnosticTrigger eventId={event.id} disabled={active} />
      {!machineEvent && event.service_kind === "docker" && <OperationCreate eventId={event.id} diagnosticId={diagnostics[0]?.id} />}
    </section>

    {diagnostics.length === 0 && <div className="empty"><strong>尚无诊断</strong><span>{machineEvent ? "发起后只分析控制平面保存的最后心跳、资源与服务快照，不会等待离线 Agent。" : "发起后，Agent 只会读取本地白名单中的有限日志窗口。"}</span></div>}
    {diagnostics.map((diagnostic) => <section className="diagnostic" key={diagnostic.id}>
      <div className="diagnostic-meta"><span>{diagnostic.status}</span><span>{diagnostic.provider}</span><time>{new Date(diagnostic.created_at).toLocaleString("zh-CN")}</time></div>
      {diagnostic.error_detail && <div className="empty error">{diagnostic.error_code} · {diagnostic.error_detail}</div>}
      {!diagnostic.result && <div className="empty"><strong>证据采集中</strong><span>{machineEvent ? "正在整理控制平面已有的机器级证据。" : "等待 Agent 领取只读请求并回传有界结果。"}</span></div>}
      {diagnostic.result && <>
        <h2>{diagnostic.result.summary}</h2>
        <div className="diagnostic-grid">
          <article><h3>事实</h3>{diagnostic.result.facts.map((item, index) => <div key={index}><p>{item.statement}</p><small>{item.evidence_ids.join(" · ")}</small></div>)}</article>
          <article><h3>推断</h3>{diagnostic.result.inferences.length === 0 ? <p className="muted">当前没有足够证据形成推断。</p> : diagnostic.result.inferences.map((item, index) => <div key={index}><p>{item.statement}</p><small>{item.confidence} · {item.evidence_ids.join(" · ")}</small></div>)}</article>
          <article><h3>建议</h3>{diagnostic.result.recommendations.map((item, index) => <div key={index}><p>{item.action}</p><small>{item.risk} risk · {item.requires_confirmation ? "需要确认" : "只读"}</small></div>)}</article>
          <article><h3>缺失证据</h3>{diagnostic.result.missing_evidence.map((item, index) => <p key={index}>{item}</p>)}</article>
        </div>
      </>}
      <details className="evidence-panel"><summary>证据（{diagnostic.evidence.length}）</summary>{diagnostic.evidence.map((item) => <article id={item.id} key={item.id}><header><strong>{item.source_label}</strong><span>{item.redacted ? "已脱敏" : "未脱敏"}{item.truncated ? " · 已截断" : ""}</span></header><pre>{item.content}</pre></article>)}</details>
    </section>)}
    <EventConversationPanel
      initial={conversation}
      unavailable={conversationUnavailable}
      operationCandidate={operationCandidate}
    />
  </main>;
}
