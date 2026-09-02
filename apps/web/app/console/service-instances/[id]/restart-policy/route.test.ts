import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

import { POST } from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.ADMIN_API_TOKEN;
  delete process.env.PRINCIPAL_WRITE_AUTHORIZATION_ENABLED;
});

describe("restart policy proxy", () => {
  it("keeps the legacy admin token server-side", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", internalFetch);
    const request = new NextRequest("https://ops.example.com/console/service-instances/instance-1/restart-policy", {
      method: "POST",
      headers: { host: "ops.example.com", origin: "https://ops.example.com", "content-type": "application/json" },
      body: JSON.stringify({ enabled: true, criticality: "non_critical" }),
    });
    expect((await POST(request, { params: Promise.resolve({ id: "instance-1" }) })).status).toBe(200);
    expect(internalFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/service-instances/instance-1/restart-policy",
      expect.objectContaining({ headers: { "content-type": "application/json", "x-admin-token": "server-secret" } }),
    );
  });

  it("does not let the legacy proxy bypass named authorization", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    process.env.PRINCIPAL_WRITE_AUTHORIZATION_ENABLED = "true";
    const internalFetch = vi.fn();
    vi.stubGlobal("fetch", internalFetch);
    const request = new NextRequest("https://ops.example.com/console/service-instances/instance-1/restart-policy", {
      method: "POST", headers: { host: "ops.example.com", origin: "https://ops.example.com" }, body: "{}",
    });
    expect((await POST(request, { params: Promise.resolve({ id: "instance-1" }) })).status).toBe(409);
    expect(internalFetch).not.toHaveBeenCalled();
  });
});
