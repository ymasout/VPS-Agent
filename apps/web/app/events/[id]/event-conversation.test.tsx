import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { ConversationOperationCandidate, EventConversation } from "@/lib/api";
import { EventConversationPanel } from "./event-conversation";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("@/app/conversation-turn-result", () => ({
  ConversationTurnResult: () => <div>bounded answer</div>,
}));

const conversation: EventConversation = {
  event_id: "event-1",
  session_id: "session-1",
  turns: [
    {
      id: "turn-1",
      session_id: "session-1",
      client_request_id: "6fd98744-1d93-4555-b019-e075b0453f35",
      question: "What is confirmed?",
      status: "completed",
      provider: "deterministic",
      answer: {
        summary: "Bounded answer",
        facts: [],
        inferences: [],
        recommendations: [],
        missing_evidence: [],
      },
      citations: [],
      context_manifest: {},
      error_code: null,
      error_detail: null,
      created_at: "2026-07-25T00:00:00Z",
      started_at: "2026-07-25T00:00:00Z",
      completed_at: "2026-07-25T00:00:01Z",
    },
  ],
};

function candidate(
  actionType: ConversationOperationCandidate["action_type"],
  available: boolean,
): ConversationOperationCandidate {
  return {
    action_type: actionType,
    available,
    reason_code: available ? null : "unavailable",
    impact_summary: "bounded plan",
    requires_plan_creation: true,
    requires_confirmation: true,
  };
}

describe("event conversation operation handoff", () => {
  it("shows rollback independently and explains server-side target derivation", () => {
    const markup = renderToStaticMarkup(
      <EventConversationPanel
        initial={conversation}
        operationCandidates={[
          candidate("docker_restart", false),
          candidate("docker_compose_rollback", true),
        ]}
      />,
    );

    expect(markup).toContain("准备回滚计划");
    expect(markup).toContain("由服务端从当前事件关联的失败部署记录派生");
    expect(markup).not.toContain("准备安全重启计划");
    expect(markup).not.toContain("rollback_of");
  });

  it("shows no write action when every server candidate is unavailable", () => {
    const markup = renderToStaticMarkup(
      <EventConversationPanel
        initial={conversation}
        operationCandidates={[
          candidate("docker_restart", false),
          candidate("docker_compose_rollback", false),
        ]}
      />,
    );

    expect(markup).not.toContain("准备回滚计划");
    expect(markup).not.toContain("准备安全重启计划");
  });
});
