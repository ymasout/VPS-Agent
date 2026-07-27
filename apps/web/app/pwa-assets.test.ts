import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

describe("PWA static assets", () => {
  const serviceWorker = readFileSync(resolve(process.cwd(), "public/sw.js"), "utf8");
  const offlinePage = readFileSync(resolve(process.cwd(), "public/offline.html"), "utf8");
  const registration = readFileSync(resolve(process.cwd(), "app/pwa-registration.tsx"), "utf8");

  it("only precaches a fixed public allowlist", () => {
    expect(serviceWorker).toContain('const STATIC_ASSETS = ["/offline.html", "/pwa-icon.svg", "/manifest.webmanifest"]');
    expect(serviceWorker).toContain('credentials: "same-origin"');
    expect(serviceWorker).toContain('cache: "reload"');
    expect(serviceWorker).not.toContain("cache.put(");
    expect(serviceWorker).not.toContain('addEventListener("sync"');
    expect(serviceWorker).not.toContain('addEventListener("push"');
  });

  it("uses the network for navigation and falls back to a data-free page", () => {
    expect(serviceWorker).toContain('request.mode === "navigate"');
    expect(serviceWorker).toContain('networkResponse.catch(() => caches.match("/offline.html"))');
    expect(offlinePage).toContain("不会离线保存机器、事件、诊断或操作数据");
    expect(offlinePage).not.toContain("ADMIN_API_TOKEN");
  });

  it("registers whether hydration happens before or after window load", () => {
    expect(registration).toContain('document.readyState === "complete"');
    expect(registration).toContain('window.addEventListener("load", register');
  });
});
