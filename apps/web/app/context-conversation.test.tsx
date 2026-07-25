import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { ContextConversation } from "@/lib/api";
import { ContextConversationPanel } from "./context-conversation";

vi.mock("@/app/conversation-turn-result", () => ({
  ConversationTurnResult: () => <div>bounded answer</div>,
}));

function conversation(scope: "agent" | "service"): ContextConversation {
  return {
    scope_type: scope,
    target_id: `${scope}-1`,
    parent_agent_id: "agent-1",
    title: scope,
    session_id: null,
    available: true,
    unavailable_reason: null,
    turns: [],
  };
}

describe("context conversation", () => {
  it("renders separate read-only Agent and service scopes", () => {
    const agent = renderToStaticMarkup(
      <ContextConversationPanel
        endpoint="/console/agents/agent-1/conversation/turns"
        initial={conversation("agent")}
      />,
    );
    const service = renderToStaticMarkup(
      <ContextConversationPanel
        endpoint="/console/service-instances/instance-1/conversation/turns"
        initial={conversation("service")}
      />,
    );

    expect(agent).toContain("Agent会话");
    expect(agent).toContain("不访问 VPS");
    expect(service).toContain("服务会话");
    expect(service).toContain("不会创建或确认 Operation");
    expect(agent).not.toContain("Fleet");
    expect(service).not.toContain("执行操作");
  });

  it("disables new questions when the independent flag is off", () => {
    const initial = {
      ...conversation("agent"),
      available: false,
      unavailable_reason: "feature_disabled",
    };
    const markup = renderToStaticMarkup(
      <ContextConversationPanel
        endpoint="/console/agents/agent-1/conversation/turns"
        initial={initial}
      />,
    );

    expect(markup).toContain("feature_disabled");
    expect(markup).toContain("disabled");
  });
});
