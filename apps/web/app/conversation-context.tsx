import React from "react";
import Link from "next/link";
import type { ConversationTurn } from "@/lib/api";

type ConversationModeEnvelope = {
  analysis_mode?: "rules" | "model" | null;
  provider_available?: boolean | null;
  provider_label?: string | null;
  context_scope?: string | null;
  context_captured_at?: string | null;
};

export function conversationModeLabel(value: ConversationModeEnvelope["analysis_mode"]) {
  if (value === "rules") return "规则分析";
  if (value === "model") return "模型分析";
  return "分析模式未知";
}

function timestamp(value: string | null | undefined) {
  if (!value) return "尚未捕获上下文";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? "上下文时间未知"
    : `${parsed.toISOString().slice(0, 19).replace("T", " ")} UTC`;
}

export function ConversationContextRail({
  envelope,
  turns,
  lastSnapshot = false,
}: {
  envelope: ConversationModeEnvelope;
  turns: ConversationTurn[];
  lastSnapshot?: boolean;
}) {
  const latest = [...turns].reverse().find((turn) => turn.citations.length > 0);
  return (
    <aside className="conversation-context-rail" aria-label="当前会话上下文与引用">
      <section>
        <span className="eyebrow">当前上下文</span>
        <strong>{envelope.context_scope ?? "unknown"}</strong>
        <small>{timestamp(envelope.context_captured_at)}</small>
        {lastSnapshot && <p className="conversation-snapshot-warning">Agent 离线 · 使用控制平面最后快照</p>}
      </section>
      <section>
        <span className="eyebrow">分析来源</span>
        <strong>{envelope.provider_label ?? conversationModeLabel(envelope.analysis_mode)}</strong>
        <small>{envelope.provider_available === false ? "Provider 当前不可用" : envelope.provider_available === true ? "Provider 配置可用" : "Provider 状态未知"}</small>
        <p>分析来源不改变授权等级；自然语言建议不会直接执行。</p>
      </section>
      <section>
        <span className="eyebrow">引用与证据</span>
        {!latest && <p>当前尚无经过服务端验证的引用。</p>}
        {latest && (
          <details>
            <summary>{latest.citations.length} 项真实引用</summary>
            <ul>
              {latest.citations.map((citation) => (
                <li key={citation.id}>
                  {citation.href ? <Link href={citation.href}>{citation.source_label}</Link> : <strong>{citation.source_label}</strong>}
                  <small>{citation.source_type} · {timestamp(citation.source_collected_at)}</small>
                  {citation.repository?.truncated && <small>仓库证据已截断</small>}
                  {citation.repository?.stale && <small>仓库证据可能过期</small>}
                </li>
              ))}
            </ul>
          </details>
        )}
      </section>
    </aside>
  );
}
