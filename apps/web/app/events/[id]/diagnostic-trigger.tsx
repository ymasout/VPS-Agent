"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function DiagnosticTrigger({ eventId, disabled }: { eventId: string; disabled: boolean }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function trigger() {
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`/console/events/${eventId}/diagnostics`, { method: "POST" });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail ?? "诊断请求失败");
      }
      router.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "诊断请求失败");
    } finally {
      setBusy(false);
    }
  }

  return <div className="diagnostic-action">
    <button disabled={disabled || busy} onClick={trigger}>{busy ? "正在发起…" : "只读诊断"}</button>
    {error && <span>{error}</span>}
  </div>;
}
