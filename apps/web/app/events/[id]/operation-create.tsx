"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function OperationCreate({ eventId, diagnosticId }: { eventId: string; diagnosticId?: string }) {
  const router = useRouter();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  async function create() {
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/console/operations", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ event_id: eventId, diagnostic_id: diagnosticId ?? null, action_type: "docker_restart" }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "创建计划失败");
      router.push(`/operations/${payload.id}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建计划失败");
    } finally {
      setLoading(false);
    }
  }
  return <div><button type="button" onClick={create} disabled={loading}>{loading ? "预检查中…" : "创建安全重启计划"}</button>{error && <p className="mapping-error" role="alert">{error}</p>}</div>;
}
