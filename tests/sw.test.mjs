// Tests for the service worker's trickiest job: never replace the saved app with a host's "waking up" page,
// and open the saved app at once when the server is slow. Run with:  node --test tests/sw.test.mjs   (Node 20+)
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const SOURCE = readFileSync(new URL("../static/sw.js", import.meta.url), "utf8");

/** Load sw.js into a sandbox with an in-memory Cache Storage and a fake network. */
function loadWorker(network) {
  const stores = new Map();
  const key = (r) => new URL(typeof r === "string" ? r : r.url, "https://app.test").pathname;
  const cacheNamed = (name) => {
    if (!stores.has(name)) stores.set(name, new Map());
    const m = stores.get(name);
    return {
      match: async (r) => m.get(key(r))?.clone(),
      put: async (r, res) => { m.set(key(r), res); },
      addAll: async (urls) => { for (const u of urls) m.set(key(u), new Response("precached " + u)); },
    };
  };
  const caches = {
    open: async (n) => cacheNamed(n), keys: async () => [...stores.keys()], delete: async (n) => stores.delete(n),
    match: async (r) => { for (const m of stores.values()) { const v = m.get(key(r)); if (v) return v.clone(); } },
  };
  const listeners = {};
  const self = { addEventListener: (type, fn) => { listeners[type] = fn; }, skipWaiting: async () => {}, clients: { claim: async () => {} } };
  const sandbox = { self, caches, fetch: (req) => network(key(req), req), location: { origin: "https://app.test" }, URL, Response, Headers, setTimeout, clearTimeout, Promise, Date };
  vm.createContext(sandbox);
  vm.runInContext(SOURCE.replace("__VERSION__", "test").replace("__PRECACHE__", "[]").replace("const SLOW_MS = 2500;", "const SLOW_MS = 60;"), sandbox);

  return {
    caches,
    /** Ask the worker to handle a request; resolves to the Response it chose, or null if it left the request alone. */
    async handle(path, { mode = "same-origin" } = {}) {
      let answer = null;
      const waits = [];
      const event = {
        request: { method: "GET", url: "https://app.test" + path, mode, headers: new Headers() },
        respondWith: (p) => { answer = p; },
        waitUntil: (p) => waits.push(p),
      };
      listeners.fetch(event);
      const t0 = Date.now();
      const res = answer ? await answer : null;
      if (res) res.tookMs = Date.now() - t0;                 // how long the worker itself took to choose an answer
      // background refreshes may never finish when the server is deliberately unresponsive: only wait briefly
      await Promise.race([Promise.allSettled(waits), new Promise((r) => setTimeout(r, 150))]);
      return res;
    },
    save: async (path, body, cacheName = "movelens-shell-test") => (await caches.open(cacheName)).put(path, new Response(body)),
  };
}

const page = (body, withHeader = true) => new Response(body, { status: 200, headers: { "content-type": "text/html", ...(withHeader ? { "x-movelens": "1" } : {}) } });
const never = () => new Promise(() => {});

test("a fresh page from our server is shown and saved", async () => {
  const w = loadWorker(() => Promise.resolve(page("NEW APP")));
  await w.save("/", "OLD APP");
  assert.equal(await (await w.handle("/", { mode: "navigate" })).text(), "NEW APP");
  assert.equal(await (await (await w.caches.open("movelens-shell-test")).match("/")).text(), "NEW APP");
});

test("the host's 'waking up' page never replaces the saved app", async () => {
  const w = loadWorker(() => Promise.resolve(page("<html>Space is starting</html>", false)));   // 200 OK, but not ours
  await w.save("/", "SAVED APP");
  assert.equal(await (await w.handle("/", { mode: "navigate" })).text(), "SAVED APP");
  assert.equal(await (await (await w.caches.open("movelens-shell-test")).match("/")).text(), "SAVED APP");
});

test("a 503 from the host opens the saved app", async () => {
  const w = loadWorker(() => Promise.resolve(new Response("busy", { status: 503, headers: { "content-type": "text/html" } })));
  await w.save("/", "SAVED APP");
  assert.equal(await (await w.handle("/", { mode: "navigate" })).text(), "SAVED APP");
});

test("a slow server: the saved app opens, and saved code follows without waiting file by file", async () => {
  const w = loadWorker(() => never());
  await w.save("/", "SAVED APP");
  await w.save("/static/js/main.js", "SAVED JS");
  const first = await w.handle("/", { mode: "navigate" });
  assert.equal(await first.text(), "SAVED APP");
  assert.ok(first.tookMs >= 50, `gave the server a moment first (${first.tookMs} ms)`);
  const next = await w.handle("/static/js/main.js");
  assert.equal(await next.text(), "SAVED JS");
  assert.ok(next.tookMs < 30, `later files are served at once while the server is slow (${next.tookMs} ms)`);
});

test("first ever visit (nothing saved) waits for the server and shows whatever it sends", async () => {
  const w = loadWorker(() => Promise.resolve(page("<html>Space is starting</html>", false)));
  assert.equal(await (await w.handle("/", { mode: "navigate" })).text(), "<html>Space is starting</html>");
});

test("a script answered with HTML (a host's interstitial) falls back to the saved script", async () => {
  const w = loadWorker(() => Promise.resolve(page("<html>starting</html>", false)));
  await w.save("/static/js/api.js", "SAVED JS");
  assert.equal(await (await w.handle("/static/js/api.js")).text(), "SAVED JS");
});

test("offline: saved page and script are used", async () => {
  const w = loadWorker(() => Promise.reject(new TypeError("offline")));
  await w.save("/", "SAVED APP");
  await w.save("/static/css/app.css", "SAVED CSS");
  assert.equal(await (await w.handle("/", { mode: "navigate" })).text(), "SAVED APP");
  assert.equal(await (await w.handle("/static/css/app.css")).text(), "SAVED CSS");
});

test("pieces and backgrounds are saved on first use and then served without the network", async () => {
  let calls = 0;
  const w = loadWorker(() => { calls++; return Promise.resolve(new Response("<svg/>", { status: 200, headers: { "content-type": "image/svg+xml" } })); });
  await w.handle("/static/pieces/merida/wK.svg");
  await w.handle("/static/pieces/merida/wK.svg");
  assert.equal(calls, 1);
});

test("API calls and other sites are never touched", async () => {
  const w = loadWorker(() => Promise.resolve(new Response("{}")));
  assert.equal(await w.handle("/api/health"), null);
  assert.equal(await w.handle("/sw.js"), null);
});
