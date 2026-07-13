import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env.ADMIN_API_TOKEN;
});

describe("registration token route", () => {
  it("creates a token through the internal API", async () => {
    process.env.ADMIN_API_TOKEN = "server-secret";
    const internalFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ token: "reg_example", expires_at: "2026-07-14T00:30:00Z" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", internalFetch);
    const request = new NextRequest("https://ops.example.com/console/registration-token", {
      method: "POST",
      headers: { "content-type": "application/json", host: "ops.example.com", origin: "https://ops.example.com" },
      body: JSON.stringify({ name: "dmit-vps" }),
    });

    const response = await POST(request);

    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({ token: "reg_example" });
    expect(internalFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/registration-tokens",
      expect.objectContaining({ headers: expect.objectContaining({ "x-admin-token": "server-secret" }) }),
    );
  });

  it("rejects a cross-origin request before calling the API", async () => {
    const internalFetch = vi.fn();
    vi.stubGlobal("fetch", internalFetch);
    const request = new NextRequest("https://ops.example.com/console/registration-token", {
      method: "POST",
      headers: { "content-type": "application/json", host: "ops.example.com", origin: "https://evil.example" },
      body: JSON.stringify({ name: "dmit-vps" }),
    });

    expect((await POST(request)).status).toBe(403);
    expect(internalFetch).not.toHaveBeenCalled();
  });
});
