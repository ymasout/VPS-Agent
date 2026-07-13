"use client";

import { FormEvent, useState } from "react";

type CreatedToken = { token: string; expires_at: string };

function shellQuote(value: string) {
  return `'${value.replaceAll("'", `'"'"'`)}'`;
}

export function RegistrationPanel() {
  const [name, setName] = useState("");
  const [created, setCreated] = useState<CreatedToken | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState("");

  const installCommand = `curl -fsSL --proto '=https' --tlsv1.2 https://github.com/ymasout/VPS-Agent/releases/latest/download/install-agent.sh | sudo bash -s -- --url https://ops.ymast.shop --name ${shellQuote(name.trim() || "my-vps")}`;

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
      setCreated(payload as CreatedToken);
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
      </form>
      {error && <div className="registration-error">{error}</div>}
      {created && (
        <div className="token-result">
          <div><span>一次性注册令牌</span><small>有效期至 {new Date(created.expires_at).toLocaleString("zh-CN")}</small></div>
          <code>{created.token}</code>
          <button type="button" onClick={() => copy(created.token, "token")}>{copied === "token" ? "已复制" : "复制令牌"}</button>
          <p>在目标 VPS 执行下面的命令，出现 Registration token 提示后粘贴令牌：</p>
          <pre>{installCommand}</pre>
          <button type="button" onClick={() => copy(installCommand, "command")}>{copied === "command" ? "已复制" : "复制安装命令"}</button>
        </div>
      )}
    </section>
  );
}
