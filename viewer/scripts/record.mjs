// Render a run to PNG frames by pausing the viewer and stepping it one world step at a time.
//   node scripts/record.mjs URL OUTDIR NFRAMES [width height settleMs]
//   STRIDE=n  world steps advanced per captured frame (default 1)
// Autoplay is turned off first (Space), then the run is rewound to t=0, so frame i shows
// world step i*STRIDE exactly. This gives uniform coverage instead of blowing through to the end.
import { chromium } from "playwright-core";
import { existsSync, readdirSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const [url, outdir, nframes = "200", w = "1280", h = "800", settle = "90"] = process.argv.slice(2);
const STRIDE = +(process.env.STRIDE || 1);
function findChrome() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;
  const root = process.env.PLAYWRIGHT_BROWSERS_PATH || "/opt/pw-browsers";
  for (const d of readdirSync(root).filter((d) => d.startsWith("chromium-")).sort().reverse())
    for (const rel of ["chrome-linux/chrome", "chrome-linux64/chrome"]) {
      const p = join(root, d, rel); if (existsSync(p)) return p;
    }
}
mkdirSync(outdir, { recursive: true });
const browser = await chromium.launch({ executablePath: findChrome(), args: ["--use-gl=swiftshader", "--enable-unsafe-swiftshader", "--hide-scrollbars"] });
const page = await browser.newPage({ viewport: { width: +w, height: +h }, deviceScaleFactor: 1 });
await page.goto(url, { waitUntil: "networkidle" });
await page.waitForTimeout(2800);
await page.mouse.click(300, 300);              // focus the page for key events
await page.keyboard.press("Space");            // replay autoplays on load; pause it
await page.waitForTimeout(150);
for (let i = 0; i < 20; i++) { await page.keyboard.press("Shift+ArrowLeft"); }  // rewind to t=0
await page.waitForTimeout(250);
for (let i = 1; i <= +nframes; i++) {
  await page.screenshot({ path: join(outdir, `f${String(i).padStart(4, "0")}.png`) });
  for (let s = 0; s < STRIDE; s++) await page.keyboard.press("ArrowRight");
  await page.waitForTimeout(+settle);
  if (i % 40 === 0) console.log(`frame ${i}/${nframes}`);
}
await browser.close();
console.log("done");
