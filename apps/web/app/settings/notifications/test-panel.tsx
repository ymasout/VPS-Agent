"use client";

import { useEffect, useRef, useState } from "react";
import type { NotificationTest } from "@/lib/api";

const terminalStatuses = new Set(["succeeded", "failed", "delivery_outcome_unknown"]);

export function NotificationTestPanel({
  channel,
  channelLabel,
  configured,
  enabled,
  cooldownSeconds,
  initialTests,
}: {
  channel: "dingtalk" | "telegram";
  channelLabel: string;
  configured: boolean;
  enabled: boolean;
  cooldownSeconds: number;
  initialTests: NotificationTest[];
}) {
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [online, setOnline] = useState(true);
  const [tests, setTests] = useState(initialTests);
  const [error, setError] = useState("");
  const requestId = useRef<string | null>(null);

  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    update();
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);

  async function poll(id: string) {
    for (let attempt = 0; attempt < 20; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 750));
      const response = await fetch(`/console/notification-tests/${encodeURIComponent(id)}`, {
        cache: "no-store",
      });
      if (!response.ok) throw new Error("无法读取测试消息状态");
      const current = await response.json() as NotificationTest;
      setTests((items) => [current, ...items.filter((item) => item.id !== current.id)].slice(0, 10));
      if (terminalStatuses.has(current.status)) return;
    }
    throw new Error("测试消息仍在处理中，请稍后刷新页面");
  }

  async function sendTest() {
    if (!configured || !enabled || !acknowledged || busy || !online) return;
    setBusy(true);
    setError("");
    requestId.current ??= crypto.randomUUID();
    try {
      const response = await fetch(`/console/notification-tests/${channel}`, {
        method: "POST",
        headers: { "Idempotency-Key": requestId.current },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail ?? "测试消息请求失败");
      const created = payload as NotificationTest;
      setTests((items) => [created, ...items.filter((item) => item.id !== created.id)].slice(0, 10));
      await poll(created.id);
      requestId.current = null;
      setAcknowledged(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "测试消息请求失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="section notification-test-panel">
      <div className="section-title"><h2>{channelLabel} 测试消息</h2><span>audited · one attempt</span></div>
      <div className="notification-guide">
        <p>固定发送一条不含事件、凭据或运维数据的 {channelLabel} 测试消息。每个请求 UUID 幂等，数据库按 {cooldownSeconds} 秒固定窗口限速；发送结果只记录有限状态和稳定错误码。</p>
        <label className="approval-check">
          <input
            type="checkbox"
            checked={acknowledged}
            onChange={(event) => setAcknowledged(event.target.checked)}
          />
          <span>我确认现在向已配置的 {channelLabel} 目标发送一条测试消息。</span>
        </label>
        <button
          className="approval-submit"
          type="button"
          disabled={!configured || !enabled || !acknowledged || busy || !online}
          onClick={sendTest}
        >
          {busy ? "发送并核对中…" : "发送一次测试消息"}
        </button>
        {!configured && <p className="error-text">{channelLabel} 通道尚未配置，测试入口保持禁用。</p>}
        {!enabled && <p className="error-text">测试消息功能默认关闭；需通过服务器配置显式开启。</p>}
        {!online && <p className="error-text">当前离线，测试入口保持禁用。</p>}
        {error && <p className="error-text" role="alert">{error}</p>}
      </div>
      <div className="notification-test-history">
        {tests.map((test) => (
          <article key={test.id}>
            <div><strong>{test.status}</strong><span>{new Date(test.created_at).toLocaleString("zh-CN")}</span></div>
            <p>{test.channel} · 尝试 {test.attempt_count}/1 · {test.error_code ?? "无错误"}</p>
            <small>audit {test.id}</small>
          </article>
        ))}
        {tests.length === 0 && <div className="empty">尚无测试消息审计记录。</div>}
      </div>
    </section>
  );
}
