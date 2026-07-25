import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.ADMIN_API_TOKEN;
});

const requestId = "afda9707-3eac-4a25-bf7f-06b0a934dc4a";

function request(body: unknown, origin = "https://ops.example.com") {
  return new NextRequest(
    "https://ops.example.com/console/events/event-1/conversation/turns/turn-1/rollback-plan",
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        host: "ops.example.com",
        origin,
      },
      body: JSON.stringify(body),
    },
  );
}

describe("conversation rollback plan proxy", () => {
  it("keeps the admin token server-side and forwards only the strict plan request", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "operation-1",
          rollback_of: "failed-deploy-1",
          status: "awaiting_confirmation",
        }),
        { status: 201 },
      ),
    );
    vi.stubGlobal("fetch", internalFetch);

    const response = await POST(
      request({ client_request_id: requestId, expires_in_seconds: 300 }),
      { params: Promise.resolve({ id: "event-1", turnId: "turn-1" }) },
    );

    expect(response.status).toBe(201);
    expect(internalFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/events/event-1/conversation/turns/turn-1/rollback-plan",
      expect.objectContaining({
        headers: {
          "content-type": "application/json",
          "x-admin-token": "server-secret",
        },
      }),
    );
    expect(await response.text()).not.toContain("server-secret");
  });

  it("rejects cross-origin and caller-selected rollback fields", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn();
    vi.stubGlobal("fetch", internalFetch);

    expect(
      (
        await POST(
          request({ client_request_id: requestId, expires_in_seconds: 300 }, "https://evil.example"),
          { params: Promise.resolve({ id: "event-1", turnId: "turn-1" }) },
        )
      ).status,
    ).toBe(403);
    expect(
      (
        await POST(
          request({
            client_request_id: requestId,
            expires_in_seconds: 300,
            rollback_of: "attacker-selected",
            target_digest: "attacker-selected",
          }),
          { params: Promise.resolve({ id: "event-1", turnId: "turn-1" }) },
        )
      ).status,
    ).toBe(422);
    expect(internalFetch).not.toHaveBeenCalled();
  });

  it("returns a controlled 502 when the control plane is unavailable", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));

    const response = await POST(
      request({ client_request_id: requestId, expires_in_seconds: 300 }),
      { params: Promise.resolve({ id: "event-1", turnId: "turn-1" }) },
    );

    expect(response.status).toBe(502);
    expect(response.headers.get("cache-control")).toBe("no-store");
  });
});
