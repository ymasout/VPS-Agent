const CACHE_NAME = "vps-agent-static-v1";
const STATIC_ASSETS = ["/offline.html", "/pwa-icon.svg", "/manifest.webmanifest"];

function staticRequests() {
  return STATIC_ASSETS.map((path) => new Request(new URL(path, self.location.origin), {
    credentials: "same-origin",
    cache: "reload",
  }));
}

async function refreshStaticAssets() {
  const cache = await caches.open(CACHE_NAME);
  await cache.addAll(staticRequests());
}

self.addEventListener("install", (event) => {
  event.waitUntil(refreshStaticAssets());
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key.startsWith("vps-agent-static-") && key !== CACHE_NAME).map((key) => caches.delete(key))),
    ),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    const networkResponse = fetch(request);
    event.respondWith(networkResponse.catch(() => caches.match("/offline.html")));
    event.waitUntil(networkResponse.then(() => refreshStaticAssets()).catch(() => undefined));
    return;
  }

  if (STATIC_ASSETS.includes(url.pathname)) {
    event.respondWith(caches.match(request).then((cached) => cached || fetch(request)));
  }
});
