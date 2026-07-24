"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import type {
  ConversationOperationCandidate,
  ConversationTurn,
  EventConversation,
} from "@/lib/api";
import { ConversationTurnResult } from "@/app/conversation-turn-result";

const terminalStatuses = new Set(["completed", "failed"]);

export function EventConversationPanel({
  initial,
  unavailable = false,
  operationCandidate = null,
}: {
  initial: EventConversation;
  unavailable?: boolean;
  operationCandidate?: ConversationOperationCandidate | null;
}) {
  const router = useRouter();
  const [turns, setTurns] = useState(initial.turns);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(
    initial.turns.some((item) => !terminalStatuses.has(item.status)),
  );
  const [error, setError] = useState(
    unavailable ? "控制平面暂时不可用，无法加载事件会话。" : "",
  );
  const [planBusy, setPlanBusy] = useState(false);
  const [planError, setPlanError] = useState("");
  const planRequestId = useRef<string | null>(null);
  const byteLength = new TextEncoder().encode(question.trim()).length;
  const valid = question.trim().length > 0 && question.length <= 2000 && byteLength <= 8192;

  const replaceTurn = useCallback((updated: ConversationTurn) => {
    setTurns((current) => {
      const found = current.some((item) => item.id === updated.id);
      return found
        ? current.map((item) => (item.id === updated.id ? updated : item))
        : [...current, updated];
    });
  }, []);

  const pollTurn = useCallback(async (turnId: string) => {
    for (let attempt = 0; attempt < 90; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 1500));
      const response = await fetch(`/console/conversation-turns/${turnId}`, {
        cache: "no-store",
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail ?? "读取会话状态失败");
      }
      const updated = (await response.json()) as ConversationTurn;
      replaceTurn(updated);
      if (terminalStatuses.has(updated.status)) return;
    }
    throw new Error("会话处理超时，请稍后刷新页面查看。");
  }, [replaceTurn]);

  useEffect(() => {
    const activeTurn = initial.turns.find((item) => !terminalStatuses.has(item.status));
    if (!activeTurn) return;
    let mounted = true;
    void pollTurn(activeTurn.id)
      .catch((reason) => {
        if (mounted) {
          setError(reason instanceof Error ? reason.message : "读取会话状态失败");
        }
      })
      .finally(() => {
        if (mounted) setBusy(false);
      });
    return () => {
      mounted = false;
    };
  }, [initial.turns, pollTurn]);

  async function submit() {
    if (!valid || busy) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`/console/events/${initial.event_id}/conversation/turns`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          client_request_id: crypto.randomUUID(),
          question: question.trim(),
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail ?? "提交问题失败");
      const turn = payload as ConversationTurn;
      replaceTurn(turn);
      setQuestion("");
      if (!terminalStatuses.has(turn.status)) await pollTurn(turn.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "提交问题失败");
    } finally {
      setBusy(false);
    }
  }

  async function prepareRestartPlan(turnId: string) {
    if (planBusy || !operationCandidate?.available) return;
    setPlanBusy(true);
    setPlanError("");
    planRequestId.current ??= crypto.randomUUID();
    try {
      const response = await fetch(
        `/console/events/${initial.event_id}/conversation/turns/${turnId}/restart-plan`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            client_request_id: planRequestId.current,
            expires_in_seconds: 300,
          }),
        },
      );
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail ?? "创建安全重启计划失败");
      router.push(`/operations/${payload.id}`);
    } catch (reason) {
      setPlanError(reason instanceof Error ? reason.message : "创建安全重启计划失败");
    } finally {
      setPlanBusy(false);
    }
  }

  const latestCompletedTurn = [...turns]
    .reverse()
    .find((item) => item.status === "completed" && item.answer);

  return (
    <section className="conversation-panel">
      <header>
        <div>
          <span className="eyebrow">M5.2 · READ ONLY</span>
          <h2>事件会话</h2>
        </div>
        <p>
          发送问题只使用当前事件已有记录，不会访问 VPS、领取 Agent 任务或创建 Operation。
          {operationCandidate?.available
            ? " 下方独立按钮只能准备待确认计划。"
            : ""}
        </p>
      </header>

      {turns.length === 0 && !unavailable && (
        <div className="empty">
          <strong>尚无会话历史</strong>
          <span>可以询问目前确认了什么、哪些是推断、还缺什么证据。</span>
        </div>
      )}
      <div className="conversation-history">
        {turns.map((turn) => (
          <article className="conversation-turn" key={turn.id}>
            <div className="conversation-question">
              <span>你的问题</span>
              <p>{turn.question}</p>
              <time>{new Date(turn.created_at).toLocaleString("zh-CN")}</time>
            </div>
            <ConversationTurnResult
              pendingTitle="正在整理事件上下文"
              turn={turn}
            />
            {operationCandidate?.available && latestCompletedTurn?.id === turn.id && (
              <div className="conversation-operation-handoff">
                <div>
                  <strong>需要进一步处置？</strong>
                  <span>
                    只创建待确认计划，不会立即访问 Agent 或重启服务。创建后仍需在操作页独立确认。
                  </span>
                </div>
                <button
                  disabled={planBusy}
                  onClick={() => void prepareRestartPlan(turn.id)}
                  type="button"
                >
                  {planBusy ? "正在准备计划…" : "准备安全重启计划"}
                </button>
                {planError && <p className="error-text">{planError}</p>}
              </div>
            )}
          </article>
        ))}
      </div>

      <div className="conversation-composer">
        <textarea
          aria-label="事件会话问题"
          disabled={busy || unavailable}
          maxLength={2000}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="例如：这个事件目前有哪些已确认事实？"
          rows={4}
          value={question}
        />
        <div>
          <span className={byteLength > 8192 ? "error-text" : "muted"}>
            {question.length}/2000 字符 · {byteLength}/8192 bytes
          </span>
          <button disabled={!valid || busy || unavailable} onClick={submit}>
            {busy ? "正在分析…" : "发送只读问题"}
          </button>
        </div>
        {error && <p className="error-text">{error}</p>}
      </div>
    </section>
  );
}
