/**
 * Record the product demo in real Chrome (Playwright).
 * Uses per-frame screenshots + ffmpeg — reliable when video capture misses React paints.
 *
 * Output: web-ui/out/kiro-bot-demo.mp4
 */
import { spawn } from "node:child_process";
import { mkdir, rm } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const outDir = path.join(root, "out");
const framesDir = path.join(outDir, "frames");
const port = Number(process.env.DEMO_PORT || 4173);
const baseUrl = `http://localhost:${port}/app/?demo=director&drive=1`;
const DURATION_SEC = Number(process.env.DEMO_SEC || 75);
const FPS = Number(process.env.DEMO_FPS || 30);
const totalFrames = DURATION_SEC * FPS;
const frameMs = 1000 / FPS;
const mp4Path = path.join(outDir, "kiro-bot-demo.mp4");

function run(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { stdio: "inherit", ...opts });
    child.on("error", reject);
    child.on("close", (code) => (code === 0 ? resolve() : reject(new Error(`${cmd} exited ${code}`))));
  });
}

async function waitForServer(url, timeoutMs = 60000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(url, { redirect: "follow" });
      if (res.ok || res.status === 200) return;
    } catch {
      /* retry */
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`Server did not start at ${url}`);
}

async function hasFfmpeg() {
  try {
    await run("ffmpeg", ["-version"], { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

async function main() {
  if (!(await hasFfmpeg())) {
    throw new Error("ffmpeg is required for demo:record");
  }

  await mkdir(outDir, { recursive: true });
  await rm(framesDir, { recursive: true, force: true });
  await mkdir(framesDir, { recursive: true });

  const preview = spawn("npm", ["run", "preview", "--", "--port", String(port), "--strictPort"], {
    cwd: root,
    stdio: "inherit",
    env: { ...process.env },
  });

  try {
    await waitForServer(`http://localhost:${port}/app/`);
    await new Promise((r) => setTimeout(r, 800));

    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
      viewport: { width: 1920, height: 1080 },
      deviceScaleFactor: 1,
    });
    const page = await context.newPage();
    await page.goto(baseUrl, { waitUntil: "domcontentloaded" });
    await page.waitForSelector("[data-demo-frame]");

    console.log(`Capturing ${totalFrames} frames at ${FPS} fps…`);
    for (let frame = 0; frame <= totalFrames; frame++) {
      await page.evaluate((f) => {
        window.__DEMO_FRAME__ = f;
        window.dispatchEvent(new Event("demo-tick"));
      }, frame);
      await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
      await page.screenshot({
        path: path.join(framesDir, `${String(frame).padStart(5, "0")}.png`),
        type: "png",
      });
      if (frame % 150 === 0) {
        console.log(`  frame ${frame}/${totalFrames}`);
      }
      await page.waitForTimeout(Math.max(0, frameMs - 5));
    }

    await context.close();
    await browser.close();

    console.log("Encoding MP4…");
    await run("ffmpeg", [
      "-y",
      "-framerate",
      String(FPS),
      "-i",
      path.join(framesDir, "%05d.png"),
      "-c:v",
      "libx264",
      "-pix_fmt",
      "yuv420p",
      "-movflags",
      "+faststart",
      mp4Path,
    ]);

    await rm(framesDir, { recursive: true, force: true });
    console.log(`\n✓ Saved ${mp4Path}`);
  } finally {
    preview.kill("SIGTERM");
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
