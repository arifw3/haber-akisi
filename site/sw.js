/* Haber Akışı service worker
 *
 * Kabuk (HTML/JS/ikon) cache-first: uygulama çevrimdışı da açılır.
 * Bülten verisi network-first: internet varsa hep taze, yoksa son bülten.
 */
const VERSION = "v1";
const SHELL_CACHE = `mynews-shell-${VERSION}`;
const DATA_CACHE = `mynews-data-${VERSION}`;

const SHELL = [
  "./",
  "./index.html",
  "./app.js",
  "./manifest.webmanifest",
  "./icons/icon.svg",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      // Tek bir dosya (ör. ikon) eksikse kurulum tümden düşmesin.
      .then((cache) => Promise.allSettled(SHELL.map((url) => cache.add(url))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key !== SHELL_CACHE && key !== DATA_CACHE)
            .map((key) => caches.delete(key))
        )
      )
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);

  // Bülten verisi: önce ağ, olmazsa cache.
  if (url.pathname.endsWith(".json")) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(DATA_CACHE).then((cache) => cache.put(request, copy));
          return response;
        })
        .catch(() => caches.match(request))
    );
    return;
  }

  // Tailwind CDN ve yayıncı faviconları: cache'e al, sonra ağdan tazele.
  if (url.origin !== self.location.origin) {
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ||
          fetch(request)
            .then((response) => {
              const copy = response.clone();
              caches.open(SHELL_CACHE).then((cache) => cache.put(request, copy));
              return response;
            })
            .catch(() => cached)
      )
    );
    return;
  }

  // Kabuk: önce cache, yoksa ağ. Gezinti isteklerinde index.html'e düş.
  event.respondWith(
    caches.match(request).then(
      (cached) =>
        cached ||
        fetch(request).catch(() => {
          if (request.mode === "navigate") return caches.match("./index.html");
          return Response.error();
        })
    )
  );
});
