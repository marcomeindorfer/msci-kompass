/* Service Worker: nötig für die Installation als App.
   Erst Netz, dann Cache: neue Kurse kommen beim Öffnen sofort an, ohne Netz gibt's den letzten Stand. */
const CACHE = "msci-kompass-v1";
const DATEIEN = ["./", "./index.html", "./manifest.json", "./icon-192.png", "./icon-512.png"];
self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => Promise.allSettled(DATEIEN.map(d => c.add(d)))).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(k => Promise.all(k.filter(n => n !== CACHE).map(n => caches.delete(n)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const u = new URL(e.request.url);
  if (e.request.method !== "GET" || u.origin !== location.origin) return;
  e.respondWith(fetch(e.request, {cache: "no-store"}).then(res => {
    const kopie = res.clone(); caches.open(CACHE).then(c => c.put(e.request, kopie)); return res;
  }).catch(() => caches.match(e.request).then(r => r || caches.match("./index.html"))));
});
