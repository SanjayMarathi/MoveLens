// The review screen: stepping through a game, the coach, and playing your own moves on the board.
//
// State in one place (S):
//   ply    which move of the real game is shown (0 = start). In a side line it is the move the line branches from.
//   line   moves you played yourself after `ply` (each is judged by the server); li = how many of them are shown
//   retry  set while you are trying to find a better move than a mistake from the game
import {
  $, $$, esc, LABELS, SUMMARY_ORDER, GOOD_LABELS, BAD_LABELS, KEY_LABELS, NO_ARROW, badge, color, fmtClock,
  toast, copyText, download, debounce,
} from "./util.js";
import { createBoard, parseFen } from "./board.js";
import { api } from "./api.js";
import { prefs, setPref } from "./prefs.js";
import { sounds, soundForSan } from "./sound.js";
import { saveSession } from "./history.js";

const S = {
  id: null, result: null, ply: 0, line: [], li: 0, retry: null, flipped: false,
  tab: "review", showBest: false, explain: false, linesOn: false, auto: null, hasClocks: false, baseTime: null,
  keyPlies: [], token: 0, linesAbort: null,
};
let board = null;
let hooks = { onBack: () => {} };
const legalCache = new Map();

const PIECE_VALUE = { p: 1, n: 3, b: 3, r: 5, q: 9 };
const START_COUNT = { p: 8, n: 2, b: 2, r: 2, q: 1 };

// ------------------------------------------------------------------ small helpers
function getLegal(fen) {
  if (legalCache.has(fen)) return legalCache.get(fen);
  const p = api.legal(fen).catch((e) => { legalCache.delete(fen); throw e; });
  legalCache.set(fen, p);
  if (legalCache.size > 300) legalCache.delete(legalCache.keys().next().value);
  return p;
}

const norm = (s) => String(s || "").trim().toLowerCase();
export function mySide(result) {
  const me = norm(prefs.me);
  if (!me || !result) return null;
  const w = norm(result.players.white.name), b = norm(result.players.black.name);
  if (me === w && me !== b) return "white";
  if (me === b && me !== w) return "black";
  if (me.length >= 3) {                                  // forgiving: "sanjay" finds "Sanjaymarathi"
    const inW = w.includes(me), inB = b.includes(me);
    if (inW && !inB) return "white";
    if (inB && !inW) return "black";
  }
  return null;
}

function evalLabel(text) {                               // "-4.91" -> "-4.9" (the bar is narrow)
  const t = String(text).replace("+", "");
  if (!/^-?\d+\.\d+$/.test(t)) return t;
  const v = parseFloat(t);
  return Math.abs(v) < 0.05 ? "0.0" : v.toFixed(1);
}

const turnOf = (fen) => fen.split(" ")[1];
const fullmoveOf = (fen) => +fen.split(" ")[5] || 1;
const moveTitle = (m) => `${m.move_number}${m.color === "white" ? "." : "…"} ${m.san}`;
const figurine = (san, colorName) => {
  const m = /^([KQRBN])(.*)$/.exec(san);
  return m ? `<i class="fig p-${colorName === "white" ? "w" : "b"}${m[1]}"></i>${esc(m[2])}` : esc(san);
};

function pos() {
  if (S.li > 0) {
    const m = S.line[S.li - 1];
    return { fen: m.fen_after, move: m, ev: m.eval_after, inLine: true };
  }
  const m = S.ply > 0 ? S.result.moves[S.ply - 1] : null;
  return { fen: m ? m.fen_after : S.result.start_fen, move: m, ev: m ? m.eval_after : S.result.start_eval, inLine: false };
}
const exploring = () => S.line.length > 0 || !!S.retry;
const liveQuality = () => { const q = S.result.quality || "standard"; return q === "max" ? "deep" : q; };

function bestFor(p) {                                    // the engine's better move to show as an arrow
  if (S.retry && !p.inLine) return S.result.moves[S.retry.ply - 1]?.best_move || null;
  const m = p.move;
  if (!m || m.pending || NO_ARROW.has(m.label)) return null;
  return m.best_move || null;
}

// ------------------------------------------------------------------ setup
export function initReview(h) {
  hooks = { ...hooks, ...h };
  board = createBoard($("board"), { getLegal, onMove: playMove });

  $("rv-back").onclick = () => hooks.onBack();
  $("rv-flip").onclick = () => flip();
  $("rv-sound").onclick = () => setPref("sound", !prefs.sound);
  $("rv-theme").onclick = (e) => { e.stopPropagation(); $("theme-btn").click(); };
  $$(".tabs button").forEach((b) => (b.onclick = () => setTab(b.dataset.tab)));

  $("btn-explain").onclick = () => { S.explain = !S.explain; renderExplain(); renderActions(); };
  $("btn-best").onclick = () => { S.showBest = !S.showBest; renderBoard(); renderActions(); };
  $("btn-retry").onclick = startRetry;
  $("btn-next").onclick = () => (exploring() ? backToGame() : stepNext());
  $("c-first").onclick = () => goPly(0);
  $("c-prev").onclick = stepPrev;
  $("c-next").onclick = stepNext;
  $("c-last").onclick = () => goPly(S.result.moves.length);
  $("c-play").onclick = toggleAuto;
  // the same five actions on the bar pinned to the bottom of the screen (phones and tablets)
  $("m-first").onclick = () => goPly(0);
  $("m-prev").onclick = stepPrev;
  $("m-next").onclick = stepNext;
  $("m-last").onclick = () => goPly(S.result.moves.length);
  $("m-play").onclick = toggleAuto;

  $("x-undo").onclick = stepPrev;
  $("x-reset").onclick = backToGame;
  $("x-engine").onclick = playEngineMove;
  $("sw-lines").onchange = (e) => { S.linesOn = e.target.checked; renderLinesPanel(); fetchLines(); persistSession(); };
  $("elines").onclick = (e) => { const b = e.target.closest(".eline"); if (b) playUci(b.dataset.uci); };

  $("graph").onclick = (e) => {
    const r = $("graph").getBoundingClientRect();
    goPly(Math.round(((e.clientX - r.left) / r.width) * S.result.moves.length));
  };
  $("moves").onclick = (e) => {
    const el = e.target.closest(".mv");
    if (!el) return;
    if (el.dataset.line != null) { S.li = +el.dataset.line + 1; stopAuto(); render(); }
    else goPly(+el.dataset.ply);
  };
  $("tab-summary").onclick = (e) => {
    const k = e.target.closest("[data-ply]");
    if (k) return goPly(+k.dataset.ply);
    const a = e.target.closest("[data-act]")?.dataset.act;
    if (a === "copy-pgn") copyText(buildPgn(), "PGN copied");
    if (a === "download-pgn") download(`movelens-${(S.result.players.white.name || "white")}-vs-${(S.result.players.black.name || "black")}.pgn`.replace(/[^\w.-]+/g, "_"), buildPgn());
    if (a === "copy-link") copyText(location.href, "Link copied. It opens this review in this browser.");
  };

  document.addEventListener("prefs", () => { if (isOpen()) { renderBoard(); renderBars(); renderMoves(); renderCoach(); } });
  document.addEventListener("keydown", onKey);
}

export const isOpen = () => !!S.result && !$("review-view").classList.contains("hidden");

export function openReview(result, { id = null, ply = null, session = null } = {}) {
  stopAuto();
  S.id = id; S.result = result; S.line = []; S.li = 0; S.retry = null; S.showBest = false; S.explain = false;
  S.linesOn = false; S.tab = "review";
  const side = prefs.view === "auto" ? mySide(result) : prefs.view;
  S.flipped = side === "black";
  S.ply = Math.max(0, Math.min(result.moves.length, ply ?? 0));
  // Come back to exactly where you were (side line, retry, tab, board side), unless the link points somewhere else.
  if (session && session.v === 1 && (ply == null || ply === session.hashPly)) restoreSession(session);
  $("sw-lines").checked = S.linesOn;
  S.hasClocks = result.moves.some((m) => m.clock != null);
  const tc = /^(\d+)(?:\+\d+)?$/.exec(result.time_control || "");
  S.baseTime = tc ? +tc[1] : null;
  S.keyPlies = result.moves.map((m, i) => (KEY_LABELS.has(m.label) ? i + 1 : 0)).filter(Boolean);
  renderSummary();
  renderGraph();
  setTab(S.tab, true);
  render();
}

function restoreSession(ss) {
  const n = S.result.moves.length;
  S.ply = Math.max(0, Math.min(n, ss.ply | 0));
  S.line = (ss.line || []).filter((m) => m && m.fen_after && m.uci && !m.pending);
  S.li = Math.max(0, Math.min(S.line.length, ss.li | 0));
  S.retry = ss.retry && ss.retry.ply >= 1 && ss.retry.ply <= n ? ss.retry : null;
  S.flipped = !!ss.flipped;
  S.tab = ["review", "summary", "engine"].includes(ss.tab) ? ss.tab : "review";
  S.showBest = !!ss.showBest; S.explain = !!ss.explain; S.linesOn = !!ss.linesOn;
}

/** What to remember about this review so it can be reopened exactly as you left it. */
function sessionSnapshot() {
  return {
    v: 1, ply: S.ply, hashPly: S.retry ? S.retry.ply : S.ply, li: S.li, line: S.line.filter((m) => !m.pending),
    retry: S.retry, tab: S.tab, flipped: S.flipped, showBest: S.showBest, explain: S.explain, linesOn: S.linesOn, savedAt: Date.now(),
  };
}
const persistSession = debounce(() => { if (S.id && S.result) saveSession(S.id, sessionSnapshot()); }, 400);

export function closeReview() {
  stopAuto();
  if (S.id && S.result) saveSession(S.id, sessionSnapshot());       // don't lose the last moments to the save delay
  S.result = null;
}

// ------------------------------------------------------------------ navigation
function goPly(p) {
  stopAuto();
  const n = S.result.moves.length;
  const target = Math.max(0, Math.min(n, p));
  const forward = target > S.ply && !exploring();
  S.ply = target; S.line = []; S.li = 0; S.retry = null; S.showBest = false;
  render();
  if (forward && target > 0) soundForSan(S.result.moves[target - 1].san);
}
function stepNext() {
  stopAuto();
  if (S.li < S.line.length) { S.li++; render(); return soundForSan(S.line[S.li - 1].san); }
  if (S.line.length || S.retry) return;
  if (S.ply < S.result.moves.length) goPly(S.ply + 1);
}
function stepPrev() {
  stopAuto();
  if (S.li > 0) { S.li--; S.showBest = false; return render(); }
  if (S.line.length) { S.line = []; }
  if (S.retry) { S.retry = null; return render(); }
  goPly(S.ply - 1);
}
function backToGame() {
  stopAuto();
  const p = S.retry ? S.retry.ply : S.ply;
  goPly(p);
}
function flip() { S.flipped = !S.flipped; renderBoard(); renderBars(); renderEvalBar(); persistSession(); }
function jumpKey(dir) {
  const cur = exploring() ? (S.retry ? S.retry.ply : S.ply) : S.ply;
  const target = dir > 0 ? S.keyPlies.find((p) => p > cur) : [...S.keyPlies].reverse().find((p) => p < cur);
  if (target != null) goPly(target); else toast(dir > 0 ? "No more key moments" : "No earlier key moments");
}

function toggleAuto() {
  if (S.auto) return stopAuto();
  if (exploring()) backToGame();
  if (S.ply >= S.result.moves.length) S.ply = 0;
  S.auto = setInterval(() => {
    if (S.ply >= S.result.moves.length) return stopAuto();
    const p = S.ply + 1;
    S.ply = p; S.line = []; S.li = 0; S.retry = null; S.showBest = false;
    render(); soundForSan(S.result.moves[p - 1].san);
  }, 1250);
  setPlayIcon("#i-pause");
}
function setPlayIcon(icon) {                              // both play buttons (panel and bottom bar) show the same icon
  for (const id of ["c-play", "m-play"]) $(id)?.querySelector("use")?.setAttribute("href", icon);
}
function stopAuto() {
  if (S.auto) { clearInterval(S.auto); S.auto = null; }
  setPlayIcon("#i-play");
}

function setTab(name, silent) {
  S.tab = name;
  $$(".tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === name));
  for (const t of ["review", "summary", "engine"]) $(`tab-${t}`).classList.toggle("hidden", t !== name);
  if (!silent) { persistSession(); if (name === "engine") fetchLines(); }
}

// ------------------------------------------------------------------ playing your own moves
function playUci(uci) {
  getLegal(pos().fen).then((data) => {
    const m = data.moves.find((x) => x.uci === uci);
    if (m) playMove(m);
  }).catch((e) => toast(e.message));
}

async function playMove(m) {
  stopAuto();
  const p = pos();
  const fenBefore = p.fen;

  // 1. Playing the move the game itself continued with: just step forward.
  if (!exploring()) {
    const next = S.result.moves[S.ply];
    if (next && next.uci === m.uci) return goPly(S.ply + 1);
  }
  // 2. Re-playing the next move of a line you already explored.
  if (S.li < S.line.length && S.line[S.li].uci === m.uci) { S.li++; render(); return soundForSan(m.san); }

  S.line = S.line.slice(0, S.li);
  S.showBest = false;
  const prev = p.move;

  // 3. In a retry, playing the very move that was the mistake: no need to ask the server again.
  if (S.retry && S.line.length === 0 && S.li === 0) {
    const orig = S.result.moves[S.retry.ply - 1];
    if (orig.uci === m.uci) {
      S.line.push({ ...orig, retryResult: "same" }); S.li = 1; render(); return soundForSan(m.san);
    }
  }

  const entry = {
    uci: m.uci, san: m.san, from: m.uci.slice(0, 2), to: m.uci.slice(2, 4), fen_before: fenBefore, fen_after: m.fen,
    pending: true, label: null, eval_after: p.ev, color: turnOf(fenBefore) === "w" ? "white" : "black", move_number: fullmoveOf(fenBefore),
  };
  S.line.push(entry); S.li = S.line.length;
  render(); soundForSan(m.san);

  try {
    const res = await api.explore({
      fen: fenBefore, uci: m.uci, quality: liveQuality(),
      previous_label: prev && !prev.pending ? prev.label : null,
      recapture_square: prev && /x/.test(prev.san) ? prev.to : null,
    });
    if (!S.line.includes(entry)) return;                 // you moved on while the engine was thinking
    Object.assign(entry, res, { pending: false });
    if (S.retry) {
      entry.retryResult = GOOD_LABELS.has(res.label) ? "ok" : "no";
      if (entry.retryResult === "ok") S.retry.solved = true;
    }
    render();
    if (res.status !== "ongoing") sounds.end();
    else if (S.retry) (entry.retryResult === "ok" ? sounds.good : sounds.bad)();
  } catch (e) {
    if (!S.line.includes(entry)) return;
    S.line = S.line.filter((x) => x !== entry);
    S.li = Math.min(S.li, S.line.length);
    toast(e.message);
    render();
  }
}

function startRetry() {
  const m = !S.line.length && S.ply > 0 ? S.result.moves[S.ply - 1] : null;
  if (!m || !BAD_LABELS.has(m.label)) return;
  S.retry = { ply: S.ply, san: m.san, label: m.label, solved: false };
  S.ply -= 1; S.line = []; S.li = 0; S.showBest = false; S.explain = false;
  render();
}

async function playEngineMove() {
  const p = pos();
  try {
    const data = await api.lines(p.fen, 1, liveQuality());
    const line = data.lines[0];
    if (!line) return toast("The game is over. There are no moves to play.");
    playUci(line.uci);
  } catch (e) { toast(e.message); }
}

// ------------------------------------------------------------------ rendering
function render() {
  renderBoard();
  renderBars();
  renderEvalBar();
  renderCoach();
  renderActions();
  renderExplain();
  renderMoves();
  renderGraphCursor();
  renderLinesPanel();
  fetchLines();
  persistSession();
  if (S.id && !exploring()) history.replaceState(null, "", `${location.pathname}${location.search}#r=${S.id}${S.ply ? "&ply=" + S.ply : ""}`);
}

function renderBoard() {
  const p = pos(), m = p.move;
  const best = S.showBest ? bestFor(p) : null;
  board.render({
    fen: p.fen, flipped: S.flipped, interactive: true,
    last: m ? { from: m.from, to: m.to, label: m.pending ? null : m.label } : null,
    arrows: best ? [{ from: best.uci.slice(0, 2), to: best.uci.slice(2, 4), color: "best" }] : [],
  });
}

function material(fen) {
  const { grid } = parseFen(fen);
  const c = { w: { p: 0, n: 0, b: 0, r: 0, q: 0 }, b: { p: 0, n: 0, b: 0, r: 0, q: 0 } };
  for (const ch of Object.values(grid)) {
    const k = ch.toLowerCase();
    if (k in PIECE_VALUE) c[ch === k ? "b" : "w"][k]++;
  }
  const value = (side) => Object.entries(c[side]).reduce((s, [k, n]) => s + PIECE_VALUE[k] * n, 0);
  return { c, diff: value("w") - value("b") };
}

function clockFor(colorName) {
  if (!S.hasClocks) return null;
  for (let i = Math.min(S.ply, S.result.moves.length) - 1; i >= 0; i--) {
    const m = S.result.moves[i];
    if (m.color === colorName && m.clock != null) return m.clock;
  }
  return S.baseTime;
}

function barHtml(colorName) {
  const pl = S.result.players[colorName];
  const p = pos();
  const mat = material(p.fen);
  const mine = colorName === "white" ? "w" : "b", theirs = colorName === "white" ? "b" : "w";
  const caps = ["p", "n", "b", "r", "q"].map((k) => {
    const n = Math.max(0, START_COUNT[k] - mat.c[theirs][k]);
    return n ? `<span class="grp">${`<i class="p-${theirs}${k.toUpperCase()}"></i>`.repeat(n)}</span>` : "";
  }).join("");
  const ahead = colorName === "white" ? mat.diff : -mat.diff;
  const clock = clockFor(colorName);
  const me = mySide(S.result) === colorName;
  return `<div class="who"><span class="avatar ${mine}"><i class="p-${mine}K"></i></span>
      <div class="id"><div class="nm"><span class="name">${esc(pl.name)}</span>${pl.rating ? `<span class="rating">(${esc(pl.rating)})</span>` : ""}${me ? `<span class="you">YOU</span>` : ""}</div>
      <div class="caps">${caps}${ahead > 0 ? `<b>+${ahead}</b>` : ""}</div></div></div>
    <div class="right"><span class="acc"><span class="l">Accuracy </span><b>${pl.accuracy ?? "–"}</b></span>
      ${clock != null ? `<span class="clock ${clock < 30 ? "low" : ""}">${fmtClock(clock)}</span>` : ""}</div>`;
}

function renderBars() {
  $("rv-top").innerHTML = barHtml(S.flipped ? "white" : "black");
  $("rv-bottom").innerHTML = barHtml(S.flipped ? "black" : "white");
}

function renderEvalBar() {
  const ev = pos().ev;
  const white = ev.win_white, whiteAhead = white >= 50;
  $("evalbar-white").style.height = `${white}%`;
  const val = $("evalbar-val");
  val.textContent = evalLabel(ev.text);
  // The bar is turned upside down when the board is flipped, so in its own frame White's part is always at the bottom.
  val.style.top = whiteAhead ? "auto" : "4px";
  val.style.bottom = whiteAhead ? "4px" : "auto";
  val.style.color = whiteAhead ? "#262421" : "#f4f4f2";
  $("evalbar").style.transform = $("evalbar-val").style.transform = S.flipped ? "rotate(180deg)" : "";
}

function renderCoach() {
  const p = pos(), m = p.move;
  let label = null, title = "", text = "", ev = "", line = "";
  if (S.retry && !p.inLine) {
    title = "Your turn";
    text = `${S.retry.san} was ${/^[aeiou]/i.test(LABELS[S.retry.label].name) ? "an" : "a"} ${LABELS[S.retry.label].name.toLowerCase()}. Can you find a better move? Play it on the board. Stuck? Press Best.`;
  } else if (!m) {
    title = "Starting position";
    text = "Use the arrow keys or the buttons below to step through the game, or drag a piece to try your own idea.";
    if (S.result.opening) line = `<div class="line">Opening: ${esc(S.result.opening.name)} (${esc(S.result.opening.eco)})</div>`;
  } else if (m.pending) {
    title = `${moveTitle(m)}`;
    text = `<span class="spinner"></span>The engine is checking your move…`;
    label = null;
  } else {
    label = m.label;
    title = `${moveTitle(m)} · ${LABELS[label].name}`;
    ev = m.eval_after.text;
    let lead = "";
    if (S.retry && p.inLine) {
      lead = m.retryResult === "ok" ? "<b>Correct!</b> That's a much better move. "
        : m.retryResult === "same" ? "<b>That's the move from the game.</b> Try something different. "
        : "<b>Not quite.</b> Try again, or press Best for a hint. ";
    }
    text = lead + esc(m.coach);
    if (m.best_line?.length && !NO_ARROW.has(label)) line = `<div class="line">Best line: ${esc(m.best_line.join(" "))}</div>`;
    if (!p.inLine && S.ply === S.result.moves.length) {
      const end = S.result.headers?.Termination || (S.result.result && S.result.result !== "*" ? `Result: ${S.result.result}` : "");
      if (end) line += `<div class="line">${esc(end)}</div>`;
    }
    if (p.inLine && m.status && m.status !== "ongoing") line += `<div class="line">${m.status === "checkmate" ? "Checkmate." : "The game is drawn."}</div>`;
  }
  const mascotColor = label ? color(label) : S.retry && !p.inLine ? "var(--great)" : "#7a8b9a";
  $("coach").innerHTML = `<div class="mascot" style="--mascot:${mascotColor}"><i class="p-wN"></i></div>
    <div class="bubble"><div class="top">${label ? badge(label, "lg") : ""}<span class="ttl">${esc(title)}</span>${ev ? `<span class="ev">${esc(ev)}</span>` : ""}</div>
    <p>${text}</p>${line}</div>`;
}

function renderActions() {
  const p = pos(), m = p.move;
  $("btn-retry").disabled = !(!exploring() && m && BAD_LABELS.has(m.label));
  const best = bestFor(p);
  $("btn-best").disabled = !best;
  $("btn-best").setAttribute("aria-pressed", S.showBest && !!best);
  $("btn-explain").setAttribute("aria-pressed", S.explain);
  const next = $("btn-next");
  const back = exploring();
  next.querySelector("span").textContent = back ? "Back to game" : "Next";
  next.disabled = !back && S.ply >= S.result.moves.length;
  $("x-undo").disabled = !exploring();
  $("x-reset").disabled = !exploring();
}

function renderExplain() {
  const box = $("explain");
  box.classList.toggle("hidden", !S.explain);
  if (!S.explain) return;
  const p = pos(), m = p.move;
  if (!m || m.pending) { box.innerHTML = `<p style="margin:0">${m ? "Waiting for the engine…" : "Pick a move to see how its evaluation changed."}</p>`; return; }
  const before = p.inLine ? m.eval_before : (S.ply > 1 ? S.result.moves[S.ply - 2].eval_after : S.result.start_eval);
  const loss = m.win_loss;
  const row = (a, b) => `<div class="row"><span>${a}</span><b>${b}</b></div>`;
  box.innerHTML =
    row("Your winning chance", `${m.win_before.toFixed(0)}% → ${m.win_after.toFixed(0)}%`) +
    row("Lost against the best move", loss < 0.5 ? "nothing" : `${loss.toFixed(1)}%`) +
    row("Evaluation", `${esc(before?.text ?? "–")} → ${esc(m.eval_after.text)}`) +
    row("Move accuracy", `${m.accuracy.toFixed(0)}%`) +
    (m.best_move && !NO_ARROW.has(m.label) ? row("Better was", `${figurine(m.best_move.san, m.color)}`) : "");
}

function renderMoves() {
  const moves = S.result.moves;
  let html = "";
  const cell = (m, i) => `<div class="mv ${!exploring() && S.ply === i + 1 ? "cur" : ""} ${exploring() && S.ply === i + 1 && S.li === 0 ? "cur" : ""}" data-ply="${i + 1}">${badge(m.label)}<span>${figurine(m.san, m.color)}</span></div>`;
  for (let i = 0; i < moves.length;) {
    const m = moves[i];
    if (m.color === "white") {
      const r = moves[i + 1];
      html += `<div class="mrow"><span class="num">${m.move_number}.</span>${cell(m, i)}${r ? cell(r, i + 1) : "<span></span>"}</div>`;
      i += r ? 2 : 1;
    } else {
      html += `<div class="mrow"><span class="num">${m.move_number}…</span><span></span>${cell(m, i)}</div>`;
      i += 1;
    }
  }
  if (S.line.length) {
    html += `<div class="line-box"><span class="tag">${S.retry ? "Your attempt" : "Your line"}</span>${S.line.map((m, i) =>
      `<div class="mv ${S.li === i + 1 ? "cur" : ""}" data-line="${i}">${m.pending ? '<span class="spinner" style="margin:0"></span>' : badge(m.label)}<span>${figurine(m.san, m.color)}</span></div>`).join("")}</div>`;
  }
  const box = $("moves");
  const keep = box.scrollTop;
  box.innerHTML = html;
  box.scrollTop = keep;
  const cur = box.querySelector(".mv.cur");
  if (cur) {
    const b = box.getBoundingClientRect(), c = cur.getBoundingClientRect();
    if (c.top < b.top) box.scrollTop -= b.top - c.top + 6;
    else if (c.bottom > b.bottom) box.scrollTop += c.bottom - b.bottom + 6;
  }
}

// evaluation graph: the white area is White's winning chance after each move
const GW = 400, GH = 92;
const gx = (i) => (i / Math.max(1, S.result.moves.length)) * GW;
const gy = (win) => GH - (win / 100) * GH;
function renderGraph() {
  const r = S.result;
  const wins = [r.start_eval.win_white, ...r.moves.map((m) => m.eval_after.win_white)];
  const pts = wins.map((w, i) => `${gx(i).toFixed(1)},${gy(w).toFixed(1)}`).join(" ");
  let svg = `<rect class="gbg" width="${GW}" height="${GH}"/><polygon class="gfill" points="0,${GH} ${pts} ${GW},${GH}"/>
    <line x1="0" y1="${GH / 2}" x2="${GW}" y2="${GH / 2}" stroke="#8a93a0" stroke-width=".6" stroke-dasharray="3 3"/>
    <line id="g-cursor" x1="0" y1="0" x2="0" y2="${GH}" stroke="#81b64c" stroke-width="2"/>`;
  r.moves.forEach((m, i) => {
    if (KEY_LABELS.has(m.label)) svg += `<circle cx="${gx(i + 1).toFixed(1)}" cy="${gy(m.eval_after.win_white).toFixed(1)}" r="3.4" fill="${color(m.label)}" stroke="#fff" stroke-width=".8"><title>${esc(moveTitle(m))} · ${LABELS[m.label].name}</title></circle>`;
  });
  $("graph").innerHTML = svg;
}
function renderGraphCursor() {
  const c = $("g-cursor");
  if (c) { c.setAttribute("x1", gx(S.ply)); c.setAttribute("x2", gx(S.ply)); }
}

// ------------------------------------------------------------------ engine lines
function renderLinesPanel() {
  $("elines-note").classList.toggle("hidden", S.linesOn);
  if (!S.linesOn) $("elines").innerHTML = "";
}
const fetchLines = debounce(async () => {
  if (!S.result || !S.linesOn || S.tab !== "engine") return;
  const fen = pos().fen;
  S.linesAbort?.abort();
  const ctrl = (S.linesAbort = new AbortController());
  $("elines").innerHTML = `<div class="note"><span class="spinner"></span>Thinking…</div>`;
  try {
    const data = await api.lines(fen, 3, liveQuality(), ctrl.signal);
    if (ctrl.signal.aborted || fen !== pos().fen) return;
    if (!data.lines.length) { $("elines").innerHTML = `<div class="note">${data.status === "checkmate" ? "Checkmate. The game is over." : "The game is drawn."}</div>`; return; }
    $("elines").innerHTML = data.lines.map((l) => {
      const neg = l.eval.mate != null ? l.eval.mate < 0 : (l.eval.cp ?? 0) < 0;
      const turn = turnOf(fen), n0 = fullmoveOf(fen);
      const pv = l.pv.map((san, i) => {
        const whiteMove = (turn === "w") === (i % 2 === 0);
        const num = whiteMove ? `${n0 + Math.floor((i + (turn === "w" ? 0 : 1)) / 2)}. ` : (i === 0 ? `${n0}… ` : "");
        return `${num}${i === 0 ? `<b>${esc(san)}</b>` : esc(san)}`;
      }).join(" ");
      return `<button class="eline" data-uci="${l.uci}"><span class="sc ${neg ? "neg" : ""}">${esc(l.eval.text)}</span><span class="pv">${pv}</span></button>`;
    }).join("");
  } catch (e) {
    if (e.name === "AbortError") return;
    $("elines").innerHTML = `<div class="note">${esc(e.message)}</div>`;
  }
}, 300);

// ------------------------------------------------------------------ summary tab
function phaseOf(result) {
  const moves = result.moves;
  const lastBook = moves.reduce((a, m, i) => (m.label === "book" ? i + 1 : a), 0);
  const openingEnd = Math.max(lastBook, 10);
  let endgameStart = moves.length + 1;
  for (let i = 0; i < moves.length; i++) {
    const { c } = material(moves[i].fen_after);
    const heavy = (s) => c[s].n * 3 + c[s].b * 3 + c[s].r * 5 + c[s].q * 9;
    if (heavy("w") <= 13 && heavy("b") <= 13) { endgameStart = i + 1; break; }
  }
  endgameStart = Math.max(endgameStart, openingEnd + 1);
  return (ply) => (ply <= openingEnd ? "Opening" : ply >= endgameStart ? "Endgame" : "Middlegame");
}

function renderSummary() {
  const r = S.result, w = r.players.white, b = r.players.black, me = mySide(r);
  const phase = phaseOf(r);
  const acc = { white: {}, black: {} };
  r.moves.forEach((m, i) => { const ph = phase(i + 1); (acc[m.color][ph] ||= []).push(m.accuracy); });
  const avg = (arr) => (arr && arr.length ? (arr.reduce((s, x) => s + x, 0) / arr.length).toFixed(0) : "–");
  const keyRows = r.moves.map((m, i) => ({ m, ply: i + 1 })).filter(({ m }) => KEY_LABELS.has(m.label));

  $("tab-summary").innerHTML = `
    <div class="tiles">
      <div class="tile w ${me === "white" ? "me" : ""}"><span>${esc(w.name)}</span><b>${w.accuracy ?? "–"}</b><small>accuracy</small></div>
      <div class="tile b ${me === "black" ? "me" : ""}"><span>${esc(b.name)}</span><b>${b.accuracy ?? "–"}</b><small>accuracy</small></div>
    </div>
    ${r.opening ? `<p class="note" style="margin:0 0 4px"><b>${esc(r.opening.name)}</b> · ${esc(r.opening.eco)}</p>` : ""}
    ${r.engine ? `<p class="note" style="margin:0">Analysed by ${esc(r.engine)}${r.quality ? ` · ${esc({ fast: "Fast", standard: "Standard", deep: "Deep", max: "Maximum" }[r.quality] || r.quality)} depth` : ""}</p>` : ""}
    ${w.estimated_rating || b.estimated_rating ? `<div class="sec-title">Estimated game rating</div><table class="tbl"><tr><td class="n">${w.estimated_rating ?? "–"}</td><td class="n">${b.estimated_rating ?? "–"}</td></tr></table>` : ""}
    <div class="sec-title">By phase (average move accuracy)</div>
    <div class="phase"><span></span><span class="pill" style="background:#f1f1ef;color:#302e2b">White</span><span class="pill" style="background:#1f1e1c;color:#f1f1ef">Black</span>
      ${["Opening", "Middlegame", "Endgame"].map((ph) => `<b>${ph}</b><span class="pill">${avg(acc.white[ph])}</span><span class="pill">${avg(acc.black[ph])}</span>`).join("")}</div>
    <div class="sec-title">Move quality</div>
    <table class="tbl"><tr><th></th><th>${esc(w.name)}</th><th>${esc(b.name)}</th></tr>
      ${SUMMARY_ORDER.map((k) => `<tr><td><span class="lab">${badge(k)}${LABELS[k].name}</span></td>
        <td class="n ${w.counts[k] ? "" : "zero"}" style="${w.counts[k] ? `color:${color(k)}` : ""}">${w.counts[k]}</td>
        <td class="n ${b.counts[k] ? "" : "zero"}" style="${b.counts[k] ? `color:${color(k)}` : ""}">${b.counts[k]}</td></tr>`).join("")}</table>
    <div class="sec-title">Key moments</div>
    <div class="moments">${keyRows.length ? keyRows.map(({ m, ply }) =>
      `<button class="moment" data-ply="${ply}">${badge(m.label)}<span class="t">${esc(moveTitle(m))} <i>${LABELS[m.label].name}</i></span><span class="e">${esc(m.eval_after.text)}</span></button>`).join("")
      : `<p class="note">No brilliant moves, mistakes or blunders. A clean game!</p>`}</div>
    <div class="sec-title">Keep this game</div>
    <div class="btn-row">
      <button class="btn" data-act="copy-pgn"><svg class="icon"><use href="#i-copy"/></svg>Copy PGN</button>
      <button class="btn" data-act="download-pgn"><svg class="icon"><use href="#i-download"/></svg>Download PGN</button>
      <button class="btn" data-act="copy-link"><svg class="icon"><use href="#i-link"/></svg>Copy link</button>
    </div>`;
}

// ------------------------------------------------------------------ PGN export (with the labels as annotations)
const NAG = { brilliant: "$3", great: "$1", inaccuracy: "$6", mistake: "$2", miss: "$2", blunder: "$4" };
function buildPgn() {
  const r = S.result, h = { ...(r.headers || {}) };
  const keys = ["Event", "Site", "Date", "Round", "White", "Black", "Result", "WhiteElo", "BlackElo", "TimeControl", "ECO", "Termination"];
  const lines = keys.filter((k) => h[k]).map((k) => `[${k} "${String(h[k]).replace(/"/g, '\\"')}"]`);
  if (!h.Event) lines.unshift('[Event "MoveLens review"]');
  if (r.start_fen && !r.start_fen.startsWith("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq")) lines.push('[SetUp "1"]', `[FEN "${r.start_fen}"]`);
  lines.push('[Annotator "MoveLens"]');
  const tokens = [];
  r.moves.forEach((m, i) => {
    if (m.color === "white") tokens.push(`${m.move_number}.`);
    else if (i === 0) tokens.push(`${m.move_number}...`);
    tokens.push(m.san);
    if (NAG[m.label]) tokens.push(NAG[m.label]);
    if (BAD_LABELS.has(m.label) && m.best_move) tokens.push(`{ ${LABELS[m.label].name}. Better was ${m.best_move.san}. }`);
    if (BAD_LABELS.has(m.label) && m.color === "white" && r.moves[i + 1]) tokens.push(`${m.move_number}...`);
  });
  tokens.push(r.result && r.result !== "*" ? r.result : "*");
  let out = "", row = "";
  for (const t of tokens) { if ((row + " " + t).length > 80) { out += row + "\n"; row = t; } else row = row ? row + " " + t : t; }
  return lines.join("\n") + "\n\n" + out + row + "\n";
}

// ------------------------------------------------------------------ keyboard
function onKey(e) {
  if (!isOpen() || e.metaKey || e.ctrlKey || e.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName) || !$("keys-modal").classList.contains("hidden")) return;
  const k = e.key;
  const act = {
    ArrowLeft: stepPrev, ArrowRight: stepNext, Home: () => goPly(0), End: () => goPly(S.result.moves.length),
    " ": toggleAuto, f: flip, F: flip, e: () => $("btn-explain").click(), E: () => $("btn-explain").click(),
    b: () => !$("btn-best").disabled && $("btn-best").click(), B: () => !$("btn-best").disabled && $("btn-best").click(),
    r: startRetry, R: startRetry, x: () => exploring() && backToGame(), X: () => exploring() && backToGame(),
    Escape: () => { if (exploring()) backToGame(); }, "]": () => jumpKey(1), "[": () => jumpKey(-1),
    "1": () => setTab("review"), "2": () => setTab("summary"), "3": () => setTab("engine"),
    s: () => setPref("sound", !prefs.sound), S: () => setPref("sound", !prefs.sound),
  }[k];
  if (act) { e.preventDefault(); act(); }
}
