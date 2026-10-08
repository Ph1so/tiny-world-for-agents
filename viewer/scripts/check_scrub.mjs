// Scrub a replay in headless Chromium and check that the memory panel and the observation
// panel show exactly what the log files hold for that step (PLAN.md M5 acceptance).
//   node scripts/check_scrub.mjs http://127.0.0.1:8000 memdemo ../viewer/fixtures/memdemo
// Exit code 1 on any mismatch or page error.
import { chromium } from "playwright-core";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const [base = "http://127.0.0.1:8000", runId = "memdemo", runDir = "fixtures/memdemo"] = process.argv.slice(2);

function findChrome() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;
  const root = process.env.PLAYWRIGHT_BROWSERS_PATH || "/opt/pw-browsers";
  if (!existsSync(root)) return undefined;
  for (const d of readdirSync(root).filter((d) => d.startsWith("chromium-")).sort().reverse()) {
    for (const rel of ["chrome-linux/chrome", "chrome-linux64/chrome"]) {
      const p = join(root, d, rel);
      if (existsSync(p)) return p;
    }
  }
  return undefined;
}

const jsonl = (f) => readFileSync(join(runDir, f), "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
const steps = jsonl("steps.jsonl");
const memory = jsonl("memory.jsonl");
const world = jsonl("world.jsonl");
const agentStepAt = (t) => { let i = 0; for (const w of world) { if (w.type === "step" && w.t <= t) i = w.i; } return i; };
const memoryAt = (i) => { let m = memory[0]; for (const r of memory) { if (r.i <= i) m = r; } return m.text; };

const errors = [];
const browser = await chromium.launch({
  executablePath: findChrome(),
  args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--no-sandbox"],
});
const page = await browser.newPage({ viewport: { width: 1500, height: 900 } });
page.on("console", (m) => { if (m.type() === "error") errors.push("console: " + m.text()); });
page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
await page.goto(`${base}/?run=${runId}&t=0`, { waitUntil: "networkidle" });
await page.waitForFunction(() => { const o = document.querySelector(".overlay"); return o && getComputedStyle(o).display === "none"; }, null, { timeout: 60000 });
await page.waitForTimeout(500);

async function readPanels() {
  return page.evaluate(() => {
    const t = Number(document.querySelector(".scrub-label, .time-label, .tlabel")?.textContent?.split("/")[0] ?? NaN);
    const lines = [...document.querySelectorAll(".memory-text .dl")].filter((d) => !d.classList.contains("del"))
      .map((d) => [...d.querySelectorAll(".ws")].filter((s) => !s.classList.contains("del")).map((s) => s.textContent).join(""));
    const single = document.querySelector(".memory-text > .muted")?.textContent;
    const mem = lines.length ? lines.join("\n") : (single === "(empty)" ? "" : single ?? "");
    const obs = document.querySelector("pre.observation")?.textContent ?? "";
    const usage = document.querySelector(".usage-label")?.textContent ?? "";
    return { t, mem, obs, usage };
  });
}

let checked = 0, bad = 0;
async function checkAt(label) {
  await page.waitForTimeout(1200);
  const p = await readPanels();
  const i = agentStepAt(p.t);
  const expMem = memoryAt(i);
  const expObs = i > 0 ? steps[i - 1].observation : "";
  const okMem = p.mem.replace(/\s+$/, "") === expMem.replace(/\s+$/, "");
  const okObs = p.obs === expObs;
  checked++;
  if (!okMem || !okObs) {
    bad++;
    console.log(`MISMATCH ${label}: t=${p.t} i=${i} memory ${okMem ? "ok" : "WRONG"} observation ${okObs ? "ok" : "WRONG"}`);
    if (!okObs) console.log("  panel obs:", JSON.stringify(p.obs.split("\n")[0]), " file obs:", JSON.stringify(expObs.split("\n")[0]), " status:", await page.evaluate(() => document.querySelector(".panel.status .sub, .status-line, .panel .meta")?.textContent));
    if (!okMem) console.log("  panel:", JSON.stringify(p.mem.slice(-160)), "\n  file: ", JSON.stringify(expMem.slice(-160)));
  } else {
    console.log(`ok ${label}: t=${p.t} i=${i} ${p.usage}`);
  }
}

// 1. The next-memory-edit button, eight times.
for (let n = 0; n < 8; n++) {
  await page.getByRole("button", { name: /memory ⏭/ }).click();
  await checkAt(`memory-next #${n + 1}`);
}
// 2. Clicks across the timeline canvas.
for (const f of [0.15, 0.3, 0.45, 0.6, 0.75, 0.9]) {
  await page.locator("canvas.timeline-canvas").scrollIntoViewIfNeeded();
  const box = await page.locator("canvas.timeline-canvas").boundingBox();
  await page.mouse.click(box.x + box.width * f, box.y + box.height * 0.5);
  await checkAt(`timeline click ${f}`);
}
// 3. Keyboard steps, one world step at a time, through a stretch with edits.
for (let n = 0; n < 12; n++) {
  await page.keyboard.press("ArrowRight");
  await checkAt(`arrow-right #${n + 1}`);
}
// 4. Previous memory edit, four times.
for (let n = 0; n < 4; n++) {
  await page.getByRole("button", { name: /⏮ memory/ }).click();
  await checkAt(`memory-prev #${n + 1}`);
}
await browser.close();
console.log(`checked ${checked} positions, ${bad} mismatches, ${errors.length} page errors`);
for (const e of errors) console.log(" ", e);
process.exit(bad || errors.length ? 1 : 0);
