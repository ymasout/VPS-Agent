"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useMemo, useState } from "react";

import type { ServiceMappingBatchView, ServiceMappingCandidate } from "@/lib/api";
import styles from "./infrastructure.module.css";

function candidateId(candidate: ServiceMappingCandidate) {
  return `${candidate.agent_id}\u0000${candidate.service_kind}\u0000${candidate.service_key}\u0000${candidate.log_source_key}`;
}

export function ServiceMappingBatchPanel({ candidates, namedAuthorization = false }: { candidates: ServiceMappingCandidate[]; namedAuthorization?: boolean }) {
  const router = useRouter();
  const available = useMemo(() => candidates.filter((candidate) => !candidate.mapped), [candidates]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<ServiceMappingBatchView | null>(null);
  const [resultLabels, setResultLabels] = useState<Record<string, string>>({});

  if (available.length < 2) return null;

  async function submit(event: FormEvent) {
    event.preventDefault();
    const chosen = available.filter((candidate) => selected.has(candidateId(candidate))).slice(0, 20);
    if (chosen.length === 0) return;
    setLoading(true);
    setError("");
    setResult(null);
    setResultLabels(Object.fromEntries(chosen.map((candidate, index) => [`review-${index + 1}`, candidate.service_name])));
    try {
      const response = await fetch(namedAuthorization ? "/api/v1/service-mappings/batch" : "/console/service-mappings/batch", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          items: chosen.map((candidate, index) => ({
            client_item_id: `review-${index + 1}`,
            mapping: {
              name: candidate.service_name,
              environment: "production",
              agent_id: candidate.agent_id,
              service_kind: candidate.service_kind,
              service_key: candidate.service_key,
              deployment_directory: null,
              log_source_key: candidate.log_source_key,
              repository_full_name: null,
              criticality: "critical",
              restart_enabled: false,
            },
          })),
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "批量复核失败");
      setResult(payload as ServiceMappingBatchView);
      router.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "批量复核失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form className={styles.batchReview} onSubmit={submit}>
      <header>
        <div><h3>批量建立基础诊断映射</h3><p>仅适用于无需目录、仓库或操作授权差异的项目。每项固定为 production、关键服务、禁止重启；需要自定义的项目请使用下方逐项复核。</p></div>
        <span>{selected.size} / {Math.min(available.length, 20)} 已选择</span>
      </header>
      <div className={styles.batchOptions}>
        {available.slice(0, 20).map((candidate) => {
          const id = candidateId(candidate);
          return (
            <label className={styles.batchOption} key={id}>
              <input
                type="checkbox"
                checked={selected.has(id)}
                onChange={(event) => setSelected((current) => {
                  const next = new Set(current);
                  if (event.target.checked) next.add(id); else next.delete(id);
                  return next;
                })}
              />
              <span><strong>{candidate.service_name}</strong><span>{candidate.service_kind} · {candidate.state}</span></span>
              <span>production · critical · 只读诊断</span>
            </label>
          );
        })}
      </div>
      {error && <p role="alert">{error}</p>}
      {result && (
        <div aria-live="polite">
          <p>已创建 {result.created_count} 项，拒绝 {result.rejected_count} 项。成功项不会因其他项目失败而回退。</p>
          <ul className={styles.batchResults}>{result.results.map((item) => <li key={item.client_item_id}><span>{resultLabels[item.client_item_id] ?? item.client_item_id}</span><strong data-status={item.status}>{item.status === "created" ? "已创建" : `已拒绝 · ${item.detail ?? item.status_code}`}</strong></li>)}</ul>
        </div>
      )}
      <button type="submit" disabled={loading || selected.size === 0}>{loading ? "逐项复核中…" : `确认 ${selected.size} 项基础映射`}</button>
    </form>
  );
}
