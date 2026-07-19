"use client";

import { FormEvent, useState } from "react";
import { GitHubRepository, ServiceMappingCandidate } from "@/lib/api";

function MappingForm({ candidate, repositories }: { candidate: ServiceMappingCandidate; repositories: GitHubRepository[] }) {
  const [mapped, setMapped] = useState(candidate.mapped);
  const [directory, setDirectory] = useState("");
  const [repository, setRepository] = useState("");
  const [environment, setEnvironment] = useState("production");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/console/service-mappings", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name: candidate.service_name,
          environment,
          agent_id: candidate.agent_id,
          service_kind: candidate.service_kind,
          service_key: candidate.service_key,
          deployment_directory: directory.trim() || null,
          log_source_key: candidate.log_source_key,
          repository_full_name: repository.trim() || null,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "映射失败");
      setMapped(true);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "映射失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <form className="mapping-card" onSubmit={submit}>
      <header>
        <div><strong>{candidate.service_name}</strong><span>{candidate.state}</span></div>
        <small>{candidate.log_source_name}</small>
      </header>
      <div className="mapping-fields">
        <label>环境<select value={environment} onChange={(event) => setEnvironment(event.target.value)}><option value="production">production</option><option value="staging">staging</option><option value="development">development</option></select></label>
        <label>部署目录（可选）<input value={directory} onChange={(event) => setDirectory(event.target.value)} placeholder="/opt/apps/service" /></label>
        <label>GitHub App 仓库（可选）<input list="authorized-github-repositories" value={repository} onChange={(event) => setRepository(event.target.value)} placeholder={repositories.length ? "选择已授权仓库" : "owner/repository"} /></label>
      </div>
      {error && <p className="mapping-error" role="alert">{error}</p>}
      <button type="submit" disabled={loading || mapped}>{mapped ? "已建立诊断映射" : loading ? "保存中…" : "确认用于诊断"}</button>
    </form>
  );
}

export function ServiceMappingPanel({ candidates, repositories }: { candidates: ServiceMappingCandidate[]; repositories: GitHubRepository[] }) {
  if (candidates.length === 0) return null;
  return (
    <section className="section">
      <div className="section-title"><h2>诊断服务发现</h2><span>{candidates.length} candidates</span></div>
      <p className="section-copy">Agent 已在本机授权这些 Docker/systemd 日志能力。确认业务信息后即可从事件发起诊断，无需填写容器 ID、Unit 参数、source_key 或 JSON。</p>
      <datalist id="authorized-github-repositories">{repositories.map((repository) => <option value={repository.full_name} key={repository.id} />)}</datalist>
      <div className="mapping-list">{candidates.map((candidate) => <MappingForm candidate={candidate} repositories={repositories} key={`${candidate.service_key}-${candidate.log_source_key}`} />)}</div>
    </section>
  );
}
