import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "./route";

afterEach(() => { vi.unstubAllGlobals(); delete process.env.ADMIN_API_TOKEN; });

describe("operation plan proxy", () => {
  it("keeps admin authority server-side and forwards only to the control plane", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: "operation-1", status: "awaiting_confirmation" }), { status: 201 }));
    vi.stubGlobal("fetch", internalFetch);
    const request = new NextRequest("https://ops.example.com/console/operations", { method: "POST", headers: { host: "ops.example.com", origin: "https://ops.example.com", "content-type": "application/json" }, body: JSON.stringify({ event_id: "event-1", action_type: "docker_restart" }) });
    const response = await POST(request);
    expect(response.status).toBe(201);
    expect(internalFetch).toHaveBeenCalledWith("http://localhost:8000/api/v1/operations", expect.objectContaining({ headers: { "content-type": "application/json", "x-admin-token": "server-secret" } }));
  });

  it("rejects cross-origin requests", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn();
    vi.stubGlobal("fetch", internalFetch);
    const request = new NextRequest("https://ops.example.com/console/operations", { method: "POST", headers: { host: "ops.example.com", origin: "https://evil.example", "content-type": "application/json" }, body: "{}" });
    expect((await POST(request)).status).toBe(403);
    expect(internalFetch).not.toHaveBeenCalled();
  });
});
