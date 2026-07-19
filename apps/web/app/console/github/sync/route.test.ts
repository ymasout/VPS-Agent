import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.ADMIN_API_TOKEN;
});

describe("GitHub synchronization route", () => {
  it("keeps the admin token on the server", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "completed", repository_count: 2 }), { status: 200 }),
    );
    vi.stubGlobal("fetch", internalFetch);
    const request = new NextRequest("https://ops.example.com/console/github/sync", {
      method: "POST",
      headers: { host: "ops.example.com", origin: "https://ops.example.com" },
    });

    const response = await POST(request);

    expect(response.status).toBe(200);
    expect(internalFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/github/sync",
      expect.objectContaining({ headers: { "x-admin-token": "server-secret" } }),
    );
  });

  it("rejects cross-origin requests", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn();
    vi.stubGlobal("fetch", internalFetch);
    const request = new NextRequest("https://ops.example.com/console/github/sync", {
      method: "POST",
      headers: { host: "ops.example.com", origin: "https://evil.example" },
    });

    expect((await POST(request)).status).toBe(403);
    expect(internalFetch).not.toHaveBeenCalled();
  });
});
