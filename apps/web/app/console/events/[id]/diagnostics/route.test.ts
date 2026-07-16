import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.ADMIN_API_TOKEN;
});

describe("diagnostic trigger route", () => {
  it("keeps the admin token on the server", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "diagnostic-1", status: "pending" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", internalFetch);
    const request = new NextRequest("https://ops.example.com/console/events/event-1/diagnostics", {
      method: "POST",
      headers: { host: "ops.example.com", origin: "https://ops.example.com" },
    });

    const response = await POST(request, { params: Promise.resolve({ id: "event-1" }) });

    expect(response.status).toBe(200);
    expect(internalFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/events/event-1/diagnostics",
      expect.objectContaining({ headers: { "x-admin-token": "server-secret" } }),
    );
  });

  it("rejects cross-origin and malformed event identifiers", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn();
    vi.stubGlobal("fetch", internalFetch);
    const crossOrigin = new NextRequest("https://ops.example.com/console/events/event-1/diagnostics", {
      method: "POST",
      headers: { host: "ops.example.com", origin: "https://evil.example" },
    });
    expect((await POST(crossOrigin, { params: Promise.resolve({ id: "event-1" }) })).status).toBe(403);

    const malformed = new NextRequest("https://ops.example.com/console/events/bad/diagnostics", {
      method: "POST",
      headers: { host: "ops.example.com", origin: "https://ops.example.com" },
    });
    expect((await POST(malformed, { params: Promise.resolve({ id: "../bad" }) })).status).toBe(400);
    expect(internalFetch).not.toHaveBeenCalled();
  });
});
