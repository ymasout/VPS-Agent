import Link from "next/link";
import { notFound } from "next/navigation";
import {
  ControlPlaneApiError,
  getRepositoryConversation,
  getRepositoryDetail,
  type RepositoryConversation,
  type RepositoryDetail,
} from "@/lib/api";
import { RepositoryConversationPanel } from "./repository-conversation";

export const dynamic = "force-dynamic";

export default async function RepositoryPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  let repository: RepositoryDetail | null = null;
  try {
    repository = await getRepositoryDetail(id);
  } catch (reason) {
    if (reason instanceof ControlPlaneApiError && reason.status === 404) {
      notFound();
    }
  }
  if (repository === null) {
    return (
      <main>
        <Link className="back" href="/">
          ← 总览
        </Link>
        <div className="empty error">
          <strong>控制平面暂时不可用</strong>
          <span>仓库是否存在尚未确认，请稍后刷新。</span>
        </div>
      </main>
    );
  }
  let conversation: RepositoryConversation = {
    repository_id: repository.id,
    session_id: null,
    available: repository.conversation_available,
    unavailable_reason: repository.unavailable_reason,
    turns: [],
  };
  let conversationUnavailable = false;
  try {
    conversation = await getRepositoryConversation(repository.id);
  } catch {
    conversationUnavailable = true;
  }

  return (
    <main>
      <Link className="back" href="/">
        ← 总览
      </Link>
      <section className="hero compact detail-head repository-head">
        <div className={`status ${repository.enabled ? "" : "offline"}`}>
          <span /> {repository.enabled ? "authorized snapshot" : "unavailable"}
        </div>
        <h1>{repository.full_name}</h1>
        <p>
          {repository.default_branch} ·{" "}
          {repository.head_sha?.slice(0, 12) ?? "无当前 Commit"} ·{" "}
          {repository.private ? "private" : "public"}
        </p>
      </section>

      <section className="section">
        <div className="section-title">
          <h2>当前脱敏快照</h2>
          <span>{repository.files.length} files</span>
        </div>
        <p className="section-copy">
          这里只显示已同步白名单文件的元数据，不展示正文。Commit
          是仓库快照，不是生产部署证明。
        </p>
        {repository.files.length === 0 ? (
          <div className="empty">
            <strong>当前没有可用快照文件</strong>
            <span>{repository.unavailable_reason ?? "请先检查 GitHub 同步状态。"}</span>
          </div>
        ) : (
          <div className="rows">
            {repository.files.map((file) => (
              <div className="row repository-file-row" key={file.id}>
                <strong>{file.path}</strong>
                <span>{file.content_sha256.slice(0, 12)}</span>
                <b className={file.truncated ? "warn" : "good"}>
                  {file.truncated ? "已截断" : "已脱敏"}
                </b>
              </div>
            ))}
          </div>
        )}
      </section>

      <RepositoryConversationPanel
        initial={conversation}
        unavailable={conversationUnavailable}
      />
    </main>
  );
}
