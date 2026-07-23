import { afterEach, describe, expect, it, vi } from "vitest";
import { GET } from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("conversation turn polling route", () => {
  it("forwards a valid turn read without caching", async () => {
    const internalFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: "turn-1", status: "completed" }), { status: 200 }),
    );
    vi.stubGlobal("fetch", internalFetch);

    const response = await GET(new Request("https://ops.example.com", {
      headers: { host: "ops.example.com", origin: "https://ops.example.com" },
    }), {
      params: Promise.resolve({ id: "turn-1" }),
    });

    expect(response.status).toBe(200);
    expect(internalFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/conversation-turns/turn-1",
      { cache: "no-store" },
    );
  });

  it("rejects malformed turn identifiers without calling the control plane", async () => {
    const internalFetch = vi.fn();
    vi.stubGlobal("fetch", internalFetch);

    const response = await GET(new Request("https://ops.example.com", {
      headers: { host: "ops.example.com", origin: "https://ops.example.com" },
    }), {
      params: Promise.resolve({ id: "../turn" }),
    });

    expect(response.status).toBe(400);
    expect(internalFetch).not.toHaveBeenCalled();
  });

  it("rejects cross-origin polling without calling the control plane", async () => {
    const internalFetch = vi.fn();
    vi.stubGlobal("fetch", internalFetch);

    const response = await GET(new Request("https://ops.example.com", {
      headers: { host: "ops.example.com", origin: "https://attacker.example" },
    }), {
      params: Promise.resolve({ id: "turn-1" }),
    });

    expect(response.status).toBe(403);
    expect(internalFetch).not.toHaveBeenCalled();
  });
});
