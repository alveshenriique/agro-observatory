// Measures the Explorar map on a simulated phone and on a desktop: time until the outline
// of the states is on screen and until the whole map is, the cost of drawing one frame, and how smooth the timeline is while
// playing (with and without reduced motion), plus the cost of zooming into a state.
//
// Phone: the Lighthouse mobile profile (412 × 823 CSS px, DPR 1.75, CPU 4× slower,
// 150 ms RTT and 1.6 Mbit/s down). Desktop: 1350 × 940, no throttling.
//
// The script serves dist/ itself, gzip-compressed as the CDN serves it (http-server only
// sends precompressed files, so it would measure the uncompressed transfer).
// Usage, after a build: node scripts/measure-explore.mjs
import { createReadStream, existsSync, statSync } from "node:fs";
import { createServer } from "node:http";
import path from "node:path";
import { createGzip } from "node:zlib";

import { chromium } from "@playwright/test";

const root = path.resolve("dist");
const types = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".woff2": "font/woff2", ".svg": "image/svg+xml", ".ico": "image/x-icon" };
const server = createServer((request, response) => {
  let file = path.join(root, decodeURIComponent(new URL(request.url ?? "/", "http://x").pathname));
  if (!file.startsWith(root)) return void response.writeHead(403).end();
  if (existsSync(file) && statSync(file).isDirectory()) file = path.join(file, "index.html");
  if (!existsSync(file)) return void response.writeHead(404).end();
  const type = types[path.extname(file)] ?? "application/octet-stream";
  const compress = /gzip/.test(String(request.headers["accept-encoding"])) && !file.endsWith(".woff2");
  response.writeHead(200, { "content-type": type, ...(compress ? { "content-encoding": "gzip" } : {}) });
  const stream = createReadStream(file);
  (compress ? stream.pipe(createGzip({ level: 6 })) : stream).pipe(response);
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${server.address().port}`;

const profiles = {
  phone: {
    context: { viewport: { width: 412, height: 823 }, deviceScaleFactor: 1.75, isMobile: true, hasTouch: true },
    cpu: 4,
    network: { latency: 150, downloadThroughput: (1638.4 * 1024) / 8, uploadThroughput: (750 * 1024) / 8 },
  },
  desktop: { context: { viewport: { width: 1350, height: 940 } }, cpu: 1, network: null },
};

const quantile = (values, p) => {
  const sorted = [...values].sort((a, b) => a - b);
  if (!sorted.length) return NaN;
  return sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))];
};
const round = (v) => Math.round(v * 10) / 10;

async function run(name, profile, reducedMotion, measure) {
  const browser = await chromium.launch();
  const context = await browser.newContext({ ...profile.context, reducedMotion });
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: profile.cpu });
  if (profile.network) {
    await cdp.send("Network.enable");
    await cdp.send("Network.emulateNetworkConditions", { offline: false, ...profile.network });
  }
  await page.addInitScript(() => {
    // The first animation frame (they run just before a paint) in which the outline, and then
    // the finished map, are on screen.
    const seen = (selector) => {
      const el = document.querySelector(selector);
      return !!el && el.getBoundingClientRect().width > 0 && el.checkVisibility();
    };
    const watch = (now) => {
      if (window.__outlineAt === undefined && seen(".explore__outline-country")) window.__outlineAt = now;
      if (window.__mapAt === undefined && document.querySelector('.explore__map[data-ready="true"]')) window.__mapAt = now;
      if (window.__mapAt === undefined) requestAnimationFrame(watch);
    };
    requestAnimationFrame(watch);
    window.__long = [];
    new PerformanceObserver((list) => {
      for (const e of list.getEntries()) window.__long.push({ start: e.startTime, duration: e.duration });
    }).observe({ type: "longtask", buffered: true });
  });

  await page.goto(`${base}/explorar/?serie=soja&medida=${measure}&ano=1990`);
  await page.waitForSelector('.explore__map[data-ready="true"]', { timeout: 60_000 });
  const firstPaint = await page.evaluate(() => ({
    fcp: performance.getEntriesByName("first-contentful-paint")[0]?.startTime,
    outline: window.__outlineAt,
    map: window.__mapAt,
  }));
  await page.waitForTimeout(1000);

  // Play ten years, recording every animation frame and every draw.
  const playing = await page.evaluate(async () => {
    performance.clearMeasures("atlas:map-draw");
    performance.clearMeasures("atlas:map-circles");
    performance.clearMeasures("atlas:map-blend");
    performance.clearMeasures("atlas:map-ahead");
    const frames = [];
    let last = performance.now();
    let running = true;
    const loop = (now) => {
      frames.push([now, now - last]);
      last = now;
      if (running) requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
    const start = performance.now();
    const longBefore = window.__long.length;
    document.querySelector(".timeline__play")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    const map = document.querySelector(".explore__map");
    await new Promise((resolve) => {
      const check = () => (map?.getAttribute("data-view")?.endsWith("/2000/BR") ? resolve() : setTimeout(check, 20));
      check();
    });
    await new Promise((resolve) => setTimeout(resolve, 600));
    running = false;
    document.querySelector(".timeline__play")?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    return {
      seconds: (performance.now() - start) / 1000,
      frames: frames.slice(1),
      draws: performance.getEntriesByName("atlas:map-draw").map((m) => m.duration),
      circles: performance.getEntriesByName("atlas:map-circles").map((m) => m.duration),
      blends: performance.getEntriesByName("atlas:map-blend").map((m) => [m.startTime, m.startTime + m.duration]),
      ahead: performance.getEntriesByName("atlas:map-ahead").map((m) => m.duration),
      long: window.__long.slice(longBefore).map((e) => e.duration),
      transition: map?.getAttribute("data-transition"),
    };
  });

  // Zoom into Minas Gerais (the largest state mesh) and back.
  const zoom = await page.evaluate(async () => {
    const select = [...document.querySelectorAll(".explore__focus select")][0];
    const map = document.querySelector(".explore__map");
    const start = performance.now();
    select.value = "MG";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    await new Promise((resolve) => {
      const check = () =>
        map?.getAttribute("data-view")?.endsWith("/MG") && map.getAttribute("data-ready") === "true"
          ? resolve()
          : setTimeout(check, 20);
      check();
    });
    return performance.now() - start;
  });

  const measures = await page.evaluate(() =>
    Object.fromEntries(
      ["atlas:mesh-decode", "atlas:map-prepare", "atlas:map-hit"].map((n) => [
        n,
        performance.getEntriesByName(n).map((m) => Math.round(m.duration)),
      ]),
    ),
  );
  await browser.close();

  const frames = playing.frames.map(([, delta]) => delta);
  // Frames while a cross-fade runs (the map is moving): a long one there is visible stutter.
  const moving = playing.frames
    .filter(([at, delta]) => playing.blends.some(([from, to]) => at - delta >= from - 1 && at <= to + 17))
    .map(([, delta]) => delta);
  return {
    profile: name,
    reducedMotion,
    measure,
    firstContentfulPaintMs: Math.round(firstPaint.fcp),
    outlineOnScreenMs: Math.round(firstPaint.outline),
    mapOnScreenMs: Math.round(firstPaint.map),
    drawMs: playing.draws.length
      ? { median: round(quantile(playing.draws, 0.5)), p95: round(quantile(playing.draws, 0.95)), max: round(Math.max(...playing.draws)) }
      : null,
    circlesMs: playing.circles.length
      ? { draws: playing.circles.length, median: round(quantile(playing.circles, 0.5)), p95: round(quantile(playing.circles, 0.95)), max: round(Math.max(...playing.circles)) }
      : null,
    play: {
      years: 10,
      seconds: round(playing.seconds),
      frames: frames.length,
      fps: round(frames.length / playing.seconds),
      frameMs: { median: round(quantile(frames, 0.5)), p95: round(quantile(frames, 0.95)), max: round(Math.max(...frames)) },
      over33ms: frames.filter((f) => f > 33.4).length,
      over50ms: frames.filter((f) => f > 50).length,
      blends: playing.blends.length,
      blendFrames: moving.length,
      blendFrameMs: moving.length ? { median: round(quantile(moving, 0.5)), p95: round(quantile(moving, 0.95)), max: round(Math.max(...moving)) } : null,
      blendOver33ms: moving.filter((f) => f > 33.4).length,
      aheadMs: playing.ahead.length ? { median: Math.round(quantile(playing.ahead, 0.5)), max: Math.round(Math.max(...playing.ahead)) } : null,
      longTasks: playing.long.length,
      longestTaskMs: playing.long.length ? Math.round(Math.max(...playing.long)) : 0,
      lastTransition: playing.transition,
    },
    zoomIntoMgMs: Math.round(zoom),
    measures,
  };
}

// Circles (production, a total) with and without reduced motion; the choropleth (yield)
// for comparison.
const runs = [
  ["phone", "no-preference", "producao"],
  ["phone", "reduce", "producao"],
  ["phone", "no-preference", "rendimento"],
  ["desktop", "no-preference", "producao"],
  ["desktop", "reduce", "producao"],
  ["desktop", "no-preference", "rendimento"],
];
const results = [];
for (const [name, reducedMotion, measure] of runs) {
  results.push(await run(name, profiles[name], reducedMotion, measure));
}
server.close();
console.log(JSON.stringify(results, null, 2));
