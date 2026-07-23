import { describe, expect, it } from "vitest";
import type { ConversationCitation } from "./api";
import { conversationCitationLabel } from "./conversation";

function repositoryCitation(
  overrides: Partial<NonNullable<ConversationCitation["repository"]>> = {},
): ConversationCitation {
  return {
    id: "ctx_repository",
    source_type: "repository_file",
    source_id: "file-1",
    source_label: "GitHub owner/repo · compose.yaml @ abc1234",
    source_collected_at: "2026-07-24T00:00:00Z",
    href: "https://github.com/owner/repo/blob/abc1234/compose.yaml",
    repository: {
      full_name: "owner/repo",
      path: "compose.yaml",
      commit_sha: "abc1234",
      deployment_commit_sha: "abc1234",
      deployment_relation: "aligned",
      synchronized_at: "2026-07-24T00:00:00Z",
      truncated: false,
      stale: false,
      available: true,
      ...overrides,
    },
  };
}

describe("conversation repository citations", () => {
  it("shows commit alignment", () => {
    expect(conversationCitationLabel(repositoryCitation())).toContain("与部署一致");
    expect(conversationCitationLabel(repositoryCitation())).toContain("部署 abc1234");
    expect(conversationCitationLabel(repositoryCitation())).toContain("同步");
    expect(
      conversationCitationLabel(
        repositoryCitation({ deployment_relation: "mismatch" }),
      ),
    ).toContain("HEAD 与部署不一致");
  });

  it("shows an unavailable tombstone without implying content is readable", () => {
    const citation = repositoryCitation({
      available: false,
      stale: true,
      truncated: true,
    });
    citation.source_id = null;
    citation.href = null;

    expect(conversationCitationLabel(citation)).toContain("历史来源已不可用");
    expect(conversationCitationLabel(citation)).toContain("快照较旧");
    expect(conversationCitationLabel(citation)).toContain("已截断");
  });
});
