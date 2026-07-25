"use client";

import React, { useCallback, useEffect, useState } from "react";
import { ConversationTurnResult } from "@/app/conversation-turn-result";
import type { ContextConversation, ConversationTurn } from "@/lib/api";

const terminalStatuses = new Set(["completed", "failed"]);

export function ContextConversationPanel({
  initial,
  endpoint,
  unavailable = false,
}: {
  initial: ContextConversation;
  endpoint: string;
  unavailable?: boolean;
}) {
  const [turns, setTurns] = useState(initial.turns);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(
    initial.turns.some((item) => !terminalStatuses.has(item.status)),
  );
  const [error, setError] = useState(
    unavailable ? "控制平面暂时不可用，无法加载上下文会话。" : "",
  );
  const bytes = new TextEncoder().encode(question.trim()).length;
  const valid =
    question.trim().length > 0 && question.length <= 2000 && bytes <= 8192;
  const writable = initial.available && !unavailable;
  const scopeLabel =
    initial.scope_type === "agent"
      ? "Agent"
      : initial.scope_type === "service"
        ? "服务"
        : "Fleet";

  const replaceTurn = useCallback((updated: ConversationTurn) => {
    setTurns((current) =>
      current.some((item) => item.id === updated.id)
        ? current.map((item) => (item.id === updated.id ? updated : item))
        : [...current, updated],
    );
  }, []);

  const pollTurn = useCallback(
    async (turnId: string) => {
      for (let attempt = 0; attempt < 90; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1500));
        const response = await fetch(`/console/conversation-turns/${turnId}`, {
          cache: "no-store",
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.detail ?? "读取会话状态失败");
        const updated = payload as ConversationTurn;
        replaceTurn(updated);
        if (terminalStatuses.has(updated.status)) return;
      }
      throw new Error("会话处理超时，请稍后刷新页面查看。");
    },
    [replaceTurn],
  );

  useEffect(() => {
    const active = initial.turns.find(
      (item) => !terminalStatuses.has(item.status),
    );
    if (!active) return;
    let mounted = true;
    void pollTurn(active.id)
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
    if (!valid || busy || !writable) return;
    setBusy(true);
    setError("");
    try {
      const response = await fetch(endpoint, {
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

  return (
    <section className="conversation-panel context-conversation">
      <header>
        <div>
          <span className="eyebrow">M5 · {scopeLabel.toUpperCase()} · READ ONLY</span>
          <h2>{scopeLabel}会话</h2>
        </div>
        <p>
          只读取当前{scopeLabel}在控制平面中已有的摘要、事件、诊断证据和操作结果。
          不访问 VPS、Agent 或 GitHub 网络，也不会创建或确认 Operation。
        </p>
      </header>
      {!initial.available && !unavailable && (
        <div className="empty error">
          <strong>{initial.unavailable_reason ?? "feature_disabled"}</strong>
          <span>当前不能创建新轮次；已有历史仅作为只读审计保留。</span>
        </div>
      )}
      {turns.length === 0 && !unavailable && (
        <div className="empty">
          <strong>尚无{scopeLabel}会话历史</strong>
          <span>可以询问当前健康状态、相关事件、诊断证据或既有操作结果。</span>
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
              pendingDetail={`只读取当前${scopeLabel}已有控制平面记录，不执行操作。`}
              pendingTitle={`正在整理${scopeLabel}上下文`}
              turn={turn}
            />
          </article>
        ))}
      </div>
      <div className="conversation-composer">
        <textarea
          aria-label={`${scopeLabel}会话问题`}
          disabled={busy || !writable}
          maxLength={2000}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder={
            initial.scope_type === "agent"
              ? "例如：这台机器当前有哪些需要关注的异常？"
              : initial.scope_type === "service"
                ? "例如：这个服务最近的异常和诊断结论是什么？"
                : "例如：当前 Fleet 中最需要优先关注哪些异常？"
          }
          rows={4}
          value={question}
        />
        <div>
          <span className={bytes > 8192 ? "error-text" : "muted"}>
            {question.length}/2000 字符 · {bytes}/8192 bytes
          </span>
          <button disabled={!valid || busy || !writable} onClick={submit}>
            {busy ? "正在分析…" : "发送只读问题"}
          </button>
        </div>
        {error && <p className="error-text">{error}</p>}
      </div>
    </section>
  );
}
