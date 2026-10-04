// Shared constants and small helpers.
export const $ = (id) => document.getElementById(id);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
export const FILES = "abcdefgh";

// Move labels. `rule` is the plain-English threshold shown on the front page.
export const LABELS = {
  brilliant:  { sym: "!!", name: "Brilliant",  blurb: "A good sacrifice. You give up material, and it is still the best or nearly the best move.", rule: "Best move + gives up 2+ pawns of material" },
  great:      { sym: "!",  name: "Great",      blurb: "The only move that keeps your position healthy. Every alternative is much worse.", rule: "All other moves lose 10%+" },
  best:       { sym: "★",  name: "Best",       blurb: "The engine's top choice in the position.", rule: "Matches the engine's first choice" },
  excellent:  { sym: "✓",  name: "Excellent",  blurb: "Almost as good as the best move. Nothing worth worrying about.", rule: "Loses under 2% winning chance" },
  good:       { sym: "•",  name: "Good",       blurb: "A solid, sensible move that gives up a little.", rule: "Loses under 5%" },
  book:       { sym: "≡",  name: "Book",       blurb: "A known opening move from theory.", rule: "Position is in the opening list" },
  forced:     { sym: "□",  name: "Forced",     blurb: "The only legal move, so there was no choice to make.", rule: "One legal move" },
  inaccuracy: { sym: "?!", name: "Inaccuracy", blurb: "Not terrible, but a better move was available.", rule: "Loses 5–10%" },
  mistake:    { sym: "?",  name: "Mistake",    blurb: "A clear error that hands your opponent a real advantage.", rule: "Loses 10–20%" },
  miss:       { sym: "✕",  name: "Miss",       blurb: "Your opponent slipped and you let the chance go by.", rule: "After an opponent error, loses 10%+" },
  blunder:    { sym: "??", name: "Blunder",    blurb: "A serious error that can lose the game or a lot of material.", rule: "Loses 20% or more" },
};
export const LABEL_ORDER = Object.keys(LABELS);
export const SUMMARY_ORDER = ["brilliant", "great", "best", "excellent", "good", "book", "inaccuracy", "mistake", "miss", "blunder"];
export const GOOD_LABELS = new Set(["brilliant", "great", "best", "excellent", "good", "book", "forced"]);
export const BAD_LABELS = new Set(["inaccuracy", "mistake", "miss", "blunder"]);
export const KEY_LABELS = new Set(["brilliant", "great", "mistake", "miss", "blunder"]);
export const NO_ARROW = new Set(["best", "brilliant", "great", "book", "forced"]);

export const BOARDS = {
  sky:        { name: "Sky",        light: "#f2f5f7", dark: "#b7d0e3" },
  green:      { name: "Green",      light: "#ebecd0", dark: "#739552" },
  brown:      { name: "Brown",      light: "#f0d9b5", dark: "#b58863" },
  walnut:     { name: "Walnut",     light: "#dcbd94", dark: "#8a5a35" },
  blue:       { name: "Blue",       light: "#dee3e6", dark: "#8ca2ad" },
  icy:        { name: "Icy Sea",    light: "#e6eef3", dark: "#6f9fc0" },
  purple:     { name: "Purple",     light: "#f0eef4", dark: "#8476ba" },
  red:        { name: "Red",        light: "#f2e3de", dark: "#c0675a" },
  gray:       { name: "Gray",       light: "#dcdcdc", dark: "#8b8b8b" },
  sand:       { name: "Sand",       light: "#f3e8cf", dark: "#cfa66c" },
  midnight:   { name: "Midnight",   light: "#8c9ab0", dark: "#4a5568" },
  tournament: { name: "Tournament", light: "#f7f7f5", dark: "#3f7a4e" },
};
export const SCENES = {
  sky:    { name: "Sky",    thumb: "url(/static/bg/sky.jpg)" },
  meadow: { name: "Meadow", thumb: "url(/static/bg/meadow.jpg)" },
  dusk:   { name: "Dusk",   thumb: "url(/static/bg/dusk.jpg)" },
  night:  { name: "Night",  thumb: "url(/static/bg/night.jpg)" },
  slate:  { name: "Slate",  thumb: "linear-gradient(#302e2b,#262421)" },
  paper:  { name: "Paper",  thumb: "linear-gradient(#ffffff,#ebeae6)" },
};
export const PIECE_SETS = { cburnett: "Classic", merida: "Merida", chessnut: "Chessnut", fantasy: "Fantasy", celtic: "Celtic", spatial: "Spatial" };
export const PIECE_KEYS = ["wK", "wQ", "wR", "wB", "wN", "wP", "bK", "bQ", "bR", "bB", "bN", "bP"];
export const pieceUrl = (set, key) => `/static/pieces/${set}/${key}.svg`;

export const color = (label) => `var(--${label})`;
export const badge = (label, cls = "") =>
  `<span class="badge ${cls}" style="background:${color(label)}" title="${LABELS[label].name}">${LABELS[label].sym}</span>`;

export function fmtClock(seconds) {
  if (seconds == null) return "";
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}` : `${m}:${String(r).padStart(2, "0")}`;
}

export function timeAgo(ts) {
  const diff = Math.max(0, Date.now() / 1000 - ts);
  if (diff < 90) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`;
  if (diff < 86400 * 30) return `${Math.round(diff / 86400)} d ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

let toastTimer = null;
export function toast(message, ms = 2600) {
  const el = $("toast");
  el.textContent = message;
  el.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), ms);
}

export async function copyText(text, okMessage = "Copied to the clipboard") {
  try { await navigator.clipboard.writeText(text); toast(okMessage); }
  catch (e) {
    const ta = document.createElement("textarea");           // older browsers / insecure origins
    ta.value = text; document.body.appendChild(ta); ta.select();
    try { document.execCommand("copy"); toast(okMessage); } catch (err) { toast("Could not copy. Select the text and copy it yourself."); }
    ta.remove();
  }
}

export function download(filename, text, type = "application/x-chess-pgn") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

export const SHORTCUTS = [
  [["←", "→"], "Previous / next move"],
  [["Home", "End"], "Jump to the start / end"],
  [["Space"], "Auto-play the game"],
  [["F"], "Flip the board"],
  [["E"], "Explain the move"],
  [["B"], "Show the best move"],
  [["R"], "Retry a mistake"],
  [["X", "Esc"], "Back to the game from a side line"],
  [["[", "]"], "Previous / next key moment"],
  [["1", "2", "3"], "Review / Summary / Engine tab"],
  [["S"], "Sound on or off"],
  [["?"], "Show these shortcuts"],
  [["Right-drag"], "Draw an arrow (Shift: red, Alt: blue)"],
  [["Right-click"], "Highlight a square"],
];
