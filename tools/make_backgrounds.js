// Generates the page backgrounds in static/bg/*.jpg.
//
// Each scene is drawn procedurally as SVG (gradients, noise-based clouds, stars, rolling hills) and rendered to a
// JPEG by headless Edge/Chrome through the DevTools protocol. Run it again after editing a scene:
//
//     node tools/make_backgrounds.js            (set BROWSER=path\to\msedge.exe if it isn't found)
//
// Needs Node 22+ (built-in WebSocket) and Edge or Chrome. Nothing here is needed to run the app.
const { spawn, execSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const W = 1920, H = 1080;
const OUT = path.join(__dirname, "..", "static", "bg");

// ------------------------------------------------------------------ helpers
function rng(seed) {                                   // small seeded random generator, so every run looks the same
  let a = seed >>> 0;
  return () => { a = (a + 0x6d2b79f5) >>> 0; let t = a; t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const stops = (list) => list.map(([o, c, a]) => `<stop offset="${o}" stop-color="${c}"${a != null ? ` stop-opacity="${a}"` : ""}/>`).join("");

// A cloud layer: fractal noise turned into soft white blobs. `lit` is the colour of the sunlit top, `shade` the colour of
// the underside (drawn first, a little lower), `cover` how much of the sky is cloud (higher = more), `band` the part of the
// sky (0..1 from the top) where clouds may appear.
function clouds({ id, seed, lit, shade, cover = 0.9, band = [0.05, 0.75], freq = "0.0042 0.0095", opacity = 1 }) {
  const k = 3.4, b = -(k * (0.62 - cover * 0.2));      // noise -> alpha: keep only the bright part of the noise
  const matrix = (c) => `0 0 0 0 ${c[0]}  0 0 0 0 ${c[1]}  0 0 0 0 ${c[2]}  0 0 0 ${k} ${b.toFixed(3)}`;
  const [y0, y1] = band;
  return `
  <filter id="${id}-lit" x="0" y="0" width="100%" height="100%" color-interpolation-filters="sRGB">
    <feTurbulence type="fractalNoise" baseFrequency="${freq}" numOctaves="6" seed="${seed}"/>
    <feColorMatrix type="matrix" values="${matrix(lit)}"/>
  </filter>
  <filter id="${id}-shade" x="0" y="0" width="100%" height="100%" color-interpolation-filters="sRGB">
    <feTurbulence type="fractalNoise" baseFrequency="${freq}" numOctaves="6" seed="${seed}"/>
    <feColorMatrix type="matrix" values="${matrix(shade)}"/>
  </filter>
  <linearGradient id="${id}-fade" x1="0" y1="0" x2="0" y2="1">${stops([[0, "#000"], [y0, "#000"], [(y0 + y1) / 2, "#fff"], [y1, "#000"], [1, "#000"]])}</linearGradient>
  <mask id="${id}-mask"><rect width="${W}" height="${H}" fill="url(#${id}-fade)"/></mask>
  <g mask="url(#${id}-mask)" opacity="${opacity}">
    <rect width="${W}" height="${H}" filter="url(#${id}-shade)" transform="translate(10 26)" opacity=".85"/>
    <rect width="${W}" height="${H}" filter="url(#${id}-lit)"/>
  </g>`;
}

function hills({ y, amp, seed, top, bottom, id }) {   // a rolling ridge made of a few sine waves
  const r = rng(seed), waves = [0, 1, 2].map(() => ({ f: 0.0016 + r() * 0.004, p: r() * 6.28, a: 0.4 + r() * 0.6 }));
  let d = `M0 ${H} L0 ${y}`;
  for (let x = 0; x <= W; x += 16) {
    const v = waves.reduce((s, w) => s + Math.sin(x * w.f + w.p) * w.a, 0) / 2;
    d += ` L${x} ${(y - v * amp).toFixed(1)}`;
  }
  d += ` L${W} ${H} Z`;
  return `<linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1">${stops([[0, top], [1, bottom]])}</linearGradient><path d="${d}" fill="url(#${id})"/>`;
}

const svg = (body) => `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"><defs></defs>${body}</svg>`;

// ------------------------------------------------------------------ scenes
const scenes = {
  // Bright daytime sky, like the one behind the review pages of the big chess sites.
  sky: svg(`
    <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">${stops([[0, "#1f6fc2"], [0.45, "#4b9be0"], [0.8, "#9ccdf2"], [1, "#d9eefc"]])}</linearGradient>
    <radialGradient id="sun" cx="0.82" cy="0.12" r="0.6">${stops([[0, "#ffffff", 0.55], [0.35, "#fff6d8", 0.18], [1, "#ffffff", 0]])}</radialGradient></defs>
    <rect width="${W}" height="${H}" fill="url(#g)"/><rect width="${W}" height="${H}" fill="url(#sun)"/>
    ${clouds({ id: "c1", seed: 11, lit: [1, 1, 1], shade: [0.55, 0.7, 0.88], cover: 0.95, band: [0.02, 0.8] })}
    ${clouds({ id: "c2", seed: 42, lit: [1, 1, 1], shade: [0.62, 0.75, 0.92], cover: 0.55, band: [0.25, 1], freq: "0.009 0.02", opacity: 0.8 })}`),

  // Sunset: purple at the top, orange at the horizon.
  dusk: svg(`
    <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">${stops([[0, "#1b1650"], [0.3, "#4e2a86"], [0.55, "#b2467f"], [0.78, "#f6845d"], [1, "#ffd08a"]])}</linearGradient>
    <radialGradient id="sun" cx="0.5" cy="1" r="0.75">${stops([[0, "#fff1c4", 0.9], [0.25, "#ffb96b", 0.45], [1, "#ff7a59", 0]])}</radialGradient></defs>
    <rect width="${W}" height="${H}" fill="url(#g)"/><rect width="${W}" height="${H}" fill="url(#sun)"/>
    ${clouds({ id: "c1", seed: 7, lit: [1, 0.74, 0.6], shade: [0.34, 0.16, 0.5], cover: 0.9, band: [0.1, 0.95] })}
    ${clouds({ id: "c2", seed: 91, lit: [1, 0.82, 0.7], shade: [0.42, 0.2, 0.55], cover: 0.5, band: [0.4, 1], freq: "0.008 0.022", opacity: 0.7 })}`),

  // Night: stars, a moon and thin dark clouds.
  night: (() => {
    const r = rng(2024); let stars = "";
    for (let i = 0; i < 520; i++) {
      const x = r() * W, y = Math.pow(r(), 1.6) * H * 0.92, big = r() > 0.97, s = big ? 1.6 + r() * 1.2 : 0.4 + r() * 1.1;
      stars += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${s.toFixed(2)}" fill="#fff" opacity="${(0.25 + r() * 0.75).toFixed(2)}"/>`;
      if (big) stars += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(s * 4).toFixed(1)}" fill="url(#glow)" opacity=".55"/>`;
    }
    return svg(`
    <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">${stops([[0, "#04081c"], [0.55, "#0d1a45"], [1, "#27407f"]])}</linearGradient>
    <radialGradient id="glow">${stops([[0, "#bcd2ff", 0.9], [1, "#bcd2ff", 0]])}</radialGradient>
    <radialGradient id="moon" cx="0.35" cy="0.35" r="0.75">${stops([[0, "#ffffff"], [0.6, "#e9edf7"], [1, "#b9c3dc"]])}</radialGradient>
    <radialGradient id="halo">${stops([[0, "#cfe0ff", 0.5], [0.4, "#8fb0ff", 0.14], [1, "#8fb0ff", 0]])}</radialGradient></defs>
    <rect width="${W}" height="${H}" fill="url(#g)"/>${stars}
    <circle cx="1560" cy="230" r="330" fill="url(#halo)"/><circle cx="1560" cy="230" r="78" fill="url(#moon)"/>
    <circle cx="1536" cy="212" r="14" fill="#aab4cf" opacity=".35"/><circle cx="1588" cy="262" r="20" fill="#aab4cf" opacity=".3"/><circle cx="1570" cy="198" r="8" fill="#aab4cf" opacity=".3"/>
    ${clouds({ id: "c1", seed: 5, lit: [0.34, 0.42, 0.7], shade: [0.07, 0.1, 0.26], cover: 0.6, band: [0.35, 1], opacity: 0.8 })}`);
  })(),

  // A bright meadow under a light sky.
  meadow: svg(`
    <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">${stops([[0, "#3a8fd9"], [0.5, "#8cc6f0"], [0.75, "#d3eefb"], [1, "#f1f9ec"]])}</linearGradient>
    <radialGradient id="sun" cx="0.2" cy="0.16" r="0.5">${stops([[0, "#ffffff", 0.6], [0.4, "#fff3c4", 0.2], [1, "#ffffff", 0]])}</radialGradient></defs>
    <rect width="${W}" height="${H}" fill="url(#g)"/><rect width="${W}" height="${H}" fill="url(#sun)"/>
    ${clouds({ id: "c1", seed: 23, lit: [1, 1, 1], shade: [0.62, 0.76, 0.9], cover: 0.8, band: [0.05, 0.7] })}
    ${hills({ y: 760, amp: 70, seed: 3, top: "#a9d48a", bottom: "#7fb85f", id: "h1" })}
    ${hills({ y: 850, amp: 90, seed: 8, top: "#78b856", bottom: "#4f9a3f", id: "h2" })}
    ${hills({ y: 960, amp: 70, seed: 15, top: "#4e9b3d", bottom: "#2f7a2e", id: "h3" })}`),
};

// ------------------------------------------------------------------ render
function findBrowser() {
  const candidates = [process.env.BROWSER,
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe", "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", "/usr/bin/google-chrome", "/usr/bin/chromium", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"];
  const found = candidates.find((p) => p && fs.existsSync(p));
  if (!found) throw new Error("No Edge/Chrome found. Set BROWSER to its path.");
  return found;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "movelens-bg-"));
  const port = 9444;
  const proc = spawn(findBrowser(), ["--headless=new", "--disable-gpu", `--remote-debugging-port=${port}`, "--remote-allow-origins=*",
    `--user-data-dir=${path.join(tmp, "profile")}`, "about:blank"], { stdio: "ignore" });
  let page;
  for (let i = 0; i < 40 && !page; i++) { try { page = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === "page"); } catch (e) { /* not up yet */ } await sleep(250); }
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0; const pending = new Map();
  ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } };
  const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
  await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: W, height: H, deviceScaleFactor: 1, mobile: false });

  const only = process.argv.slice(2);
  for (const [name, markup] of Object.entries(scenes)) {
    if (only.length && !only.includes(name)) continue;
    const file = path.join(tmp, name + ".svg");
    fs.writeFileSync(file, markup);
    await send("Page.navigate", { url: "file:///" + file.replace(/\\/g, "/") });
    await sleep(1800);                                  // let the noise filters finish
    const shot = await send("Page.captureScreenshot", { format: "jpeg", quality: 80 });
    const out = path.join(OUT, name + ".jpg");
    fs.writeFileSync(out, Buffer.from(shot.result.data, "base64"));
    fs.writeFileSync(out + ".b64", shot.result.data.replace(/(.{76})/g, "$1\n") + "\n");   // text twin: Hugging Face rejects binary files in git (see app/assets.py)
    console.log(`${name}.jpg  ${(fs.statSync(out).size / 1024).toFixed(0)} KB`);
  }
  ws.close();
  try { execSync(process.platform === "win32" ? `taskkill /pid ${proc.pid} /T /F` : `kill ${proc.pid}`, { stdio: "ignore" }); } catch (e) { /* gone */ }
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
