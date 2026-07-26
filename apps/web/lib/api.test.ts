import { afterEach, describe, expect, it, vi } from "vitest";
import { ControlPlaneApiError, formatBytes, getAgent, getAgents, getSystemInfo } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("control plane API client", () => {
  it("requests Fleet data without using a stale cache", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("[]", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await getAgents();

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/agents",
      { cache: "no-store" },
    );
  });

  it("rejects non-success responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("missing", { status: 404 })));

    const request = getAgent("missing-agent");
    await expect(request).rejects.toThrow("API returned 404");
    await expect(request).rejects.toBeInstanceOf(ControlPlaneApiError);
    await expect(request).rejects.toMatchObject({ status: 404 });
  });

  it("keeps the managed system token in the server-side request header", async () => {
    vi.stubEnv("ADMIN_API_TOKEN", "managed-secret");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response('{"schema_current":true}', { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getSystemInfo();

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/system-info",
      {
        cache: "no-store",
        headers: { "X-Admin-Token": "managed-secret" },
      },
    );
  });

  it("fails closed when the managed system token is absent", async () => {
    vi.stubEnv("ADMIN_API_TOKEN", "");
    await expect(getSystemInfo()).rejects.toThrow("ADMIN_API_TOKEN is required");
  });
});

describe("byte formatting", () => {
  it("uses a readable unit for each scale", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(2 * 1024 ** 3)).toBe("2.0 GB");
  });

  it("does not expose invalid numeric values", () => {
    expect(formatBytes(Number.NaN)).toBe("0 B");
    expect(formatBytes(-1)).toBe("0 B");
  });
});
