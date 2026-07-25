"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useState } from "react";
import type {
  ConversationTurn,
  EventHistory,
  EventReview,
  RunbookDraft,
  SimilarEvents,
} from "@/lib/api";

const historyLabels: Record<string, string> = {
  event: "事件",
  diagnostic: "诊断",
  conversation: "会话",
  operation: "操作",
};

export function EventInsights({
  history,
  similar,
  review,
  latestTurn,
}: {
  history: EventHistory | null;
  similar: SimilarEvents | null;
  review: EventReview | null;
  latestTurn: ConversationTurn | null;
}) {
  const router = useRouter();
  const [feedback, setFeedback] = useState<string>("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");

  async function submitFeedback(rating: "helpful" | "not_helpful") {
    if (!latestTurn || busy) return;
    setBusy("feedback");
    setError("");
    try {
      const response = await fetch(
        `/console/conversation-turns/${latestTurn.id}/feedback`,
        {
          method: "PUT",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ rating, reason_code: null, comment: null }),
        },
      );
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail ?? "保存反馈失败");
      setFeedback(rating);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "保存反馈失败");
    } finally {
      setBusy(null);
    }
  }

  async function createDraft() {
    if (!latestTurn?.answer?.recommendations.length || busy) return;
    setBusy("draft");
    setError("");
    try {
      const response = await fetch(
        `/console/conversation-turns/${latestTurn.id}/runbook-drafts`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            client_request_id: crypto.randomUUID(),
            recommendation_index: 0,
          }),
        },
      );
      const payload = (await response.json().catch(() => ({}))) as Partial<RunbookDraft> & {
        detail?: string;
      };
      if (!response.ok || !payload.id) {
        throw new Error(payload.detail ?? "创建 Runbook 草稿失败");
      }
      router.push(`/runbook-drafts/${payload.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建 Runbook 草稿失败");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="conversation-panel event-insights">
      <header>
        <div>
          <span className="eyebrow">M5.6–M5.7 · EXPLAINABLE</span>
          <h2>历史、相似事件与复盘</h2>
        </div>
        <p>
          相似事件由当前组织内的确定性规则筛选。反馈不会在线改变提示、权限或执行策略；Runbook 只能保存为不可执行草稿。
        </p>
      </header>

      {!history && !similar && !review && (
        <div className="empty">
          <strong>收尾体验尚未启用</strong>
          <span>现有事件会话、诊断和 M4 操作不受影响。</span>
        </div>
      )}

      {history && (
        <div className="insight-column">
          <h3>统一历史</h3>
          {history.items.map((item) => (
            <Link className="insight-row" href={item.href} key={`${item.item_type}-${item.id}`}>
              <span>{historyLabels[item.item_type] ?? item.item_type}</span>
              <strong>{item.summary}</strong>
              <small>{item.status} · {new Date(item.occurred_at).toLocaleString("zh-CN")}</small>
            </Link>
          ))}
        </div>
      )}

      {similar && (
        <div className="insight-column">
          <h3>相似事件</h3>
          {similar.items.length === 0 && <p className="muted">当前没有有依据的相似事件。</p>}
          {similar.items.map((item) => (
            <Link className="insight-row" href={item.href} key={item.id}>
              <span>{item.score_band}</span>
              <strong>{item.title}</strong>
              <small>{item.match_reasons.join(" · ")}</small>
            </Link>
          ))}
        </div>
      )}

      {review && (
        <div className="insight-column">
          <h3>{review.provisional ? "临时复盘" : "事件复盘"}</h3>
          <p>{review.summary}</p>
          <div className="diagnostic-grid">
            <article><h3>事实</h3>{review.facts.map((item, index) => <p key={index}>{item}</p>)}</article>
            <article><h3>推断</h3>{review.inferences.map((item, index) => <p key={index}>{item}</p>)}</article>
            <article><h3>操作结果</h3>{review.operation_results.map((item, index) => <p key={index}>{item}</p>)}</article>
            <article><h3>缺失证据</h3>{review.missing_evidence.map((item, index) => <p key={index}>{item}</p>)}</article>
          </div>
        </div>
      )}

      {latestTurn && (history || review) && (
        <div className="insight-actions">
          <strong>最新已完成回答</strong>
          <button disabled={busy !== null} onClick={() => void submitFeedback("helpful")}>
            {feedback === "helpful" ? "已标记有帮助" : "有帮助"}
          </button>
          <button disabled={busy !== null} onClick={() => void submitFeedback("not_helpful")}>
            {feedback === "not_helpful" ? "已标记无帮助" : "无帮助"}
          </button>
          {latestTurn.answer?.recommendations.length ? (
            <button disabled={busy !== null} onClick={() => void createDraft()}>
              {busy === "draft" ? "正在保存…" : "保存首条建议为 Runbook 草稿"}
            </button>
          ) : null}
          <span>草稿未审核、不可执行，不会创建 Operation。</span>
        </div>
      )}
      {error && <p className="error-text">{error}</p>}
    </section>
  );
}
