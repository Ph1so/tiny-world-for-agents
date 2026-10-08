// Render a run to PNG frames by stepping the viewer with the arrow key.
//   node scripts/record.mjs URL OUTDIR NFRAMES [width height settleMs]
import { chromium } from "playwright-core";
import { existsSync, readdirSync, mkdirSync } from "node:fs";
import { join } from "node:path";

const [url, outdir, nframes = "200", w = "1280", h = "800", settle = "130"] = process.argv.slice(2);
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
await page.mouse.click(300, 300);          // focus the canvas/body
for (let i = 1; i <= +nframes; i++) {
  await page.keyboard.press("ArrowRight");
  await page.waitForTimeout(+settle);
  await page.screenshot({ path: join(outdir, `f${String(i).padStart(4, "0")}.png`) });
  if (i % 40 === 0) console.log(`frame ${i}/${nframes}`);
}
await browser.close();
console.log("done");
