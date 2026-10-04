// Saved reviews and where you were in each one. The list (small) is in localStorage so the front page can draw it
// at once; the reviews themselves (large) are in IndexedDB, see store.js.
import * as store from "./store.js";

const INDEX_KEY = "movelens.history.v3";
const LEGACY_INDEX_KEY = "movelens.history.v2";
const MAX_ENTRIES = 60;

function readIndex() {
  try { return JSON.parse(localStorage.getItem(INDEX_KEY) || "[]"); } catch (e) { return []; }
}
function writeIndex(list) {
  try { localStorage.setItem(INDEX_KEY, JSON.stringify(list)); } catch (e) { /* storage blocked */ }
}

export const listReviews = () => readIndex();

export async function loadReview(id) {
  return (await store.get("reviews", id)) ?? null;
}

export async function saveReview(id, result) {
  const w = result.players.white, b = result.players.black;
  const entry = {
    id, savedAt: Math.floor(Date.now() / 1000),
    white: w.name, black: b.name, whiteRating: w.rating, blackRating: b.rating,
    accWhite: w.accuracy, accBlack: b.accuracy, result: result.result, opening: result.opening?.name || null,
    plies: result.moves.length, quality: result.quality || null,
  };
  const ok = await store.set("reviews", id, result);
  if (!ok) return false;
  const list = readIndex().filter((e) => e.id !== id);
  list.unshift(entry);
  while (list.length > MAX_ENTRIES) {
    const old = list.pop();
    await store.del("reviews", old.id);
    await store.del("kv", `session:${old.id}`);
  }
  writeIndex(list);
  return true;
}

export async function removeReview(id) {
  await store.del("reviews", id);
  await store.del("kv", `session:${id}`);
  writeIndex(readIndex().filter((e) => e.id !== id));
}

export async function clearReviews() {
  for (const e of readIndex()) await store.del("kv", `session:${e.id}`);
  await store.clear("reviews");
  writeIndex([]);
}

// ---- where you were in a review: the move shown, lines you explored, retries, tab, board side
export const loadSession = (id) => store.get("kv", `session:${id}`);
export const saveSession = (id, state) => store.set("kv", `session:${id}`, state);

/** Reviews saved by the previous version (plain localStorage) are moved into IndexedDB once. */
export async function migrateLegacy() {
  let old;
  try { old = JSON.parse(localStorage.getItem(LEGACY_INDEX_KEY) || "null"); } catch (e) { old = null; }
  if (!old || !old.length) return;
  const index = readIndex();
  for (const entry of old) {
    try {
      const raw = localStorage.getItem(`movelens.review.${entry.id}`);
      if (raw && !index.some((e) => e.id === entry.id) && await store.set("reviews", entry.id, JSON.parse(raw))) index.push(entry);
      localStorage.removeItem(`movelens.review.${entry.id}`);
    } catch (e) { /* skip a damaged entry */ }
  }
  writeIndex(index.sort((a, b) => b.savedAt - a.savedAt));
  try { localStorage.removeItem(LEGACY_INDEX_KEY); } catch (e) { /* ignore */ }
}
