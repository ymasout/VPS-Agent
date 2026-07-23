import type { ConversationCitation } from "@/lib/api";

export function conversationCitationLabel(citation: ConversationCitation): string {
  const parts = [citation.source_label];
  if (citation.repository) {
    if (citation.repository.deployment_commit_sha) {
      parts.push(`部署 ${citation.repository.deployment_commit_sha.slice(0, 12)}`);
    }
    parts.push(
      citation.repository.deployment_relation === "aligned"
        ? "与部署一致"
        : citation.repository.deployment_relation === "mismatch"
          ? "HEAD 与部署不一致"
          : "部署 Commit 未知",
    );
    if (citation.repository.synchronized_at) {
      parts.push(
        `同步 ${new Date(citation.repository.synchronized_at).toLocaleString("zh-CN")}`,
      );
    }
    if (citation.repository.stale) parts.push("快照较旧");
    if (citation.repository.truncated) parts.push("已截断");
    if (!citation.repository.available) parts.push("历史来源已不可用");
  }
  return parts.join(" · ");
}
