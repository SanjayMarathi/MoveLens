// Renders static/icon.svg to static/icon-192.png and static/icon-512.png (for the installable-app manifest).
//     node tools/make_icons.js          (needs Node 22+ and Edge or Chrome; set BROWSER=path if it isn't found)
const { spawn, execSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const STATIC = path.join(__dirname, "..", "static");
const svg = fs.readFileSync(path.join(STATIC, "icon.svg"), "utf8");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const candidates = [process.env.BROWSER, "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe", "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", "/usr/bin/google-chrome", "/usr/bin/chromium", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"];

(async () => {
  const browser = candidates.find((p) => p && fs.existsSync(p));
  if (!browser) throw new Error("No Edge/Chrome found. Set BROWSER to its path.");
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "movelens-icon-"));
  const port = 9445;
  const proc = spawn(browser, ["--headless=new", "--disable-gpu", `--remote-debugging-port=${port}`, "--remote-allow-origins=*", `--user-data-dir=${path.join(tmp, "p")}`, "about:blank"], { stdio: "ignore" });
  let page;
  for (let i = 0; i < 40 && !page; i++) { try { page = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === "page"); } catch (e) { /* starting */ } await sleep(250); }
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0; const pending = new Map();
  ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } };
  const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
  await send("Page.enable");
  for (const size of [192, 512]) {
    const html = `<!doctype html><body style="margin:0;background:transparent"><div style="width:${size}px;height:${size}px">${svg.replace("<svg ", `<svg width="${size}" height="${size}" `)}</div>`;
    fs.writeFileSync(path.join(tmp, "i.html"), html);
    await send("Emulation.setDeviceMetricsOverride", { width: size, height: size, deviceScaleFactor: 1, mobile: false });
    await send("Emulation.setDefaultBackgroundColorOverride", { color: { r: 0, g: 0, b: 0, a: 0 } });
    await send("Page.navigate", { url: "file:///" + path.join(tmp, "i.html").replace(/\\/g, "/") });
    await sleep(700);
    const shot = await send("Page.captureScreenshot", { format: "png", omitBackground: true });
    fs.writeFileSync(path.join(STATIC, `icon-${size}.png`), Buffer.from(shot.result.data, "base64"));
    fs.writeFileSync(path.join(STATIC, `icon-${size}.png.b64`), shot.result.data.replace(/(.{76})/g, "$1\n") + "\n");   // text twin (see app/assets.py)
    console.log(`icon-${size}.png written`);
  }
  ws.close();
  try { execSync(process.platform === "win32" ? `taskkill /pid ${proc.pid} /T /F` : `kill ${proc.pid}`, { stdio: "ignore" }); } catch (e) { /* gone */ }
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
