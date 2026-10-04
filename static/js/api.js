// Thin wrappers around the server's JSON API.
//
// Answers that never change for the same question (legal moves, a move judged, engine lines, a games list for a few
// minutes) are kept in the browser, in memory and in IndexedDB. The second time you visit a position it is instant,
// it costs the server nothing, and positions you have seen work even while the server is asleep or you are offline.
import * as store from "./store.js";

async function request(path, { method = "GET", body, signal } = {}) {
  let res;
  try {
    res = await fetch(path, { method, signal, headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  } catch (e) {
    if (e.name === "AbortError") throw e;
    throw new Error("Could not reach the server. Check your connection and try again.");
  }
  let data = null, isJson = false;
  try { data = await res.json(); isJson = true; } catch (e) { /* not JSON */ }
  // A free host that is asleep answers with its own "starting" page (HTML, or a 502/503) instead of our JSON.
  if (!isJson && (res.ok || [502, 503, 504].includes(res.status))) throw new Error(WAKING);
  if (!res.ok) {
    const d = data && data.detail;
    throw new Error(typeof d === "string" ? d : Array.isArray(d) ? "That request wasn't valid." : `The server answered with an error (${res.status}).`);
  }
  return data;
}

export const WAKING = "The server is waking up. A free host sleeps when nobody has used it for a while, and this takes about a minute. Try again shortly.";

// ---- remembered answers
const MAX_MEMORY = 600;          // answers kept for instant reuse in this tab
const MAX_STORED = 4000;         // answers kept in IndexedDB before the oldest are dropped
const memory = new Map();
let writes = 0;

async function remembered(key, fetcher, ttlMs = Infinity) {
  if (memory.has(key)) { const m = memory.get(key); if (Date.now() - m.t < ttlMs) return m.v; }
  const hit = await store.get("analysis", key);
  if (hit && Date.now() - hit.t < ttlMs) { memory.set(key, hit); return hit.v; }
  const v = await fetcher();                                     // errors are not remembered
  const entry = { v, t: Date.now() };
  memory.set(key, entry);
  if (memory.size > MAX_MEMORY) memory.delete(memory.keys().next().value);
  store.set("analysis", key, entry).then(() => { if (++writes % 80 === 0) store.trim("analysis", MAX_STORED); });
  return v;
}

export async function clearAnalysisCache() {
  memory.clear();
  await store.clear("analysis");
}

export const api = {
  health: (signal) => request("/api/health", { signal }),
  createReview: (pgn, quality) => request("/api/reviews", { method: "POST", body: { pgn, quality } }),
  getReview: (id) => request(`/api/reviews/${encodeURIComponent(id)}`),
  legal: (fen) => remembered(`legal:${fen}`, () => request("/api/legal", { method: "POST", body: { fen } })),
  explore: (p) => remembered(`explore:${p.quality}:${p.fen}:${p.uci}:${p.previous_label || ""}:${p.recapture_square || ""}`,
    () => request("/api/explore", { method: "POST", body: p })),
  lines: (fen, count, quality, signal) => remembered(`lines:${quality}:${count}:${fen}`,
    () => request("/api/analyse", { method: "POST", body: { fen, count, quality }, signal })),
  importGames: (site, user) => remembered(`import:${site}:${user.toLowerCase()}`,
    () => request(`/api/import/${site}?user=${encodeURIComponent(user)}`), 10 * 60 * 1000),
  sample: () => request("/static/data/opera.json"),
};
