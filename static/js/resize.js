// The handle at the board's bottom-right corner. Drag it (mouse or finger) to make the board smaller or bigger, up to
// the largest size that fits the screen; arrow keys work too. Double-click it, or press Home, to fit the screen again.
// The size is saved as a share of "what fits", so it suits every screen the page is opened on.
import { $ } from "./util.js";
import { prefs, setPref, MIN_BOARD_SCALE } from "./prefs.js";

const clamp = (s) => Math.min(1, Math.max(MIN_BOARD_SCALE, s));
const live = (s) => document.documentElement.style.setProperty("--board-scale", s);
const save = (s) => setPref("boardScale", Math.round(clamp(s) * 1000) / 1000);

export function initResize() {
  const handle = $("board-resize"), board = $("board"), probe = $("fit-probe");
  const fit = () => probe.getBoundingClientRect().width || board.getBoundingClientRect().width;   // largest size that fits

  handle.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    handle.setPointerCapture(e.pointerId);
    handle.classList.add("dragging");
    const x0 = e.clientX, y0 = e.clientY, size0 = board.getBoundingClientRect().width, f = fit();
    let scale = prefs.boardScale;
    // The layout is centred, so when the board grows by d its corner moves d/2 sideways and d down.
    // Follow the pointer along that line: the corner stays as close to your finger as it can.
    const move = (ev) => {
      const grow = (0.5 * (ev.clientX - x0) + (ev.clientY - y0)) / 1.25;
      scale = clamp((size0 + grow) / f);
      live(scale);
    };
    const end = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", end);
      handle.removeEventListener("pointercancel", end);
      handle.classList.remove("dragging");
      save(scale);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
  });

  handle.addEventListener("dblclick", () => save(1));
  handle.addEventListener("keydown", (e) => {
    const step = { ArrowUp: 0.05, ArrowRight: 0.05, ArrowDown: -0.05, ArrowLeft: -0.05 }[e.key];
    if (step) save(prefs.boardScale + step);
    else if (e.key === "Home") save(1);
    else if (e.key === "End") save(MIN_BOARD_SCALE);
    else return;
    e.preventDefault();
    e.stopPropagation();                                     // don't also step through the game
  });
}
