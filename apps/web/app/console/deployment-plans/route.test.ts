import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "./route";

afterEach(() => { vi.unstubAllGlobals(); delete process.env.ADMIN_API_TOKEN; });

describe("read-only deployment plan proxy", () => {
  it("keeps admin authority server-side", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: "plan-1", status: "planned" }), { status: 201 }));
    vi.stubGlobal("fetch", internalFetch);
    const request = new NextRequest("https://ops.example.com/console/deployment-plans", { method: "POST", headers: { host: "ops.example.com", origin: "https://ops.example.com", "content-type": "application/json" }, body: JSON.stringify({ instance_id: "instance-1", target_digest: `ghcr.io/org/app@sha256:${"a".repeat(64)}` }) });
    const response = await POST(request);
    expect(response.status).toBe(201);
    expect(internalFetch).toHaveBeenCalledWith("http://localhost:8000/api/v1/deployment-plans", expect.objectContaining({ headers: { "content-type": "application/json", "x-admin-token": "server-secret" } }));
  });

  it("rejects cross-origin requests", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn();
    vi.stubGlobal("fetch", internalFetch);
    const request = new NextRequest("https://ops.example.com/console/deployment-plans", { method: "POST", headers: { host: "ops.example.com", origin: "https://evil.example" }, body: "{}" });
    expect((await POST(request)).status).toBe(403);
    expect(internalFetch).not.toHaveBeenCalled();
  });
});
