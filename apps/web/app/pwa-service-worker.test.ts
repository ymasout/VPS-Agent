import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";
import { beforeEach, describe, expect, it, vi } from "vitest";

type WorkerEvent = { waitUntil: (promise: Promise<unknown>) => void };
type FetchEvent = WorkerEvent & { request: { method: string; mode: string; url: string }; respondWith: (promise: Promise<unknown>) => void };
type Handler = (event: WorkerEvent & Partial<FetchEvent>) => void;

describe("PWA service worker runtime policy", () => {
  const source = readServiceWorker();
  const handlers: Record<string, Handler> = {};
  const addAll = vi.fn(async (requests: Request[]) => { void requests; });
  const match = vi.fn(async (request: Request | string) => { void request; return undefined as unknown; });
  const cache = { addAll, match };
  const caches = {
    open: vi.fn(async (name: string) => { void name; return cache; }),
    keys: vi.fn(async () => ["vps-agent-static-old", "unrelated-cache"]),
    delete: vi.fn(async (name: string) => { void name; return true; }),
    match,
  };
  const fetchRequest = vi.fn(async (request: unknown) => { void request; return new Response("online"); });
  const worker = {
    location: { origin: "https://ops.example.com" },
    clients: { claim: vi.fn() },
    skipWaiting: vi.fn(),
    addEventListener: (type: string, handler: Handler) => { handlers[type] = handler; },
  };

  beforeEach(() => {
    vi.clearAllMocks();
    for (const key of Object.keys(handlers)) delete handlers[key];
    runInNewContext(source, { self: worker, caches, fetch: fetchRequest, URL, Request, Response, Promise });
  });

  it("installs exactly three authenticated same-origin static requests", async () => {
    let completion: Promise<unknown> = Promise.resolve();
    handlers.install({ waitUntil: (promise) => { completion = promise; } });
    await completion;
    const requests = addAll.mock.calls[0][0];
    expect(requests.map((request) => new URL(request.url).pathname)).toEqual(["/offline.html", "/pwa-icon.svg", "/manifest.webmanifest"]);
    expect(requests.every((request) => request.credentials === "same-origin" && request.cache === "reload")).toBe(true);
  });

  it("does not intercept API traffic or any write request", () => {
    const respondWith = vi.fn();
    const waitUntil = vi.fn();
    handlers.fetch({ request: { method: "GET", mode: "cors", url: "https://ops.example.com/api/v1/events" }, respondWith, waitUntil });
    handlers.fetch({ request: { method: "POST", mode: "cors", url: "https://ops.example.com/console/operations/op-1/confirm" }, respondWith, waitUntil });
    expect(respondWith).not.toHaveBeenCalled();
    expect(waitUntil).not.toHaveBeenCalled();
  });

  it("refreshes only the fixed static allowlist after a successful navigation", async () => {
    let response: Promise<unknown> = Promise.resolve();
    let background: Promise<unknown> = Promise.resolve();
    handlers.fetch({
      request: { method: "GET", mode: "navigate", url: "https://ops.example.com/mobile" },
      respondWith: (promise) => { response = promise; },
      waitUntil: (promise) => { background = promise; },
    });
    expect(await response).toBeInstanceOf(Response);
    await background;
    expect(addAll).toHaveBeenCalledOnce();
    expect(addAll.mock.calls[0][0]).toHaveLength(3);
  });

  it("returns the data-free offline page without refreshing after a failed navigation", async () => {
    const offline = new Response("offline");
    fetchRequest.mockRejectedValueOnce(new Error("offline"));
    match.mockResolvedValueOnce(offline);
    let response: Promise<unknown> = Promise.resolve();
    let background: Promise<unknown> = Promise.resolve();
    handlers.fetch({
      request: { method: "GET", mode: "navigate", url: "https://ops.example.com/mobile" },
      respondWith: (promise) => { response = promise; },
      waitUntil: (promise) => { background = promise; },
    });
    expect(await response).toBe(offline);
    await background;
    expect(addAll).not.toHaveBeenCalled();
  });
});

function readServiceWorker() {
  return readFileSync(resolve(process.cwd(), "public/sw.js"), "utf8");
}
