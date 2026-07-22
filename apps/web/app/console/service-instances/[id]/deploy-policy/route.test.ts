import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "./route";

afterEach(() => { vi.unstubAllGlobals(); delete process.env.ADMIN_API_TOKEN; });

describe("deployment policy proxy", () => {
  it("forwards a bounded same-origin policy update with server authority", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ instance_id: "instance-1", deploy_enabled: true, criticality: "non_critical" }), { status: 200 }));
    vi.stubGlobal("fetch", internalFetch);
    const request = new NextRequest("https://ops.example.com/console/service-instances/instance-1/deploy-policy", { method: "POST", headers: { host: "ops.example.com", origin: "https://ops.example.com", "content-type": "application/json" }, body: JSON.stringify({ enabled: true, criticality: "non_critical" }) });
    const response = await POST(request, { params: Promise.resolve({ id: "instance-1" }) });
    expect(response.status).toBe(200);
    expect(internalFetch).toHaveBeenCalledWith("http://localhost:8000/api/v1/service-instances/instance-1/deploy-policy", expect.objectContaining({ headers: { "content-type": "application/json", "x-admin-token": "server-secret" } }));
  });

  it("rejects cross-origin requests before forwarding", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn();
    vi.stubGlobal("fetch", internalFetch);
    const request = new NextRequest("https://ops.example.com/console/service-instances/instance-1/deploy-policy", { method: "POST", headers: { host: "ops.example.com", origin: "https://evil.example" }, body: "{}" });
    expect((await POST(request, { params: Promise.resolve({ id: "instance-1" }) })).status).toBe(403);
    expect(internalFetch).not.toHaveBeenCalled();
  });
});
