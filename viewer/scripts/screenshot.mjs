// Take a screenshot of the viewer with headless Chromium.
//   node scripts/screenshot.mjs "http://127.0.0.1:8000/?run=sensible_seed1&t=700" out.png [width height [scroll-to-selector]]
// The server must be running with the built viewer. Uses the Chromium that Playwright has
// already installed (PLAYWRIGHT_BROWSERS_PATH or /opt/pw-browsers), or CHROME_PATH.
import { chromium } from "playwright-core";
import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";

const [url, out, w = "1500", h = "900", scrollTo = ""] = process.argv.slice(2);
if (!url || !out) { console.error("usage: screenshot.mjs URL OUT.png [width height]"); process.exit(2); }

function findChrome() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;
  const root = process.env.PLAYWRIGHT_BROWSERS_PATH || "/opt/pw-browsers";
  if (!existsSync(root)) return undefined;
  const dirs = readdirSync(root).filter((d) => d.startsWith("chromium-")).sort().reverse();
  for (const d of dirs) {
    for (const rel of ["chrome-linux/chrome", "chrome-linux64/chrome", "chrome-mac/Chromium.app/Contents/MacOS/Chromium"]) {
      const p = join(root, d, rel);
      if (existsSync(p)) return p;
    }
  }
  return undefined;
}

const browser = await chromium.launch({
  executablePath: findChrome(),
  args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--no-sandbox"],
});
const page = await browser.newPage({ viewport: { width: Number(w), height: Number(h) }, deviceScaleFactor: 1 });
page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") console.log("[page]", m.type(), m.text()); });
page.on("pageerror", (e) => console.log("[pageerror]", e.message));
await page.goto(url, { waitUntil: "networkidle" });
await page.waitForFunction(() => {
  const o = document.querySelector(".overlay");
  return !o || getComputedStyle(o).display === "none";   // the run picker has no overlay
}, null, { timeout: 60000 });
await page.waitForTimeout(1500);
if (scrollTo) await page.evaluate((sel) => document.querySelector(sel)?.scrollIntoView({ block: "start" }), scrollTo);
await page.waitForTimeout(200);
const stats = await page.evaluate(() => document.querySelector(".debug")?.textContent ?? "");
if (stats) console.log(stats);
await page.screenshot({ path: out });
console.log("saved", out);
await browser.close();
