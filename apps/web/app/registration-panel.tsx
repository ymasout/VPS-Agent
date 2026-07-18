"use client";

import { FormEvent, useState } from "react";
import { buildInstallCommand } from "../lib/registration";

type CreatedToken = { token: string; expires_at: string; name: string };

export function RegistrationPanel() {
  const [name, setName] = useState("");
  const [created, setCreated] = useState<CreatedToken | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState("");
  const [evidencePolicy, setEvidencePolicy] = useState<"disabled" | "docker-logs">("docker-logs");

  const controlPlaneURL = typeof window === "undefined" ? "" : window.location.origin;
  const installCommand = buildInstallCommand(
    controlPlaneURL,
    created?.name ?? (name.trim() || "my-vps"),
    evidencePolicy,
  );

  async function createToken(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setCreated(null);
    setCopied("");
    try {
      const response = await fetch("/console/registration-token", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "生成失败");
      setCreated({ ...(payload as Omit<CreatedToken, "name">), name: name.trim() });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "生成失败");
    } finally {
      setLoading(false);
    }
  }

  async function copy(value: string, label: string) {
    await navigator.clipboard.writeText(value);
    setCopied(label);
  }

  return (
    <section className="registration-panel">
      <div className="registration-copy">
        <div className="eyebrow"><span /> ADD VPS</div>
        <h2>接入新机器</h2>
        <p>填写 Fleet 中显示的名称，生成仅可使用一次、30 分钟后过期的注册令牌。</p>
      </div>
      <form onSubmit={createToken}>
        <label htmlFor="agent-name">机器名称</label>
        <div className="registration-form-row">
          <input id="agent-name" value={name} onChange={(event) => setName(event.target.value)} maxLength={255} required placeholder="例如：dmit-vps" />
          <button type="submit" disabled={loading || !name.trim()}>{loading ? "生成中…" : "生成令牌"}</button>
        </div>
        <label htmlFor="evidence-policy">本地能力</label>
        <select
          id="evidence-policy"
          value={evidencePolicy}
          onChange={(event) => setEvidencePolicy(event.target.value as "disabled" | "docker-logs")}
        >
          <option value="docker-logs">监控与 Docker 只读诊断（推荐）</option>
          <option value="disabled">仅监控</option>
        </select>
        <small className="field-help">诊断模式只允许读取自动发现容器的有限日志，不开放 Shell 或任意路径。</small>
      </form>
      {error && <div className="registration-error" role="alert">{error}</div>}
      {created && (
        <div className="token-result" aria-live="polite">
          <div><span>一次性注册令牌</span><small>有效期至 {new Date(created.expires_at).toLocaleString("zh-CN")}</small></div>
          <code>{created.token}</code>
          <button type="button" onClick={() => copy(created.token, "token")}>{copied === "token" ? "已复制" : "复制令牌"}</button>
          <p>先在目标 VPS 执行安装命令；终端出现 Registration token 提示后，再复制并粘贴上方令牌。令牌不会写入命令或 Shell 历史。</p>
          <pre>{installCommand}</pre>
          <button type="button" onClick={() => copy(installCommand, "command")}>{copied === "command" ? "已复制" : "复制安装命令"}</button>
        </div>
      )}
    </section>
  );
}
