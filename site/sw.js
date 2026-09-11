/* Haber Akışı service worker
 *
 * Kabuk (HTML/JS/ikon) cache-first: uygulama çevrimdışı da açılır.
 * Bülten verisi network-first: internet varsa hep taze, yoksa son bülten.
 */
const VERSION = "v3";
const SHELL_CACHE = `mynews-shell-${VERSION}`;
const DATA_CACHE = `mynews-data-${VERSION}`;
// Ses ayrı ve sürümsüz: bülten güncellense de indirilmiş sesler durmalı.
const AUDIO_CACHE = "mynews-audio";

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
            .filter((key) => ![SHELL_CACHE, DATA_CACHE, AUDIO_CACHE].includes(key))
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

  // Ses: önce cache. Bir kez indirilen ses çevrimdışı da çalar; dosya
  // adları içerik hash'i olduğu için tazeleme derdi yok.
  if (url.pathname.includes("/audio/")) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(AUDIO_CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        });
      })
    );
    return;
  }

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

  // Kabuk: cache'i hemen ver, arka planda ağdan tazele (stale-while-revalidate).
  //
  // Burası düz cache-first'tü ve sessiz bir hataydı: index.html ile app.js
  // kurulumda cache'e giriyor, VERSION elle değiştirilmedikçe bir daha asla
  // yenilenmiyordu. Yani uygulamayı ana ekranına ekleyen biri, yayınlanan
  // her düzeltmeyi kaçırıyordu — kod deposunda düzelmiş, kullanıcıda
  // düzelmemiş. Sürüm numarasını her yayında elle artırmayı hatırlamak
  // güvenilir bir plan değil; bugün iki kez unuttum.
  //
  // Artık açılış yine anında (cache'ten), ama aynı anda ağdan yeni sürüm
  // çekilip cache'e yazılıyor: bir sonraki açılışta yeni kod çalışıyor.
  event.respondWith(
    caches.match(request).then((cached) => {
      const fresh = fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(SHELL_CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(() => {
          if (cached) return cached;
          if (request.mode === "navigate") return caches.match("./index.html");
          return Response.error();
        });

      return cached || fresh;
    })
  );
});

/* Uygulama "çevrimdışı kaydet" dediğinde sesleri toplu indirir ve
 * ilerlemeyi sayfaya bildirir. */
self.addEventListener("message", (event) => {
  const data = event.data || {};
  if (data.type !== "cache-audio" || !Array.isArray(data.urls)) return;

  event.waitUntil(
    caches.open(AUDIO_CACHE).then(async (cache) => {
      let done = 0;
      let failed = 0;
      for (const url of data.urls) {
        try {
          const hit = await cache.match(url);
          if (!hit) await cache.add(url);
          done += 1;
        } catch {
          failed += 1;
        }
        const clients = await self.clients.matchAll();
        clients.forEach((client) =>
          client.postMessage({ type: "cache-audio-progress", done, failed, total: data.urls.length })
        );
      }
    })
  );
});
