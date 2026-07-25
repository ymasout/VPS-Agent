import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type {
  ConversationOperationCandidate,
  ConversationOperationTimeline,
  EventConversation,
} from "@/lib/api";
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

const operationTimeline: ConversationOperationTimeline = {
  event_id: "event-1",
  available: true,
  unavailable_reason: null,
  operations: [
    {
      id: "operation-1",
      source_conversation_turn_id: "turn-1",
      action_type: "docker_compose_deploy",
      status: "succeeded",
      impact_summary: "恢复失败部署",
      verification_status: "passed",
      error_code: null,
      error_summary: null,
      requested_at: "2026-07-25T00:00:02Z",
      completed_at: "2026-07-25T00:01:02Z",
      transitions: [
        {
          from_status: "verifying",
          to_status: "succeeded",
          actor_type: "control_plane",
          created_at: "2026-07-25T00:01:02Z",
        },
      ],
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

  it("renders a read-only operation timeline and trusted deployment navigation", () => {
    const markup = renderToStaticMarkup(
      <EventConversationPanel
        deploymentHref="/servers/agent-1?service=compose%3Ademo%3Aapi%3A1#deployment-plans"
        initial={conversation}
        operationTimeline={operationTimeline}
      />,
    );

    expect(markup).toContain("相关操作");
    expect(markup).toContain("健康验证通过");
    expect(markup).toContain("verifying");
    expect(markup).toContain("/operations/operation-1");
    expect(markup).toContain(
      "/servers/agent-1?service=compose%3Ademo%3Aapi%3A1#deployment-plans",
    );
    expect(markup).not.toContain("确认并签发");
    expect(markup).not.toContain("target_digest");
  });

  it("distinguishes a disabled operation timeline from an empty history", () => {
    const markup = renderToStaticMarkup(
      <EventConversationPanel
        initial={conversation}
        operationTimeline={{
          event_id: "event-1",
          available: false,
          unavailable_reason: "feature_disabled",
          operations: [],
        }}
      />,
    );

    expect(markup).toContain("操作时间线尚未启用");
    expect(markup).not.toContain("当前事件没有关联操作");
  });
});
