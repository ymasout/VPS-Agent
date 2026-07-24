"use client";

import Link from "next/link";
import type { ConversationCitation, ConversationTurn } from "@/lib/api";
import { conversationCitationLabel } from "@/lib/conversation";

function CitationLinks({
  ids,
  citations,
}: {
  ids: string[];
  citations: ConversationCitation[];
}) {
  const byId = new Map(citations.map((item) => [item.id, item]));
  return (
    <small className="conversation-citations">
      {ids.map((id) => {
        const citation = byId.get(id);
        if (!citation) {
          return <span key={id}>引用不可用</span>;
        }
        const label = conversationCitationLabel(citation);
        return citation.href ? (
          <Link href={citation.href} key={id}>
            {label}
          </Link>
        ) : (
          <span key={id}>{label}</span>
        );
      })}
    </small>
  );
}

export function ConversationTurnResult({
  turn,
  pendingTitle = "正在整理只读上下文",
  pendingDetail = "只读取控制平面已有记录，不访问 VPS，也不会执行操作。",
}: {
  turn: ConversationTurn;
  pendingTitle?: string;
  pendingDetail?: string;
}) {
  if (turn.status === "failed") {
    return (
      <div className="empty error">
        <strong>{turn.error_code ?? "conversation_failed"}</strong>
        <span>{turn.error_detail ?? "本轮会话未能生成经过验证的回答。"}</span>
      </div>
    );
  }
  if (!turn.answer) {
    return (
      <div className="empty">
        <strong>{pendingTitle}</strong>
        <span>{pendingDetail}</span>
      </div>
    );
  }
  return (
    <div className="conversation-answer">
      <h3>{turn.answer.summary}</h3>
      <div className="diagnostic-grid">
        <article>
          <h3>已确认事实</h3>
          {turn.answer.facts.map((item, index) => (
            <div key={index}>
              <p>{item.statement}</p>
              <CitationLinks ids={item.citation_ids} citations={turn.citations} />
            </div>
          ))}
        </article>
        <article>
          <h3>推断</h3>
          {turn.answer.inferences.length === 0 ? (
            <p className="muted">当前没有足够依据形成推断。</p>
          ) : (
            turn.answer.inferences.map((item, index) => (
              <div key={index}>
                <p>{item.statement}</p>
                <small>{item.confidence}</small>
                <CitationLinks ids={item.citation_ids} citations={turn.citations} />
              </div>
            ))
          )}
        </article>
        <article>
          <h3>建议</h3>
          {turn.answer.recommendations.map((item, index) => (
            <div key={index}>
              <p>{item.action}</p>
              <small>
                {item.risk} risk ·{" "}
                {item.requires_confirmation
                  ? "未授权，写操作仍需受控计划确认"
                  : "只读建议"}
              </small>
              <CitationLinks ids={item.citation_ids} citations={turn.citations} />
            </div>
          ))}
        </article>
        <article>
          <h3>缺失信息</h3>
          {turn.answer.missing_evidence.map((item, index) => (
            <p key={index}>{item}</p>
          ))}
        </article>
      </div>
    </div>
  );
}
