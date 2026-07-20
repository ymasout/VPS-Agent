import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "./route";

afterEach(() => { vi.unstubAllGlobals(); delete process.env.ADMIN_API_TOKEN; });

describe("operation confirmation proxy", () => {
  it("adds the explicit local administrator identity on the server", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: "operation-1", status: "queued" }), { status: 200 }));
    vi.stubGlobal("fetch", internalFetch);
    const request = new NextRequest("https://ops.example.com/console/operations/operation-1/confirm", { method: "POST", headers: { host: "ops.example.com", origin: "https://ops.example.com" } });
    const response = await POST(request, { params: Promise.resolve({ id: "operation-1" }) });
    expect(response.status).toBe(200);
    expect(internalFetch).toHaveBeenCalledWith("http://localhost:8000/api/v1/operations/operation-1/confirm", expect.objectContaining({ body: JSON.stringify({ confirmed_by: "local-admin" }) }));
  });

  it("rejects malformed identifiers before contacting the API", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn();
    vi.stubGlobal("fetch", internalFetch);
    const request = new NextRequest("https://ops.example.com/console/operations/bad/confirm", { method: "POST", headers: { host: "ops.example.com", origin: "https://ops.example.com" } });
    expect((await POST(request, { params: Promise.resolve({ id: "../bad" }) })).status).toBe(400);
    expect(internalFetch).not.toHaveBeenCalled();
  });
});
