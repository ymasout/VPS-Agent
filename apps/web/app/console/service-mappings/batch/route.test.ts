import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

import { POST } from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.ADMIN_API_TOKEN;
  delete process.env.PRINCIPAL_WRITE_AUTHORIZATION_ENABLED;
});

describe("batch service mapping proxy", () => {
  it("forwards a bounded batch while keeping authority server-side", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const payload = { items: [{ client_item_id: "one", mapping: { name: "api" } }] };
    const internalFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ results: [], created_count: 0, rejected_count: 0 }), { status: 200 }),
    );
    vi.stubGlobal("fetch", internalFetch);
    const request = new NextRequest("https://ops.example.com/console/service-mappings/batch", {
      method: "POST",
      headers: { host: "ops.example.com", origin: "https://ops.example.com", "content-type": "application/json" },
      body: JSON.stringify(payload),
    });

    expect((await POST(request)).status).toBe(200);
    expect(internalFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/service-mappings/batch",
      expect.objectContaining({
        body: JSON.stringify(payload),
        headers: { "content-type": "application/json", "x-admin-token": "server-secret" },
      }),
    );
  });

  it("rejects cross-origin and oversized batches before forwarding", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn();
    vi.stubGlobal("fetch", internalFetch);
    const crossOrigin = new NextRequest("https://ops.example.com/console/service-mappings/batch", {
      method: "POST", headers: { host: "ops.example.com", origin: "https://evil.example" }, body: "{}",
    });
    expect((await POST(crossOrigin)).status).toBe(403);
    const oversized = new NextRequest("https://ops.example.com/console/service-mappings/batch", {
      method: "POST", headers: { host: "ops.example.com", origin: "https://ops.example.com" },
      body: JSON.stringify({ items: Array.from({ length: 21 }, () => ({})) }),
    });
    expect((await POST(oversized)).status).toBe(422);
    expect(internalFetch).not.toHaveBeenCalled();
  });

  it("does not let the legacy proxy bypass named authorization", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    process.env.PRINCIPAL_WRITE_AUTHORIZATION_ENABLED = "true";
    const internalFetch = vi.fn();
    vi.stubGlobal("fetch", internalFetch);
    const request = new NextRequest("https://ops.example.com/console/service-mappings/batch", {
      method: "POST", headers: { host: "ops.example.com", origin: "https://ops.example.com" }, body: "{}",
    });
    expect((await POST(request)).status).toBe(409);
    expect(internalFetch).not.toHaveBeenCalled();
  });
});
