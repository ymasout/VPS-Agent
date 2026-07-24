import Link from "next/link";
import {
  getGitHubRepositories,
  getGitHubStatus,
  type GitHubRepository,
} from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function RepositoriesPage() {
  let repositories: GitHubRepository[] = [];
  let unavailable = false;
  let enabled = false;
  try {
    const [status, authorized] = await Promise.all([
      getGitHubStatus(),
      getGitHubRepositories(),
    ]);
    enabled = status.repository_chat_enabled;
    repositories = enabled ? authorized : [];
  } catch {
    unavailable = true;
  }

  return (
    <main>
      <Link className="back" href="/">
        ← 总览
      </Link>
      <section className="hero compact detail-head">
        <span className="eyebrow">M5.2.2 · SINGLE REPOSITORY</span>
        <h1>仓库会话</h1>
        <p>
          请选择一个当前授权仓库。每次会话只绑定一个仓库，不会跨仓库检索或混合
          Commit。
        </p>
      </section>

      {unavailable && (
        <div className="empty error">
          <strong>控制平面暂时不可用</strong>
          <span>无法确认授权仓库列表，请稍后刷新。</span>
        </div>
      )}
      {!unavailable && !enabled && (
        <div className="empty">
          <strong>仓库会话功能未启用</strong>
          <span>当前只保留既有 M5.1 行为；启用必须通过独立服务端开关。</span>
        </div>
      )}
      {!unavailable && enabled && repositories.length === 0 && (
        <div className="empty">
          <strong>没有已授权仓库</strong>
          <span>请先在总览页配置并同步 GitHub App。</span>
        </div>
      )}
      {repositories.length > 0 && (
        <section className="section">
          <div className="section-title">
            <h2>选择单一仓库</h2>
            <span>{repositories.length} repositories</span>
          </div>
          <div className="rows">
            {repositories.map((repository) => (
              <Link
                className="row github-row"
                href={`/repositories/${repository.id}`}
                key={repository.id}
              >
                <strong>{repository.full_name}</strong>
                <span>
                  {repository.default_branch} ·{" "}
                  {repository.head_sha?.slice(0, 12) ?? "无当前 Commit"}
                </span>
                <b className={repository.last_error ? "bad" : "good"}>
                  {repository.last_error ? "不可用" : "进入会话"}
                </b>
              </Link>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
