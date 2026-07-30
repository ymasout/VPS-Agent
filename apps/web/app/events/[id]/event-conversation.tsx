"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useCallback, useEffect, useRef, useState } from "react";
import type {
  ConversationOperationCandidate,
  ConversationOperationTimeline,
  ConversationTurn,
  EventConversation,
} from "@/lib/api";
import { ConversationTurnResult } from "@/app/conversation-turn-result";

const terminalStatuses = new Set(["completed", "failed"]);
const actionLabels: Record<string, string> = {
  docker_restart: "安全重启",
  docker_compose_deploy: "Compose 部署/回滚",
};
const verificationLabels: Record<string, string> = {
  waiting_for_fresh_observation: "等待新鲜观测",
  waiting_for_deployment_observation: "等待目标 digest 与健康观测",
  waiting_for_healthy_observation: "等待健康观测",
  stability_window: "健康稳定窗口观察中",
  passed: "健康验证通过",
  failed: "健康验证失败",
};

export function EventConversationPanel({
  initial,
  unavailable = false,
  operationCandidates = [],
  operationTimeline,
  deploymentHref = null,
  namedAuthorization = false,
}: {
  initial: EventConversation;
  unavailable?: boolean;
  operationCandidates?: ConversationOperationCandidate[];
  operationTimeline?: ConversationOperationTimeline;
  deploymentHref?: string | null;
  namedAuthorization?: boolean;
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
  const [planBusy, setPlanBusy] = useState<string | null>(null);
  const [planError, setPlanError] = useState("");
  const planRequestIds = useRef<Record<string, string>>({});
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

  async function preparePlan(
    turnId: string,
    actionType: ConversationOperationCandidate["action_type"],
  ) {
    const candidate = operationCandidates.find((item) => item.action_type === actionType);
    if (planBusy || !candidate?.available) return;
    setPlanBusy(actionType);
    setPlanError("");
    planRequestIds.current[actionType] ??= crypto.randomUUID();
    const path = actionType === "docker_restart" ? "restart-plan" : "rollback-plan";
    const errorLabel = actionType === "docker_restart" ? "安全重启" : "显式回滚";
    try {
      const response = await fetch(
        `${namedAuthorization ? "/api/v1" : "/console"}/events/${initial.event_id}/conversation/turns/${turnId}/${path}`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            client_request_id: planRequestIds.current[actionType],
            expires_in_seconds: 300,
          }),
        },
      );
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail ?? `创建${errorLabel}计划失败`);
      router.push(`/operations/${payload.id}`);
    } catch (reason) {
      setPlanError(reason instanceof Error ? reason.message : `创建${errorLabel}计划失败`);
    } finally {
      setPlanBusy(null);
    }
  }

  const latestCompletedTurn = [...turns]
    .reverse()
    .find((item) => item.status === "completed" && item.answer);
  const restartCandidate = operationCandidates.find(
    (item) => item.action_type === "docker_restart",
  );
  const rollbackCandidate = operationCandidates.find(
    (item) => item.action_type === "docker_compose_rollback",
  );
  const hasOperationCandidate = operationCandidates.some((item) => item.available);
  const timeline = operationTimeline ?? {
    event_id: initial.event_id,
    available: false,
    unavailable_reason: "feature_disabled",
    operations: [],
  };

  return (
    <section className="conversation-panel">
      <header>
        <div>
          <span className="eyebrow">M5.2 · READ ONLY</span>
          <h2>事件会话</h2>
        </div>
        <p>
          发送问题只使用当前事件已有记录，不会访问 VPS、领取 Agent 任务或创建 Operation。
          {hasOperationCandidate
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
            {hasOperationCandidate && latestCompletedTurn?.id === turn.id && (
              <div className="conversation-operation-handoff">
                <div>
                  <strong>需要进一步处置？</strong>
                  <span>
                    只创建待确认计划，不会立即访问 Agent 或操作服务。创建后仍需在操作页独立确认。
                  </span>
                </div>
                {restartCandidate?.available && (
                  <button
                    disabled={planBusy !== null}
                    onClick={() => void preparePlan(turn.id, "docker_restart")}
                    type="button"
                  >
                    {planBusy === "docker_restart" ? "正在准备计划…" : "准备安全重启计划"}
                  </button>
                )}
                {rollbackCandidate?.available && (
                  <>
                    <span>
                      回滚来源和目标镜像由服务端从当前事件关联的失败部署记录派生，不读取会话文本。
                    </span>
                    <button
                      disabled={planBusy !== null}
                      onClick={() => void preparePlan(turn.id, "docker_compose_rollback")}
                      type="button"
                    >
                      {planBusy === "docker_compose_rollback"
                        ? "正在准备计划…"
                        : "准备回滚计划"}
                    </button>
                  </>
                )}
                {planError && <p className="error-text">{planError}</p>}
              </div>
            )}
          </article>
        ))}
      </div>

      <section className="conversation-operation-history">
        <header>
          <div>
            <span className="eyebrow">M5.3.3 · READ ONLY</span>
            <h3>相关操作</h3>
          </div>
          {timeline.available && deploymentHref && (
            <Link href={deploymentHref}>前往 M4.2 部署候选</Link>
          )}
        </header>
        {!timeline.available && (
          <div className={`empty ${timeline.unavailable_reason === "control_plane_unavailable" ? "error" : ""}`}>
            <strong>
              {timeline.unavailable_reason === "control_plane_unavailable"
                ? "操作时间线暂时不可用"
                : "操作时间线尚未启用"}
            </strong>
            <span>这里不会创建、确认或执行任何 Operation。</span>
          </div>
        )}
        {timeline.available && timeline.operations.length === 0 && (
          <div className="empty">
            <strong>当前事件没有关联操作</strong>
            <span>只读提问和查看历史不会产生 Operation。</span>
          </div>
        )}
        {timeline.available && timeline.operations.map((operation) => (
          <article className="conversation-operation-summary" key={operation.id}>
            <header>
              <div>
                <span>{actionLabels[operation.action_type] ?? operation.action_type}</span>
                <strong>{operation.status}</strong>
              </div>
              <time>{new Date(operation.requested_at).toLocaleString("zh-CN")}</time>
            </header>
            <p>{operation.impact_summary}</p>
            {operation.verification_status && (
              <small>
                {verificationLabels[operation.verification_status] ?? "验证状态不可识别"}
              </small>
            )}
            {operation.error_code && (
              <p className="error-text">
                {operation.error_code}
                {operation.error_summary ? ` · ${operation.error_summary}` : ""}
              </p>
            )}
            <details>
              <summary>审计时间线（{operation.transitions.length}）</summary>
              {operation.transitions.map((transition, index) => (
                <div
                  className="conversation-operation-transition"
                  key={`${transition.created_at}-${index}`}
                >
                  <strong>
                    {transition.from_status ?? "created"} → {transition.to_status}
                  </strong>
                  <span>
                    {transition.actor_type}
                  </span>
                  <time>{new Date(transition.created_at).toLocaleString("zh-CN")}</time>
                </div>
              ))}
            </details>
            <Link href={`/operations/${encodeURIComponent(operation.id)}`}>
              查看操作详情
            </Link>
          </article>
        ))}
      </section>

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
