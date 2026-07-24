"use client";

import { useCallback, useEffect, useState } from "react";
import { ConversationTurnResult } from "@/app/conversation-turn-result";
import type {
  ConversationTurn,
  RepositoryConversation,
} from "@/lib/api";

const terminalStatuses = new Set(["completed", "failed"]);

export function RepositoryConversationPanel({
  initial,
  unavailable = false,
}: {
  initial: RepositoryConversation;
  unavailable?: boolean;
}) {
  const [turns, setTurns] = useState(initial.turns);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(
    initial.turns.some((item) => !terminalStatuses.has(item.status)),
  );
  const [error, setError] = useState(
    unavailable ? "控制平面暂时不可用，无法加载仓库会话。" : "",
  );
  const byteLength = new TextEncoder().encode(question.trim()).length;
  const valid =
    question.trim().length > 0 &&
    question.length <= 2000 &&
    byteLength <= 8192;
  const writable = initial.available && !unavailable;

  const replaceTurn = useCallback((updated: ConversationTurn) => {
    setTurns((current) => {
      const found = current.some((item) => item.id === updated.id);
      return found
        ? current.map((item) => (item.id === updated.id ? updated : item))
        : [...current, updated];
    });
  }, []);

  const pollTurn = useCallback(
    async (turnId: string) => {
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
    },
    [replaceTurn],
  );

  useEffect(() => {
    const activeTurn = initial.turns.find(
      (item) => !terminalStatuses.has(item.status),
    );
    if (!activeTurn) return;
    let mounted = true;
    void pollTurn(activeTurn.id)
      .catch((reason) => {
        if (mounted) {
          setError(
            reason instanceof Error ? reason.message : "读取会话状态失败",
          );
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
      const response = await fetch(
        `/console/repositories/${initial.repository_id}/conversation/turns`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            client_request_id: crypto.randomUUID(),
            question: question.trim(),
          }),
        },
      );
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
    <section className="conversation-panel repository-conversation">
      <header>
        <div>
          <span className="eyebrow">M5.2.2 · READ ONLY</span>
          <h2>仓库会话</h2>
        </div>
        <p>
          只读取当前授权仓库在控制平面中的脱敏快照。回答不代表 VPS
          当前部署版本，也不会访问 GitHub、VPS、Agent 或创建 Operation。
        </p>
      </header>

      {!initial.available && !unavailable && (
        <div className="empty error">
          <strong>{initial.unavailable_reason ?? "repository_unavailable"}</strong>
          <span>当前不能创建新轮次；已有历史仅作为只读审计保留。</span>
        </div>
      )}
      {turns.length === 0 && !unavailable && (
        <div className="empty">
          <strong>尚无仓库会话历史</strong>
          <span>可以询问当前快照中的配置、入口、依赖或健康检查。</span>
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
              pendingDetail="只读取当前仓库已有脱敏快照，不访问 GitHub 网络或执行操作。"
              pendingTitle="正在整理仓库快照"
              turn={turn}
            />
          </article>
        ))}
      </div>

      <div className="conversation-composer">
        <textarea
          aria-label="仓库会话问题"
          disabled={busy || !writable}
          maxLength={2000}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="例如：compose.yaml 中如何配置健康检查？"
          rows={4}
          value={question}
        />
        <div>
          <span className={byteLength > 8192 ? "error-text" : "muted"}>
            {question.length}/2000 字符 · {byteLength}/8192 bytes
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
