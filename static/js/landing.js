// The front page: the review form, importing games by username, recent reviews, and the animated demo.
import { $, $$, esc, LABELS, LABEL_ORDER, SHORTCUTS, badge, timeAgo, debounce, toast } from "./util.js";
import { prefs, setPref } from "./prefs.js";
import { api, clearAnalysisCache } from "./api.js";
import { listReviews, removeReview, clearReviews } from "./history.js";
import * as store from "./store.js";
import { createBoard } from "./board.js";

const state = { src: "pgn", games: [], selected: null, imported: null };   // imported: { site, user, games, t } = the last lookup
let handlers = {};

const DEPTH_HINT = {
  fast: "Depth 12 · a quick scan, about 10 seconds for a typical game.",
  standard: "Depth 16 · balanced, about 30 seconds.",
  deep: "Depth 20 · strong analysis, about 1–2 minutes. Recommended.",
  max: "Depth 24 · the strongest setting, about 3–5 minutes on a fast server.",
};
const QUALITY_ORDER = ["fast", "standard", "deep", "max"];

export function initLanding(h) {
  handlers = h;
  renderStatic();

  // where is the game?
  $$(".source-tabs button").forEach((b) => (b.onclick = () => setSource(b.dataset.src)));
  $("finder").onsubmit = (e) => { e.preventDefault(); findGames(); };
  $("games").onclick = (e) => {
    const row = e.target.closest(".game-row");
    if (!row) return;
    state.selected = state.games[+row.dataset.i];
    $$(".game-row").forEach((r) => r.setAttribute("aria-pressed", r === row));
    showError("");
  };
  $("sample-btn").onclick = () => handlers.onSample();
  $("pgn-file").onchange = async (e) => {
    const f = e.target.files[0];
    if (!f) return;
    $("pgn").value = await f.text();
    setSource("pgn");
    e.target.value = "";
  };

  // options
  $("me").value = prefs.me;
  $("me").oninput = () => { setPref("me", $("me").value.trim()); updateViewHint(); };
  $("view-seg").onclick = (e) => { const b = e.target.closest("button"); if (b) { setPref("view", b.dataset.view); syncView(); } };
  $("quality").value = prefs.depth;
  $("quality").onchange = () => { setPref("depth", $("quality").value); $("depth-hint").textContent = DEPTH_HINT[$("quality").value]; };
  $("depth-hint").textContent = DEPTH_HINT[$("quality").value];
  syncView();

  $("review-btn").onclick = submit;
  $("pgn").addEventListener("input", saveDraft);
  $("find-user").addEventListener("input", saveDraft);
  $("storage").onclick = storageClick;
  renderRecent();
  startDemo();
  restoreDraft();
}

// ------------------------------------------------------------------ remember the form (until the browser's site data is cleared)
const saveDraft = debounce(() => {
  store.set("kv", "landing", { src: state.src, pgn: $("pgn").value, user: $("find-user").value, imported: state.imported });
}, 500);

async function restoreDraft() {
  const d = await store.get("kv", "landing");
  if (!d) return;
  if (d.pgn && !$("pgn").value) $("pgn").value = d.pgn;
  if (d.src && d.src !== "pgn") {
    setSource(d.src, { restoring: true });
    $("find-user").value = d.user || d.imported?.user || "";
    if (d.imported && d.imported.site === d.src && Date.now() - d.imported.t < 6 * 3600 * 1000) {
      state.imported = d.imported;
      renderGames(d.imported.games, d.imported.user);
    }
  }
}

function setSource(src, { restoring = false } = {}) {
  state.src = src;
  $$(".source-tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.src === src));
  $("pane-pgn").classList.toggle("hidden", src !== "pgn");
  $("pane-import").classList.toggle("hidden", src === "pgn");
  if (src !== "pgn") {
    $("find-user").placeholder = src === "chesscom" ? "Your Chess.com username" : "Your Lichess username";
    state.games = []; state.selected = null; $("games").innerHTML = "";
    if (!restoring) { $("find-user").value = $("find-user").value || prefs.me; $("find-user").focus(); }
  }
  showError("");
  if (!restoring) saveDraft();
}

function renderGames(games, user) {
  state.games = games;
  state.selected = null;
  const u = user.toLowerCase();
  $("games").innerHTML = games.map((g, i) => {
    const side = g.white.toLowerCase() === u ? "white" : g.black.toLowerCase() === u ? "black" : null;
    const won = (g.result === "1-0" && side === "white") || (g.result === "0-1" && side === "black");
    const lost = (g.result === "1-0" && side === "black") || (g.result === "0-1" && side === "white");
    const cls = !side || g.result === "*" ? "" : won ? "win" : lost ? "loss" : "draw";
    const rating = (r) => (r ? ` <i>(${r})</i>` : "");
    return `<button class="game-row" role="option" data-i="${i}" aria-pressed="false">
      <span class="who">${esc(g.white)}${rating(g.white_rating)} vs ${esc(g.black)}${rating(g.black_rating)}</span>
      <span class="res ${cls}">${esc(g.result)}</span>
      <span class="meta">${esc([g.time_class, g.played_at ? timeAgo(g.played_at) : "", g.rated === false ? "Casual" : g.rated ? "Rated" : ""].filter(Boolean).join(" · "))}</span></button>`;
  }).join("");
}

async function findGames() {
  const user = $("find-user").value.trim();
  if (!user) return;
  const btn = $("find-btn");
  btn.disabled = true;
  $("games").innerHTML = `<div class="note">Searching…</div>`;
  state.selected = null;
  try {
    const data = await api.importGames(state.src, user);
    renderGames(data.games, user);
    state.imported = { site: state.src, user, games: data.games, t: Date.now() };
    saveDraft();
    if (!prefs.me) { setPref("me", user); $("me").value = user; updateViewHint(); }
  } catch (e) {
    $("games").innerHTML = `<div class="note">${esc(e.message)}</div>`;
  } finally { btn.disabled = false; }
}

function submit() {
  showError("");
  const pgn = state.src === "pgn" ? $("pgn").value.trim() : state.selected?.pgn;
  if (!pgn) return showError(state.src === "pgn" ? "Paste a game first, or try the famous game." : "Find your games and pick one from the list first.");
  handlers.onReview({ pgn, quality: $("quality").value });
}

function syncView() {
  $$("#view-seg button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.view === prefs.view));
  updateViewHint();
}
function updateViewHint() {
  const v = prefs.view, me = prefs.me;
  $("view-hint").textContent = v === "white" ? "White will be at the bottom of the board."
    : v === "black" ? "Black will be at the bottom of the board."
    : me ? `Auto: the board opens from ${me}'s side once ${me} is found in the game. Otherwise White is at the bottom.`
         : "Auto: White is at the bottom. Enter your username above and the board will open from your side.";
}

export function applyServerLimits(maxQuality) {
  const max = QUALITY_ORDER.indexOf(maxQuality);
  if (max < 0) return;
  $$("#quality option").forEach((o) => { o.disabled = QUALITY_ORDER.indexOf(o.value) > max; });
  if (QUALITY_ORDER.indexOf($("quality").value) > max) { $("quality").value = maxQuality; $("depth-hint").textContent = DEPTH_HINT[maxQuality] + " (This server's limit.)"; }
}

export function showError(msg) { $("error").textContent = msg; $("error").classList.toggle("hidden", !msg); }
export function setBusy(busy) { $("review-btn").disabled = busy; $("review-btn").textContent = busy ? "Reviewing…" : "Review game"; if (!busy) $("progress").classList.add("hidden"); }
export function setProgress(done, total, text) {
  $("progress").classList.remove("hidden");
  $("bar-fill").style.width = total ? `${(100 * done) / total}%` : "0";
  $("progress-text").textContent = text;
}

// ------------------------------------------------------------------ recent reviews
export function renderRecent() {
  const list = listReviews();
  $("recent").classList.toggle("hidden", !list.length);
  $("recent-list").innerHTML = list.map((e) => `
    <div class="recent-card" role="button" tabindex="0" data-id="${e.id}">
      <div class="vs">${esc(e.white)} vs ${esc(e.black)}</div>
      <div class="sub">${esc([e.result, e.opening, `${Math.ceil(e.plies / 2)} moves`, timeAgo(e.savedAt)].filter(Boolean).join(" · "))}</div>
      <div class="accs"><span class="w"><span>White</span><b>${e.accWhite ?? "–"}</b></span><span class="b"><span>Black</span><b>${e.accBlack ?? "–"}</b></span></div>
      <button class="btn btn-ghost del" data-del="${e.id}" title="Remove from this browser" aria-label="Remove"><svg class="icon"><use href="#i-close"/></svg></button>
    </div>`).join("");
  renderStorage();
}

// ------------------------------------------------------------------ "Saved on this device"
async function renderStorage() {
  const [positions, usage] = await Promise.all([store.count("analysis"), store.usage()]);
  const reviews = listReviews().length;
  const mb = usage ? ` · about ${Math.max(0.1, usage.used / 1048576).toFixed(1)} MB used` : "";
  $("storage").innerHTML = `<b>Saved on this device:</b> ${reviews} review${reviews === 1 ? "" : "s"}, ${positions} remembered position${positions === 1 ? "" : "s"}${mb}.
    They stay until you clear this site's data in your browser. <button class="link" data-clear="analysis">Forget positions</button> · <button class="link" data-clear="reviews">Delete saved reviews</button>`;
}
async function storageClick(e) {
  const what = e.target.closest("[data-clear]")?.dataset.clear;
  if (what === "analysis") { await clearAnalysisCache(); toast("Remembered positions cleared."); }
  if (what === "reviews") {
    if (!confirm("Delete all reviews saved in this browser?")) return;
    await clearReviews();
    toast("Saved reviews deleted.");
  }
  if (what) renderRecent();
}
function recentClick(e) {
  const del = e.target.closest("[data-del]");
  if (del) { e.stopPropagation(); removeReview(del.dataset.del).then(renderRecent); return; }
  const card = e.target.closest(".recent-card");
  if (card) handlers.onOpenHistory(card.dataset.id);
}

// ------------------------------------------------------------------ static content built from the label definitions
function renderStatic() {
  $("label-cards").innerHTML = LABEL_ORDER.map((k) => `
    <div class="label-card">${badge(k, "xl")}<div><h3>${LABELS[k].name}</h3><p>${LABELS[k].blurb}</p><span class="rule">${LABELS[k].rule}</span></div></div>`).join("");
  const keysHtml = SHORTCUTS.map(([keys, what]) =>
    `<div class="key-row"><span>${what}</span><span>${keys.map((k) => `<kbd>${k}</kbd>`).join(" ")}</span></div>`).join("");
  $("keys-list").innerHTML = keysHtml;
  $("keys-modal-list").innerHTML = keysHtml;
  $("recent-list").addEventListener("click", recentClick);
  $("recent-list").addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.classList.contains("recent-card")) recentClick(e); });
}

// ------------------------------------------------------------------ the animated demo in the hero
async function startDemo() {
  const el = $("demo-board");
  let data;
  try { data = await api.sample(); } catch (e) { el.closest(".demo")?.classList.add("hidden"); return; }
  const board = createBoard(el, {});
  const note = $("demo-note");
  let ply = 0;
  const show = () => {
    const m = ply ? data.moves[ply - 1] : null;
    board.render({ fen: m ? m.fen_after : data.start_fen, flipped: false, interactive: false, last: m ? { from: m.from, to: m.to, label: m.label } : null });
    note.innerHTML = m
      ? `<b>${badge(m.label, "lg")}${m.move_number}${m.color === "white" ? "." : "…"} ${esc(m.san)} · ${LABELS[m.label].name}</b>${esc(m.coach)}`
      : `<b>Morphy vs. the Duke and the Count</b>Paris, 1858. Watch MoveLens review a famous game, move by move.`;
  };
  const tick = () => {
    const visible = !document.hidden && !$("landing").classList.contains("hidden") && el.offsetParent !== null;
    if (visible) { ply = ply >= data.moves.length ? 0 : ply + 1; show(); }
    setTimeout(tick, ply === data.moves.length || ply === 0 ? 3200 : 1700);
  };
  show();
  setTimeout(tick, 2200);
}
