import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST as postFleet } from "./fleet/conversation/turns/route";
import { PUT as putFeedback } from "./conversation-turns/[id]/feedback/route";
import { POST as postDraft } from "./conversation-turns/[id]/runbook-drafts/route";

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.ADMIN_API_TOKEN;
});

describe("M5 completion proxies", () => {
  it("keeps the admin token server-side for Fleet turns", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "turn-1", status: "pending" }), { status: 202 }),
    );
    vi.stubGlobal("fetch", internalFetch);
    const request = new NextRequest(
      "https://ops.example.com/console/fleet/conversation/turns",
      {
        method: "POST",
        headers: { host: "ops.example.com", origin: "https://ops.example.com" },
        body: JSON.stringify({
          client_request_id: "6fd98744-1d93-4555-b019-e075b0453f35",
          question: "当前 Fleet 状态？",
        }),
      },
    );

    const response = await postFleet(request);

    expect(response.status).toBe(202);
    expect(internalFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/fleet/conversation/turns",
      expect.objectContaining({
        headers: {
          "content-type": "application/json",
          "x-admin-token": "server-secret",
        },
      }),
    );
    expect(await response.text()).not.toContain("server-secret");
  });

  it.each([
    ["feedback", putFeedback, "PUT"],
    ["runbook-drafts", postDraft, "POST"],
  ])("rejects cross-origin %s requests", async (suffix, handler, method) => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn();
    vi.stubGlobal("fetch", internalFetch);
    const request = new NextRequest(
      `https://ops.example.com/console/conversation-turns/turn-1/${suffix}`,
      {
        method,
        headers: { host: "ops.example.com", origin: "https://evil.example" },
        body: "{}",
      },
    );

    const response = await handler(request, {
      params: Promise.resolve({ id: "turn-1" }),
    });

    expect(response.status).toBe(403);
    expect(internalFetch).not.toHaveBeenCalled();
  });
});
