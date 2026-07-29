import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST as postDingTalk } from "./dingtalk/route";
import { POST as postTelegram } from "./telegram/route";
import { GET } from "./[id]/route";

const id = "11111111-1111-4111-8111-111111111111";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("notification test proxy", () => {
  it("forwards an empty same-origin POST with server authority and idempotency", async () => {
    vi.stubEnv("ADMIN_API_TOKEN", "managed-secret");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id, status: "pending" }), { status: 202 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const request = new NextRequest("https://ops.example.com/console/notification-tests/dingtalk", {
      method: "POST",
      headers: { host: "ops.example.com", origin: "https://ops.example.com", "idempotency-key": id },
    });

    const response = await postDingTalk(request);

    expect(response.status).toBe(202);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/notification-tests/dingtalk",
      {
        method: "POST",
        headers: { "idempotency-key": id, "x-admin-token": "managed-secret" },
        cache: "no-store",
      },
    );
  });

  it("rejects cross-origin, malformed idempotency, and request bodies", async () => {
    const crossOrigin = await postDingTalk(new NextRequest("https://ops.example.com/console/notification-tests/dingtalk", {
      method: "POST",
      headers: { host: "ops.example.com", origin: "https://evil.example", "idempotency-key": id },
    }));
    const malformed = await postDingTalk(new NextRequest("https://ops.example.com/console/notification-tests/dingtalk", {
      method: "POST",
      headers: { host: "ops.example.com", origin: "https://ops.example.com", "idempotency-key": "bad" },
    }));
    const body = await postDingTalk(new NextRequest("https://ops.example.com/console/notification-tests/dingtalk", {
      method: "POST",
      headers: { host: "ops.example.com", origin: "https://ops.example.com", "idempotency-key": id, "content-length": "2" },
      body: "{}",
    }));

    expect(crossOrigin.status).toBe(403);
    expect(malformed.status).toBe(422);
    expect(body.status).toBe(422);
  });

  it("forwards Telegram only to the fixed managed API route", async () => {
    vi.stubEnv("ADMIN_API_TOKEN", "managed-secret");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id, channel: "telegram", status: "pending" }), { status: 202 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const request = new NextRequest("https://ops.example.com/console/notification-tests/telegram", {
      method: "POST",
      headers: { host: "ops.example.com", origin: "https://ops.example.com", "idempotency-key": id },
    });

    const response = await postTelegram(request);

    expect(response.status).toBe(202);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/notification-tests/telegram",
      {
        method: "POST",
        headers: { "idempotency-key": id, "x-admin-token": "managed-secret" },
        cache: "no-store",
      },
    );
  });

  it("polls only a bounded UUID through the managed API", async () => {
    vi.stubEnv("ADMIN_API_TOKEN", "managed-secret");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id, status: "succeeded" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const request = new NextRequest(`https://ops.example.com/console/notification-tests/${id}`, {
      headers: { host: "ops.example.com", origin: "https://ops.example.com" },
    });

    const response = await GET(request, { params: Promise.resolve({ id }) });

    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledWith(
      `http://localhost:8000/api/v1/notification-tests/${id}`,
      { headers: { "x-admin-token": "managed-secret" }, cache: "no-store" },
    );
  });
});
