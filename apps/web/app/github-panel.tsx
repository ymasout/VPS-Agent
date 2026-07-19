"use client";

import { GitHubRepository, GitHubStatus } from "@/lib/api";
import { useRouter } from "next/navigation";
import { useState } from "react";

export function GitHubPanel({ status, repositories }: { status: GitHubStatus; repositories: GitHubRepository[] }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function synchronize() {
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/console/github/sync", { method: "POST" });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.detail ?? "GitHub 同步失败");
      router.refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "GitHub 同步失败");
    } finally {
      setBusy(false);
    }
  }

  return <section className="section github-panel">
    <div className="section-title"><h2>GitHub App</h2><span>{repositories.length} repositories</span></div>
    <p className="section-copy">只读取 App 已授权仓库的 Commit 和白名单文件：{status.allowed_file_paths.join("、") || "未配置"}。安装令牌和私钥不会下发给 VPS Agent。</p>
    <div className="github-actions">
      <button type="button" onClick={synchronize} disabled={busy}>{busy ? "同步中…" : "同步已授权仓库"}</button>
      {status.installation_url && <a href={status.installation_url} target="_blank" rel="noreferrer">管理 GitHub App 安装范围</a>}
    </div>
    {error && <p className="mapping-error" role="alert">{error}</p>}
    {repositories.length > 0 && <div className="rows">{repositories.map((repository) => <div className="row github-row" key={repository.id}><strong>{repository.full_name}</strong><span>{repository.default_branch} · {repository.head_sha?.slice(0, 12) ?? "未读取 Commit"}</span><b className={repository.last_error ? "bad" : "good"}>{repository.last_error ? "部分失败" : "已同步"}</b></div>)}</div>}
  </section>;
}
