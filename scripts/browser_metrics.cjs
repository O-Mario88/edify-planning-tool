#!/usr/bin/env node
/* Core Web Vitals for signed-in pages, on a throttled mobile profile.
 *
 * The route sweep and the load test time the server. What a field officer
 * waits for is the page on their phone: the stylesheets and scripts it must
 * download before anything paints, the HTML it must parse, the main-thread
 * work that makes a tap feel dead. This opens each page in Chromium under
 * Lighthouse's "Slow 4G" profile (150 ms RTT, 1.6 Mbps down, 750 kbps up)
 * and a 4x CPU slowdown, and records per visit:
 *
 *   ttfb, fcp, lcp            navigation and paint timings (ms)
 *   cls                       layout shift, excluding shifts after input
 *   longTasks, longTaskMs     main-thread tasks over 50 ms and their total
 *   inp                       the slowest interaction: typing into the page's
 *                             search box when it has one, else a click on the
 *                             page heading (read-only either way)
 *   domNodes, htmlKB, transferKB, requests
 *
 * Each page is visited cold (a fresh browser context: empty HTTP cache, no
 * service worker) and then warm (the same context again), which is what a
 * returning user gets.
 *
 *   node scripts/browser_metrics.cjs --base http://127.0.0.1:8000 \
 *     --sessions sessions.json --pages pages.json --out metrics.json
 *
 * sessions.json maps an account to a session cookie value; pages.json is a
 * list of {"account": ..., "path": ...}. Run it against a local, disposable
 * deployment, never production.
 */
'use strict';

const fs = require('node:fs');
const { chromium } = require('@playwright/test');

function arg(name, fallback) {
  const i = process.argv.indexOf(`--${name}`);
  return i > -1 ? process.argv[i + 1] : fallback;
}

const BASE = arg('base', 'http://127.0.0.1:8000');
const SESSIONS = JSON.parse(fs.readFileSync(arg('sessions'), 'utf8'));
const PAGES = JSON.parse(fs.readFileSync(arg('pages'), 'utf8'));
const OUT = arg('out', 'browser-metrics.json');
const EXECUTABLE = arg('executable', process.env.CHROMIUM_PATH || undefined);
const SETTLE_MS = Number(arg('settle', '2500'));

// Lighthouse's mobile "Slow 4G" and its CPU slowdown.
const NETWORK = {
  offline: false,
  latency: 150,
  downloadThroughput: (1.6 * 1024 * 1024) / 8,
  uploadThroughput: (750 * 1024) / 8,
};
const CPU_SLOWDOWN = Number(arg('cpu', '4'));

// Installed before any page script: every observer buffers from navigation.
const OBSERVE = `
  window.__edifyVitals = { lcp: 0, cls: 0, longTasks: 0, longTaskMs: 0, inp: 0 };
  const v = window.__edifyVitals;
  const watch = (type, fn, extra) => {
    try { new PerformanceObserver((l) => l.getEntries().forEach(fn))
      .observe(Object.assign({ type, buffered: true }, extra || {})); } catch (e) {}
  };
  watch('largest-contentful-paint', (e) => { v.lcp = e.startTime; });
  watch('layout-shift', (e) => { if (!e.hadRecentInput) v.cls += e.value; });
  watch('longtask', (e) => { v.longTasks += 1; v.longTaskMs += e.duration; });
  watch('event', (e) => { if (e.interactionId) v.inp = Math.max(v.inp, e.duration); },
        { durationThreshold: 16 });
`;

async function visit(context, path) {
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send('Network.enable');
  await cdp.send('Network.emulateNetworkConditions', NETWORK);
  await cdp.send('Emulation.setCPUThrottlingRate', { rate: CPU_SLOWDOWN });
  let transfer = 0;
  let requests = 0;
  cdp.on('Network.loadingFinished', (e) => {
    transfer += e.encodedDataLength || 0;
    requests += 1;
  });
  const started = Date.now();
  const response = await page.goto(BASE + path, { waitUntil: 'load', timeout: 120000 });
  await page.waitForTimeout(SETTLE_MS);

  // One read-only interaction, the kind INP is made of.
  let interaction = 'none';
  const search = page.locator('input[type="search"]:visible, input[name="q"]:visible').first();
  if (await search.count()) {
    await search.click();
    await page.keyboard.type('pri', { delay: 60 });
    interaction = 'type-search';
  } else {
    const heading = page.locator('h1:visible').first();
    if (await heading.count()) {
      await heading.click();
      interaction = 'click-heading';
    }
  }
  await page.waitForTimeout(1200);

  const metrics = await page.evaluate(() => {
    const nav = performance.getEntriesByType('navigation')[0] || {};
    const fcp = performance.getEntriesByName('first-contentful-paint')[0];
    const v = window.__edifyVitals || {};
    return {
      ttfb: nav.responseStart || null,
      fcp: fcp ? fcp.startTime : null,
      lcp: v.lcp || null,
      cls: v.cls,
      longTasks: v.longTasks,
      longTaskMs: v.longTaskMs,
      inp: v.inp || null,
      domNodes: document.getElementsByTagName('*').length,
      htmlKB: nav.decodedBodySize ? nav.decodedBodySize / 1024 : null,
    };
  });
  await page.close();
  return {
    status: response ? response.status() : null,
    finalUrl: response ? new URL(response.url()).pathname : null,
    wallMs: Date.now() - started,
    transferKB: transfer / 1024,
    requests,
    interaction,
    ...metrics,
  };
}

(async () => {
  const browser = await chromium.launch(EXECUTABLE ? { executablePath: EXECUTABLE } : {});
  const host = new URL(BASE).hostname;
  const rows = [];
  for (const { account, path } of PAGES) {
    const context = await browser.newContext({
      viewport: { width: 412, height: 823 },
      deviceScaleFactor: 2,
      isMobile: true,
      hasTouch: true,
    });
    await context.addInitScript(OBSERVE);
    await context.addCookies([
      { name: 'sessionid', value: SESSIONS[account], domain: host, path: '/' },
    ]);
    for (const visitKind of ['cold', 'warm']) {
      try {
        const m = await visit(context, path);
        rows.push({ account, path, visit: visitKind, ...m });
        process.stdout.write(
          `${visitKind.padEnd(5)} ${account.padEnd(28)} ${path.padEnd(34)} ` +
            `fcp ${Math.round(m.fcp || 0)} lcp ${Math.round(m.lcp || 0)} ` +
            `inp ${Math.round(m.inp || 0)} cls ${(m.cls || 0).toFixed(3)} ` +
            `long ${m.longTasks}/${Math.round(m.longTaskMs)}ms dom ${m.domNodes} ` +
            `xfer ${Math.round(m.transferKB)}KB\n`,
        );
      } catch (err) {
        rows.push({ account, path, visit: visitKind, error: String(err) });
        process.stdout.write(`${visitKind} ${account} ${path} ERROR ${err}\n`);
      }
    }
    await context.close();
  }
  await browser.close();
  fs.writeFileSync(OUT, JSON.stringify(rows, null, 2));
})();
