// MoveLens service worker. It keeps the app in the browser so it opens instantly and keeps working offline.
// When the server sends this file it fills in the two placeholders below: a version number that changes whenever
// any app file changes (so every deploy refreshes the saved copy), and the list of files to keep.
//
//   code (html, css, js, data)  network first, falling back to the saved copy when offline OR when the server is
//                               slow to answer (a free host that is waking up can take a minute)
//   images (pieces, scenes)     saved copy first, fetched once and kept
//   /api/*                      never touched here (the page keeps its own copy of engine answers, see store.js)
const VERSION = "__VERSION__";
const SHELL = `movelens-shell-${VERSION}`;
const MEDIA = "movelens-media";
const PRECACHE = __PRECACHE__;
const SLOW_MS = 2500;                 // wait this long for the server before opening the saved copy
let slowUntil = 0;                    // while the server is known to be slow, serve saved code at once

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) {
      if (name.startsWith("movelens-shell-") && name !== SHELL) await caches.delete(name);   // drop the previous version
    }
    await self.clients.claim();
  })());
});

const isMedia = (path) => /^\/static\/(pieces|bg)\//.test(path) || /\.(jpg|jpeg|png|svg|woff2?)$/.test(path);

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin || url.pathname.startsWith("/api/") || url.pathname === "/sw.js") return;

  if (req.mode === "navigate") {                         // the page itself
    event.respondWith(networkFirst(event, "/", true));
    return;
  }
  if (url.pathname.startsWith("/static/") || url.pathname === "/manifest.webmanifest") {
    event.respondWith(isMedia(url.pathname) ? cacheFirst(req) : networkFirst(event, req, false));
  }
});

async function networkFirst(event, key, isPage) {
  const req = event.request;
  const cache = await caches.open(SHELL);
  const saved = await cache.match(key);

  const network = fetch(req).then(async (res) => {
    const isHtml = (res.headers.get("content-type") || "").includes("text/html");
    // Only keep what really is ours: the page carries an X-MoveLens header; a script or style is never HTML.
    // (A sleeping host answers with its own "starting" page. That must never replace the saved app.)
    const ours = res.ok && (isPage ? !!res.headers.get("x-movelens") : !isHtml);
    if (ours) { await cache.put(key, res.clone()); return res; }
    if (saved) throw new Error("not the app");
    return res;
  });

  if (!saved) return network;                            // first visit: nothing saved yet, so wait for the server
  event.waitUntil(network.catch(() => {}));              // keep refreshing the saved copy in the background
  if (Date.now() < slowUntil) return saved;              // the server is slow right now: don't wait file by file
  const tooSlow = new Promise((resolve) => setTimeout(() => { slowUntil = Date.now() + 90000; resolve(saved); }, SLOW_MS));
  return Promise.race([network.catch(() => saved), tooSlow]);
}

async function cacheFirst(req) {
  const hit = await caches.match(req);
  if (hit) return hit;
  const res = await fetch(req);
  if (res.ok) (await caches.open(MEDIA)).put(req, res.clone());
  return res;
}
