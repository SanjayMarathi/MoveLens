// Everything MoveLens remembers in your browser lives here, in IndexedDB (a large store that survives restarts):
//
//   reviews   finished reviews (the full annotated game)
//   analysis  engine answers: legal moves, your moves judged, engine lines. Seen positions never hit the server twice
//   kv        small things: where you were in each review, your unsent form, the last games you looked up
//
// It stays until you clear this site's data in the browser. If the browser blocks IndexedDB (some private
// windows do), the same calls fall back to memory for that tab, so the app still works.
const NAME = "movelens";
const STORES = ["reviews", "analysis", "kv"];
const memory = Object.fromEntries(STORES.map((s) => [s, new Map()]));
let dbPromise = null;

function open() {
  if (!dbPromise) {
    dbPromise = new Promise((resolve) => {
      try {
        const req = indexedDB.open(NAME, 1);
        req.onupgradeneeded = () => { for (const s of STORES) if (!req.result.objectStoreNames.contains(s)) req.result.createObjectStore(s); };
        req.onsuccess = () => resolve(req.result);
        req.onerror = req.onblocked = () => resolve(null);
      } catch (e) { resolve(null); }
    });
  }
  return dbPromise;
}

async function run(store, mode, work) {
  const db = await open();
  if (!db) return { ok: false };
  return new Promise((resolve) => {
    try {
      const tx = db.transaction(store, mode);
      const result = work(tx.objectStore(store));
      tx.oncomplete = () => resolve({ ok: true, value: result?.result });
      tx.onerror = tx.onabort = () => resolve({ ok: false, error: tx.error });
    } catch (e) { resolve({ ok: false, error: e }); }
  });
}

export async function get(store, key) {
  const r = await run(store, "readonly", (s) => s.get(key));
  return r.ok ? r.value : memory[store].get(key);
}
export async function set(store, key, value) {
  const r = await run(store, "readwrite", (s) => s.put(value, key));
  if (!r.ok) memory[store].set(key, value);
  return r.ok;
}
export async function del(store, key) {
  memory[store].delete(key);
  await run(store, "readwrite", (s) => s.delete(key));
}
export async function count(store) {
  const r = await run(store, "readonly", (s) => s.count());
  return r.ok ? r.value : memory[store].size;
}
export async function clear(store) {
  memory[store].clear();
  await run(store, "readwrite", (s) => s.clear());
}
export async function allKeys(store) {
  const r = await run(store, "readonly", (s) => s.getAllKeys());
  return r.ok ? r.value : [...memory[store].keys()];
}

/** Keep at most `max` entries of an {t: timestamp} store, dropping the oldest. */
export async function trim(store, max) {
  const db = await open();
  if (!db) return;
  const entries = [];
  await new Promise((resolve) => {
    try {
      const req = db.transaction(store, "readonly").objectStore(store).openCursor();
      req.onsuccess = () => { const c = req.result; if (c) { entries.push([c.key, c.value?.t || 0]); c.continue(); } else resolve(); };
      req.onerror = () => resolve();
    } catch (e) { resolve(); }
  });
  if (entries.length <= max) return;
  entries.sort((a, b) => a[1] - b[1]);
  const drop = entries.slice(0, entries.length - max + Math.floor(max / 8));       // free a little extra room
  await run(store, "readwrite", (s) => { for (const [k] of drop) s.delete(k); });
}

/** { used, quota } in bytes, or null if the browser can't say. */
export async function usage() {
  try { const e = await navigator.storage.estimate(); return { used: e.usage || 0, quota: e.quota || 0 }; } catch (err) { return null; }
}
/** Ask the browser not to evict our data when it is short of space. */
export async function persist() {
  try { return (await navigator.storage.persisted()) || (await navigator.storage.persist()); } catch (e) { return false; }
}
