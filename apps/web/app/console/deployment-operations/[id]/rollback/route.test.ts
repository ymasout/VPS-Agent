import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "./route";

afterEach(() => { vi.unstubAllGlobals(); delete process.env.ADMIN_API_TOKEN; });

describe("deployment rollback proxy", () => {
  it("creates only a server-authorized rollback of the selected failed deployment", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: "rollback-1", rollback_of: "operation-1", status: "awaiting_confirmation" }), { status: 201 }));
    vi.stubGlobal("fetch", internalFetch);
    const request = new NextRequest("https://ops.example.com/console/deployment-operations/operation-1/rollback", { method: "POST", headers: { host: "ops.example.com", origin: "https://ops.example.com" } });
    const response = await POST(request, { params: Promise.resolve({ id: "operation-1" }) });
    expect(response.status).toBe(201);
    expect(internalFetch).toHaveBeenCalledWith("http://localhost:8000/api/v1/deployment-operations/operation-1/rollback", expect.objectContaining({ body: JSON.stringify({ expires_in_seconds: 300 }), headers: { "content-type": "application/json", "x-admin-token": "server-secret" } }));
  });

  it("rejects cross-origin requests before contacting the API", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn();
    vi.stubGlobal("fetch", internalFetch);
    const request = new NextRequest("https://ops.example.com/console/deployment-operations/operation-1/rollback", { method: "POST", headers: { host: "ops.example.com", origin: "https://evil.example" } });
    expect((await POST(request, { params: Promise.resolve({ id: "operation-1" }) })).status).toBe(403);
    expect(internalFetch).not.toHaveBeenCalled();
  });
});
