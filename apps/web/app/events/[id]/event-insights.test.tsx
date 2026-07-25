import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { ConversationTurn } from "@/lib/api";
import { EventInsights } from "./event-insights";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

const turn: ConversationTurn = {
  id: "turn-1",
  session_id: "session-1",
  client_request_id: "6fd98744-1d93-4555-b019-e075b0453f35",
  question: "what happened",
  status: "completed",
  provider: "deterministic",
  answer: {
    summary: "bounded",
    facts: [],
    inferences: [],
    recommendations: [
      {
        action: "review the service",
        risk: "low",
        requires_confirmation: true,
        citation_ids: ["ctx_1"],
      },
    ],
    missing_evidence: [],
  },
  citations: [],
  context_manifest: {},
  error_code: null,
  error_detail: null,
  created_at: "2026-07-26T00:00:00Z",
  started_at: "2026-07-26T00:00:00Z",
  completed_at: "2026-07-26T00:00:01Z",
};

describe("EventInsights", () => {
  it("labels feedback as non-authoritative and Runbook as non-executable", () => {
    const html = renderToStaticMarkup(
      <EventInsights
        history={{ event_id: "event-1", items: [] }}
        latestTurn={turn}
        review={null}
        similar={{ event_id: "event-1", algorithm: "m5.6-similarity-v1", items: [] }}
      />,
    );

    expect(html).toContain("反馈不会在线改变提示、权限或执行策略");
    expect(html).toContain("保存首条建议为 Runbook 草稿");
    expect(html).toContain("草稿未审核、不可执行，不会创建 Operation");
  });
});
