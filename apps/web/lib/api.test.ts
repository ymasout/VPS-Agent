import { afterEach, describe, expect, it, vi } from "vitest";
import { formatBytes, getAgent, getAgents } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
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

    await expect(getAgent("missing-agent")).rejects.toThrow("API returned 404");
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
