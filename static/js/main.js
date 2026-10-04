// Entry point: themes, navigation, starting a review, and opening one from the address bar.
import { $, sleep, toast } from "./util.js";
import { api } from "./api.js";
import { prefs, setPref, applyPrefs, mountThemePicker } from "./prefs.js";
import { saveReview, loadReview, loadSession, migrateLegacy } from "./history.js";
import * as store from "./store.js";
import { initReview, openReview, closeReview, isOpen } from "./review.js";
import { initLanding, setBusy, setProgress, showError, renderRecent, applyServerLimits } from "./landing.js";

// ------------------------------------------------------------------ themes
mountThemePicker($("theme-pop"));
mountThemePicker($("themes-mount"));
applyPrefs();

function setPopover(open) {
  $("theme-pop").classList.toggle("hidden", !open);
  $("theme-btn").setAttribute("aria-expanded", open);
}
$("theme-btn").onclick = (e) => { e.stopPropagation(); setPopover($("theme-pop").classList.contains("hidden")); };
document.addEventListener("click", (e) => { if (!e.target.closest("#theme-pop") && !e.target.closest("#theme-btn")) setPopover(false); });
$("sound-btn").onclick = () => setPref("sound", !prefs.sound);

const keysModal = $("keys-modal");
const setKeys = (open) => keysModal.classList.toggle("hidden", !open);
$("keys-btn").onclick = () => setKeys(true);
$("keys-close").onclick = () => setKeys(false);
keysModal.onclick = (e) => { if (e.target === keysModal) setKeys(false); };
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") { setPopover(false); setKeys(false); }
  if (e.key === "?" && !/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) setKeys(true);
});

// ------------------------------------------------------------------ views
function showLanding() {
  closeReview();
  $("landing").classList.remove("hidden");
  $("review-view").classList.add("hidden");
  $("main").classList.remove("reviewing");
  document.body.classList.remove("reviewing");
  $("new-btn").classList.add("hidden");
  history.replaceState(null, "", location.pathname + location.search);
  renderRecent();
  window.scrollTo(0, 0);
}
function showReview() {
  $("landing").classList.add("hidden");
  $("review-view").classList.remove("hidden");
  $("main").classList.add("reviewing");
  document.body.classList.add("reviewing");
  $("new-btn").classList.remove("hidden");
  window.scrollTo(0, 0);
}
$("new-btn").onclick = showLanding;
$("brand").onclick = (e) => { if (isOpen()) { e.preventDefault(); showLanding(); } };
$("nav-links").onclick = (e) => { if (isOpen() && e.target.closest("a")) { const href = e.target.closest("a").getAttribute("href"); showLanding(); setTimeout(() => document.querySelector(href)?.scrollIntoView(), 30); e.preventDefault(); } };

async function open(result, id, ply = null) {
  const session = await loadSession(id);            // where you were last time: side lines, retry, tab, board side
  showReview();
  openReview(result, { id, ply, session });
}

// ------------------------------------------------------------------ reviewing a game
async function startReview({ pgn, quality }) {
  showError("");
  setBusy(true);
  setProgress(0, 1, "Sending your game…");
  const slow = setTimeout(() => setProgress(0, 1, "The server is waking up. A free host sleeps when it is idle, so this can take about a minute…"), 4000);
  try {
    const job = await api.createReview(pgn, quality).finally(() => clearTimeout(slow));
    history.replaceState(null, "", `${location.pathname}${location.search}#r=${job.id}`);
    await waitFor(job.id);
  } catch (e) {
    showError(e.message);
    setBusy(false);
    history.replaceState(null, "", location.pathname + location.search);
  }
}

async function waitFor(id, ply = null) {
  for (;;) {
    const job = await api.getReview(id);
    if (job.status === "done") {
      await saveReview(id, job.result);
      store.persist();                                   // ask the browser to keep our data when space is short
      setBusy(false);
      await open(job.result, id, ply);
      return;
    }
    if (job.status === "error") throw new Error(job.error);
    const { done, total } = job.progress;
    setBusy(true);
    const waiting = job.ahead > 0 ? `Waiting for the engine… ${job.ahead} review${job.ahead === 1 ? "" : "s"} ahead of yours.` : "Waiting for the engine… you're next.";
    setProgress(done, total, job.status === "queued" ? waiting : `Analysing position ${done} of ${total}…`);
    await sleep(700);
  }
}

async function openSample(ply = null) {
  try { await open(await api.sample(), "sample", ply); }
  catch (e) { toast("Could not load the sample game."); }
}

async function openHistory(id) {
  const saved = await loadReview(id);
  if (saved) await open(saved, id);
  else { toast("That review is no longer stored in this browser."); renderRecent(); }
}

initReview({ onBack: showLanding });
initLanding({ onReview: startReview, onSample: () => openSample(), onOpenHistory: openHistory });

// ------------------------------------------------------------------ server facts, and "the free host is waking up"
async function watchServer() {
  const wake = $("wake");
  const showWake = setTimeout(() => wake.classList.remove("hidden"), 2500);        // no answer yet: say why
  for (let attempt = 0; attempt < 80; attempt++) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 6000);
    try {
      const h = await api.health(ctrl.signal);
      if (h.engine_name) $("engine-credit").textContent = h.engine_name;
      if (h.max_quality) applyServerLimits(h.max_quality);
      clearTimeout(showWake); wake.classList.add("hidden");
      return;
    } catch (e) { /* asleep or starting: try again */ } finally { clearTimeout(timer); }
    await sleep(3000);
  }
}
watchServer();

// ------------------------------------------------------------------ open a review from the address (#r=<id>&ply=<n>)
async function route() {
  const m = location.hash.match(/^#r=([\w-]+)(?:&ply=(\d+))?/);
  if (!m) { if (isOpen()) showLanding(); return; }
  const [, id, plyText] = m, ply = plyText ? +plyText : null;
  if (id === "sample") return openSample(ply);
  const saved = await loadReview(id);
  if (saved) return open(saved, id, ply);
  try { await waitFor(id, ply); }                      // still running on the server, or finished but not saved here
  catch (e) {
    toast("That review isn't available any more. Start a new one.");
    history.replaceState(null, "", location.pathname + location.search);
    setBusy(false);
  }
}
migrateLegacy().finally(route);                        // reviews saved by older versions move over first
window.addEventListener("hashchange", route);          // a pasted link, or the back / forward buttons

// ------------------------------------------------------------------ offline support: keep the app itself in the browser
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
}
window.addEventListener("offline", () => toast("You're offline. Saved reviews and positions you've seen still work.", 4000));
window.addEventListener("online", () => toast("Back online."));
