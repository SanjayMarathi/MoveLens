// The live numbers on the front page (games reviewed, moves analysed, users, online now), and this tab's part in them.
//
// While the page is visible it sends a heartbeat every 30 seconds; hiding or closing the tab says goodbye at once,
// so "online now" means people looking at MoveLens right now. Nothing personal is sent: a random id this browser
// made for itself (so it is counted as a user once), and a random id for this tab (so two tabs count as one person).
import { $ } from "./util.js";

const KEY = "movelens.visitor";
const BEAT_MS = 30000;
const ID = /^[A-Za-z0-9_-]{8,64}$/;

const randomId = () => [...crypto.getRandomValues(new Uint8Array(12))].map((b) => b.toString(36).padStart(2, "0")).join("");

function loadVisitor() {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || "null");
    if (v && ID.test(v.id)) return v;
  } catch (e) { /* private mode */ }
  const v = { id: randomId(), counted: false };
  saveVisitor(v);
  return v;
}
function saveVisitor(v) { try { localStorage.setItem(KEY, JSON.stringify(v)); } catch (e) { /* private mode */ } }

const visitor = loadVisitor();
const tab = randomId();
let timer = null, busy = false;

/** Send a heartbeat now (and every 30 s while the page is visible), and show the numbers it brings back. */
export async function beat() {
  clearTimeout(timer);
  if (document.visibilityState !== "visible") return;
  timer = setTimeout(beat, BEAT_MS);
  if (busy) return;
  busy = true;
  try {
    const res = await fetch("/api/presence", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ visitor: visitor.id, tab, first: !visitor.counted }),
    });
    const data = res.ok ? await res.json() : null;          // a sleeping host answers with its own page: ignore it
    if (data?.counted && !visitor.counted) { visitor.counted = true; saveVisitor(visitor); }
    if (data?.stats) render(data.stats);
  } catch (e) { /* offline or asleep: try again next beat */ }
  finally { busy = false; }
}

function leave() {
  clearTimeout(timer);
  try { navigator.sendBeacon?.("/api/presence/leave", new Blob([JSON.stringify({ tab })], { type: "application/json" })); }
  catch (e) { /* ignore */ }
}

export function startPresence() {
  document.addEventListener("visibilitychange", () => (document.visibilityState === "visible" ? beat() : leave()));
  window.addEventListener("pagehide", leave);
  window.addEventListener("pageshow", (e) => { if (e.persisted) beat(); });   // back from the browser's page cache
  beat();
}

// ------------------------------------------------------------------ drawing the numbers
const shown = {};
const compact = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });
const fmt = (n) => (n >= 1e6 ? compact.format(n) : Math.round(n).toLocaleString());
const calm = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

function countTo(el, key, target) {
  const from = shown[key] ?? 0;
  shown[key] = target;
  if (from === target || calm() || document.visibilityState !== "visible") { el.textContent = fmt(target); return; }
  const t0 = performance.now(), ms = from ? 600 : 1100;
  const step = (now) => {
    const k = Math.min(1, (now - t0) / ms), eased = 1 - (1 - k) ** 3;
    el.textContent = fmt(from + (target - from) * eased);
    if (k < 1 && shown[key] === target) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function render(stats) {
  const box = $("stats");
  if (!box) return;
  for (const key of ["games", "moves", "users", "online"]) {
    const el = box.querySelector(`[data-stat="${key}"]`);
    if (el && Number.isFinite(stats[key])) countTo(el, key, stats[key]);
  }
  box.classList.add("ready");
  if (stats.since) {
    const day = new Date(stats.since * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
    $("stats-since").textContent = `Live numbers from everyone using MoveLens, counted since ${day}.`;
  }
}
