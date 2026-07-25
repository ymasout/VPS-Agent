import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST as postAgent } from "./agents/[id]/conversation/turns/route";
import { POST as postService } from "./service-instances/[id]/conversation/turns/route";

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.ADMIN_API_TOKEN;
});

describe("context conversation proxies", () => {
  it.each([
    [
      "agent",
      postAgent,
      "agents",
      "agent-1",
    ],
    [
      "service",
      postService,
      "service-instances",
      "instance-1",
    ],
  ])(
    "keeps the admin token server-side for %s scope",
    async (_label, handler, resource, id) => {
      process.env.ADMIN_API_TOKEN = "server-secret";
      const internalFetch = vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ id: "turn-1", status: "pending" }), {
          status: 202,
        }),
      );
      vi.stubGlobal("fetch", internalFetch);
      const request = new NextRequest(
        `https://ops.example.com/console/${resource}/${id}/conversation/turns`,
        {
          method: "POST",
          headers: {
            host: "ops.example.com",
            origin: "https://ops.example.com",
            "content-type": "application/json",
          },
          body: JSON.stringify({
            client_request_id: "6fd98744-1d93-4555-b019-e075b0453f35",
            question: "当前状态？",
          }),
        },
      );

      const response = await handler(request, {
        params: Promise.resolve({ id }),
      });

      expect(response.status).toBe(202);
      expect(internalFetch).toHaveBeenCalledWith(
        `http://localhost:8000/api/v1/${resource}/${id}/conversation/turns`,
        expect.objectContaining({
          headers: {
            "content-type": "application/json",
            "x-admin-token": "server-secret",
          },
        }),
      );
      expect(await response.text()).not.toContain("server-secret");
    },
  );

  it.each([
    ["agent", postAgent, "agents"],
    ["service", postService, "service-instances"],
  ])("rejects cross-origin %s requests", async (_label, handler, resource) => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn();
    vi.stubGlobal("fetch", internalFetch);
    const request = new NextRequest(
      `https://ops.example.com/console/${resource}/target-1/conversation/turns`,
      {
        method: "POST",
        headers: {
          host: "ops.example.com",
          origin: "https://evil.example",
        },
        body: "{}",
      },
    );

    const response = await handler(request, {
      params: Promise.resolve({ id: "target-1" }),
    });

    expect(response.status).toBe(403);
    expect(internalFetch).not.toHaveBeenCalled();
  });
});
