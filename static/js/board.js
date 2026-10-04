// The chess board: drawing, drag-and-drop / click-to-move, promotion picker, and right-click arrows.
// It knows nothing about reviews. The caller gives it a FEN and hears about moves through `hooks`:
//   hooks.getLegal(fen) -> Promise<{ turn, check, status, moves: [{uci, san, fen, capture}] }>
//   hooks.onMove(move)  -> called with the chosen legal-move entry
import { FILES, badge } from "./util.js";

export function parseFen(fen) {
  const [placement, turn = "w"] = fen.split(" ");
  const grid = {};
  placement.split("/").forEach((row, i) => {
    let f = 0;
    for (const ch of row) {
      if (/\d/.test(ch)) f += +ch;
      else { grid[FILES[f] + (8 - i)] = ch; f++; }
    }
  });
  return { grid, turn };
}

const ARROW = { green: "#81b64c", red: "#e5534b", blue: "#4a90e2", best: "#6bbf2a" };

export function createBoard(root, hooks = {}) {
  const s = {
    fen: "", grid: {}, turn: "w", flipped: false, last: null, arrows: [], interactive: false,
    legal: null, byFrom: new Map(), check: null, selected: null, drag: null,
    marks: { arrows: [], squares: new Set() }, drawing: null, promo: null, overlay: null,
  };

  // ---------------------------------------------------------------- geometry
  const colRow = (sq) => {
    const f = FILES.indexOf(sq[0]), r = +sq[1] - 1;
    return [s.flipped ? 7 - f : f, s.flipped ? r : 7 - r];
  };
  const center = (sq) => { const [c, r] = colRow(sq); return [c + 0.5, r + 0.5]; };
  function sqAt(e) {
    const b = root.getBoundingClientRect();
    const c = Math.floor(((e.clientX - b.left) / b.width) * 8), r = Math.floor(((e.clientY - b.top) / b.height) * 8);
    if (c < 0 || c > 7 || r < 0 || r > 7) return null;
    return FILES[s.flipped ? 7 - c : c] + (s.flipped ? r + 1 : 8 - r);
  }
  const squareEl = (sq) => root.querySelector(`[data-sq="${sq}"]`);

  // ---------------------------------------------------------------- legal moves
  const targetsOf = (from) => s.byFrom.get(from) || [];
  function ensureLegal() {
    const fen = s.fen;
    s.legal = null; s.byFrom = new Map(); s.check = null;
    if (!s.interactive || !hooks.getLegal) return;
    hooks.getLegal(fen).then((data) => {
      if (fen !== s.fen) return;
      s.legal = data;
      for (const m of data.moves) {
        const from = m.uci.slice(0, 2);
        if (!s.byFrom.has(from)) s.byFrom.set(from, []);
        s.byFrom.get(from).push({ ...m, to: m.uci.slice(2, 4), promo: m.uci[4] || null });
      }
      if (data.check) {
        const king = Object.keys(s.grid).find((q) => s.grid[q] === (data.turn === "w" ? "K" : "k"));
        if (king) { s.check = king; squareEl(king)?.classList.add("check"); }
      }
    }).catch(() => {});
  }

  // ---------------------------------------------------------------- drawing
  function arrowPolygon(from, to, fill, opacity = 0.85) {
    const [x1, y1] = center(from), [x2, y2] = center(to);
    const len = Math.hypot(x2 - x1, y2 - y1);
    if (!len) return "";
    const ux = (x2 - x1) / len, uy = (y2 - y1) / len, head = 0.4, w = 0.12, hw = 0.29;
    const ex = x2 - ux * 0.16, ey = y2 - uy * 0.16, bx = ex - ux * head, by = ey - uy * head, px = -uy, py = ux;
    const pts = [[x1 + px * w, y1 + py * w], [bx + px * w, by + py * w], [bx + px * hw, by + py * hw], [ex, ey],
      [bx - px * hw, by - py * hw], [bx - px * w, by - py * w], [x1 - px * w, y1 - py * w]]
      .map((p) => p.map((v) => v.toFixed(3)).join(",")).join(" ");
    return `<polygon points="${pts}" fill="${fill}" opacity="${opacity}"/>`;
  }
  function drawOverlay() {
    if (!s.overlay) return;
    s.overlay.innerHTML = [...s.arrows.map((a) => arrowPolygon(a.from, a.to, ARROW[a.color] || ARROW.best, 0.9)),
      ...s.marks.arrows.map((a) => arrowPolygon(a.from, a.to, ARROW[a.color], 0.8))].join("");
  }

  function draw() {
    const targets = s.selected ? new Map(targetsOf(s.selected).map((m) => [m.to, m])) : new Map();
    let html = "";
    for (let row = 0; row < 8; row++) {
      for (let col = 0; col < 8; col++) {
        const f = s.flipped ? 7 - col : col, r = s.flipped ? row : 7 - row;
        const sq = FILES[f] + (r + 1);
        let cls = "sq " + ((f + r) % 2 ? "light" : "dark");
        if (s.selected === sq) cls += " sel";
        if (s.check === sq) cls += " check";
        if (s.marks.squares.has(sq)) cls += " user-hl";
        const t = targets.get(sq);
        if (t) cls += t.capture ? " legal cap" : " legal";
        let inner = "";
        if (s.last && (s.last.from === sq || s.last.to === sq)) {
          inner += `<div class="hl" style="background:${s.last.label ? `var(--${s.last.label})` : "#f5e642"}"></div>`;
        }
        if (row === 7) inner += `<span class="coord f">${FILES[f]}</span>`;
        if (col === 0) inner += `<span class="coord r">${r + 1}</span>`;
        const p = s.grid[sq];
        if (p) inner += `<div class="piece p-${p === p.toUpperCase() ? "w" : "b"}${p.toUpperCase()}"></div>`;
        if (s.last && s.last.label && s.last.to === sq) inner += badge(s.last.label);
        html += `<div class="${cls}" data-sq="${sq}">${inner}</div>`;
      }
    }
    root.innerHTML = html + `<svg class="overlay" viewBox="0 0 8 8"></svg>`;
    s.overlay = root.querySelector("svg.overlay");
    s.promo = null;
    drawOverlay();
  }

  // ---------------------------------------------------------------- selecting and moving
  function select(sq) { s.selected = sq; draw(); }
  function deselect() { if (s.selected) { s.selected = null; draw(); } }
  function clearMarks() {
    if (!s.marks.arrows.length && !s.marks.squares.size) return;
    s.marks = { arrows: [], squares: new Set() };
    root.querySelectorAll(".user-hl").forEach((el) => el.classList.remove("user-hl"));
    drawOverlay();
  }
  function closePromo() { if (s.promo) { s.promo.remove(); s.promo = null; } }
  function commit(move) { s.selected = null; closePromo(); hooks.onMove?.(move); }

  function attempt(from, to, moves) {
    if (moves.length === 1) return commit(moves[0]);
    showPromo(from, to, moves);                              // four moves with the same squares: a promotion
  }
  function showPromo(from, to, moves) {
    closePromo();
    const white = s.grid[from] === "P";
    const [col, row] = colRow(to);
    const el = document.createElement("div");
    el.className = "promo" + (row === 0 ? "" : " up");
    el.style.left = `${col * 12.5}%`;
    el.style[row === 0 ? "top" : "bottom"] = "0";
    for (const p of ["q", "n", "r", "b"]) {
      const move = moves.find((m) => m.promo === p);
      if (!move) continue;
      const b = document.createElement("button");
      b.className = `p-${white ? "w" : "b"}${p.toUpperCase()}`;
      b.title = { q: "Queen", n: "Knight", r: "Rook", b: "Bishop" }[p];
      b.addEventListener("click", (ev) => { ev.stopPropagation(); commit(move); });
      el.appendChild(b);
    }
    root.appendChild(el);
    s.promo = el;
  }

  // ---------------------------------------------------------------- pointer input
  const arrowColor = (e) => (e.shiftKey ? "red" : e.altKey ? "blue" : "green");

  root.addEventListener("contextmenu", (e) => e.preventDefault());
  root.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".promo")) return;
    const sq = sqAt(e);
    if (e.button === 2) { if (sq) s.drawing = { from: sq, color: arrowColor(e) }; return; }
    if (e.button !== 0) return;
    clearMarks();
    if (!s.interactive || !sq) return;
    closePromo();
    if (s.selected && s.selected !== sq) {
      const hit = targetsOf(s.selected).filter((m) => m.to === sq);
      if (hit.length) return attempt(s.selected, sq, hit);
    }
    const piece = s.grid[sq];
    if (piece && targetsOf(sq).length) {
      select(sq);
      s.drag = { sq, x: e.clientX, y: e.clientY, moved: false, ghost: null, piece };
      try { root.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
    } else {
      deselect();
    }
  });

  root.addEventListener("pointermove", (e) => {
    const d = s.drag;
    if (!d) return;
    if (!d.moved) {
      if (Math.hypot(e.clientX - d.x, e.clientY - d.y) < 5) return;
      d.moved = true;
      const size = root.getBoundingClientRect().width / 8;
      d.ghost = document.createElement("div");
      d.ghost.className = `ghost p-${d.piece === d.piece.toUpperCase() ? "w" : "b"}${d.piece.toUpperCase()}`;
      d.ghost.style.width = d.ghost.style.height = `${size}px`;
      root.appendChild(d.ghost);
      squareEl(d.sq)?.querySelector(".piece")?.classList.add("lifted");
    }
    const b = root.getBoundingClientRect(), size = b.width / 8;
    d.ghost.style.left = `${e.clientX - b.left - size / 2}px`;
    d.ghost.style.top = `${e.clientY - b.top - size / 2}px`;
    const over = sqAt(e);
    if (over !== d.over) {
      if (d.over) squareEl(d.over)?.classList.remove("over");
      if (over) squareEl(over)?.classList.add("over");
      d.over = over;
    }
  });

  function endPointer(e) {
    if (s.drawing && e.button === 2) {                       // finish a right-click arrow / highlight
      const { from, color } = s.drawing, to = sqAt(e);
      s.drawing = null;
      if (!to) return;
      if (to === from) {
        const on = !s.marks.squares.has(from);
        on ? s.marks.squares.add(from) : s.marks.squares.delete(from);
        squareEl(from)?.classList.toggle("user-hl", on);
      } else {
        const i = s.marks.arrows.findIndex((a) => a.from === from && a.to === to);
        if (i >= 0) s.marks.arrows.splice(i, 1); else s.marks.arrows.push({ from, to, color });
        drawOverlay();
      }
      return;
    }
    const d = s.drag;
    if (!d) return;
    s.drag = null;
    d.ghost?.remove();
    if (d.over) squareEl(d.over)?.classList.remove("over");
    squareEl(d.sq)?.querySelector(".piece")?.classList.remove("lifted");
    if (!d.moved) return;                                    // it was a click: the piece stays selected
    const to = sqAt(e);
    if (!to || to === d.sq) return;
    const hit = targetsOf(d.sq).filter((m) => m.to === to);
    if (hit.length) attempt(d.sq, to, hit);
  }
  root.addEventListener("pointerup", endPointer);
  root.addEventListener("pointercancel", (e) => { s.drawing = null; endPointer({ ...e, button: -1, clientX: -1, clientY: -1 }); });

  // ---------------------------------------------------------------- public
  return {
    /** Show a position. opts: { fen, flipped, last: {from, to, label}, arrows: [{from, to, color}], interactive } */
    render(opts) {
      const positionChanged = opts.fen !== s.fen;
      s.fen = opts.fen;
      const parsed = parseFen(opts.fen);
      s.grid = parsed.grid; s.turn = parsed.turn;
      s.flipped = !!opts.flipped;
      s.last = opts.last || null;
      s.arrows = opts.arrows || [];
      s.interactive = !!opts.interactive;
      if (positionChanged) { s.selected = null; s.marks = { arrows: [], squares: new Set() }; }
      s.drag = null;
      draw();
      if (positionChanged || !s.legal) ensureLegal(); else if (s.check) squareEl(s.check)?.classList.add("check");
    },
    clearMarks,
    get flipped() { return s.flipped; },
  };
}
