import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.ADMIN_API_TOKEN;
});

describe("service mapping proxy", () => {
  it("keeps the admin token on the server", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ instance_id: "instance-1" }), { status: 201 }),
    );
    vi.stubGlobal("fetch", internalFetch);
    const body = {
      name: "api",
      environment: "production",
      agent_id: "agent-1",
      service_kind: "docker",
      service_key: "compose:payments:api:1",
      log_source_key: "docker-logs-1234",
    };
    const request = new NextRequest("https://ops.example.com/console/service-mappings", {
      method: "POST",
      headers: { "content-type": "application/json", host: "ops.example.com", origin: "https://ops.example.com" },
      body: JSON.stringify(body),
    });

    const response = await POST(request);

    expect(response.status).toBe(201);
    expect(internalFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/service-mappings",
      expect.objectContaining({
        headers: expect.objectContaining({ "x-admin-token": "server-secret" }),
        body: JSON.stringify(body),
      }),
    );
  });

  it("rejects cross-origin requests before calling the API", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn();
    vi.stubGlobal("fetch", internalFetch);
    const request = new NextRequest("https://ops.example.com/console/service-mappings", {
      method: "POST",
      headers: { "content-type": "application/json", host: "ops.example.com", origin: "https://evil.example" },
      body: JSON.stringify({}),
    });

    expect((await POST(request)).status).toBe(403);
    expect(internalFetch).not.toHaveBeenCalled();
  });
});
