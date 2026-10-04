// Preferences (saved in this browser) and the theme picker UI.
import { $, $$, BOARDS, SCENES, PIECE_SETS, PIECE_KEYS, pieceUrl, esc } from "./util.js";
import { setSoundEnabled } from "./sound.js";

const KEY = "movelens.prefs.v2";
export const DEFAULTS = { scene: "sky", board: "sky", pieces: "cburnett", view: "auto", me: "", sound: true, depth: "deep" };

function load() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { /* private mode */ }
  const p = { ...DEFAULTS, ...saved };
  // A link can carry a look: /?scene=night&board=green&pieces=merida&view=black&me=name (applied, not saved)
  const q = new URLSearchParams(location.search);
  for (const k of Object.keys(DEFAULTS)) if (q.has(k)) p[k] = k === "sound" ? q.get(k) !== "0" : q.get(k);
  if (!SCENES[p.scene]) p.scene = DEFAULTS.scene;
  if (!BOARDS[p.board]) p.board = DEFAULTS.board;
  if (!PIECE_SETS[p.pieces]) p.pieces = DEFAULTS.pieces;
  if (!["auto", "white", "black"].includes(p.view)) p.view = "auto";
  if (!["fast", "standard", "deep", "max"].includes(p.depth)) p.depth = DEFAULTS.depth;
  return p;
}

export const prefs = load();

export function setPref(key, value) {
  prefs[key] = value;
  try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch (e) { /* ignore */ }
  applyPrefs();
  document.dispatchEvent(new CustomEvent("prefs", { detail: { key } }));
}

export function applyPrefs() {
  const b = BOARDS[prefs.board];
  const root = document.documentElement;
  document.body.dataset.scene = prefs.scene;
  root.style.setProperty("--light", b.light);
  root.style.setProperty("--dark", b.dark);
  $("piece-css").textContent = PIECE_KEYS.map((k) => `.p-${k}{background-image:url(${pieceUrl(prefs.pieces, k)})}`).join("\n");
  setSoundEnabled(prefs.sound);
  const icon = prefs.sound ? "#i-vol" : "#i-mute";
  for (const id of ["sound-btn", "rv-sound"]) { const use = $(id)?.querySelector("use"); if (use) use.setAttribute("href", icon); }
  $$(".picker").forEach(syncPicker);
}

function syncPicker(el) {
  $$("[data-scene]", el).forEach((c) => c.setAttribute("aria-pressed", c.dataset.scene === prefs.scene));
  $$("[data-board]", el).forEach((c) => c.setAttribute("aria-pressed", c.dataset.board === prefs.board));
  $$("[data-pieces]", el).forEach((c) => c.setAttribute("aria-pressed", c.dataset.pieces === prefs.pieces));
  const sw = $$("input[data-sound]", el)[0];
  if (sw) sw.checked = prefs.sound;
}

/** Fill `el` with the scene / board / piece / sound controls. */
export function mountThemePicker(el) {
  el.innerHTML = `
    <h3>Scene</h3>
    <div class="scenes">${Object.entries(SCENES).map(([id, s]) =>
      `<button class="chip" data-scene="${id}" aria-pressed="false" title="${s.name}"><span class="th" style="background-image:${s.thumb}"></span>${s.name}</button>`).join("")}</div>
    <h3>Board</h3>
    <div class="boards">${Object.entries(BOARDS).map(([id, t]) =>
      `<button class="chip" data-board="${id}" aria-pressed="false" title="${t.name}"><span class="sw" style="background:conic-gradient(${t.light} 25%,${t.dark} 0 50%,${t.light} 0 75%,${t.dark} 0)"></span>${esc(t.name)}</button>`).join("")}</div>
    <h3>Pieces</h3>
    <div class="piece-sets">${Object.entries(PIECE_SETS).map(([id, name]) =>
      `<button class="chip" data-pieces="${id}" aria-pressed="false" title="${name}"><span class="pv"><i style="background-image:url(${pieceUrl(id, "wN")})"></i><i style="background-image:url(${pieceUrl(id, "bQ")})"></i><i style="background-image:url(${pieceUrl(id, "wR")})"></i></span>${name}</button>`).join("")}</div>
    <h3>Sound</h3>
    <label class="switch"><span>Move sounds</span><input type="checkbox" data-sound></label>`;
  el.addEventListener("click", (e) => {
    const c = e.target.closest(".chip");
    if (!c) return;
    if (c.dataset.scene) setPref("scene", c.dataset.scene);
    if (c.dataset.board) setPref("board", c.dataset.board);
    if (c.dataset.pieces) setPref("pieces", c.dataset.pieces);
  });
  el.querySelector("input[data-sound]").addEventListener("change", (e) => setPref("sound", e.target.checked));
  syncPicker(el);
}
