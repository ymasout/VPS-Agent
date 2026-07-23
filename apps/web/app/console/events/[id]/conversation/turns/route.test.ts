import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.ADMIN_API_TOKEN;
});

describe("event conversation route", () => {
  it("keeps the admin token server-side and forwards the bounded question", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "turn-1", status: "pending" }), { status: 202 }),
    );
    vi.stubGlobal("fetch", internalFetch);
    const request = new NextRequest(
      "https://ops.example.com/console/events/event-1/conversation/turns",
      {
        method: "POST",
        headers: {
          "content-type": "application/json",
          host: "ops.example.com",
          origin: "https://ops.example.com",
        },
        body: JSON.stringify({
          client_request_id: "6fd98744-1d93-4555-b019-e075b0453f35",
          question: "目前确认了什么？",
        }),
      },
    );

    const response = await POST(request, { params: Promise.resolve({ id: "event-1" }) });

    expect(response.status).toBe(202);
    expect(internalFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/events/event-1/conversation/turns",
      expect.objectContaining({
        headers: {
          "content-type": "application/json",
          "x-admin-token": "server-secret",
        },
      }),
    );
    expect(await response.text()).not.toContain("server-secret");
  });

  it("rejects cross-origin, malformed identifiers, and oversized bodies", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn();
    vi.stubGlobal("fetch", internalFetch);
    const crossOrigin = new NextRequest(
      "https://ops.example.com/console/events/event-1/conversation/turns",
      {
        method: "POST",
        headers: { host: "ops.example.com", origin: "https://evil.example" },
        body: "{}",
      },
    );
    expect(
      (await POST(crossOrigin, { params: Promise.resolve({ id: "event-1" }) })).status,
    ).toBe(403);

    const malformed = new NextRequest(
      "https://ops.example.com/console/events/bad/conversation/turns",
      {
        method: "POST",
        headers: { host: "ops.example.com", origin: "https://ops.example.com" },
        body: "{}",
      },
    );
    expect((await POST(malformed, { params: Promise.resolve({ id: "../bad" }) })).status).toBe(
      400,
    );

    const oversized = new NextRequest(
      "https://ops.example.com/console/events/event-1/conversation/turns",
      {
        method: "POST",
        headers: { host: "ops.example.com", origin: "https://ops.example.com" },
        body: JSON.stringify({ question: "x".repeat(13000) }),
      },
    );
    expect(
      (await POST(oversized, { params: Promise.resolve({ id: "event-1" }) })).status,
    ).toBe(413);
    expect(internalFetch).not.toHaveBeenCalled();
  });
});
