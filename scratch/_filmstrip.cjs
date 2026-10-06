#!/usr/bin/env node
/* Filmstrip of real link navigations: what is on screen, frame by frame,
 * between the click and the settled page. Audit tooling only. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('@playwright/test');

const BASE = process.env.BASE || 'http://127.0.0.1:8376';
const OUT = process.env.OUT;
const EMAIL = process.env.EMAIL || 'cceo1@edify.org';
const SCHEME = process.env.SCHEME || 'dark'; // OS colour scheme
const THEME = process.env.THEME || 'system'; // edify_theme preference
const NET = process.env.NET || 'none'; // none | fast4g | slow4g
const CPU = Number(process.env.CPU || '1');
const STANDALONE = process.env.STANDALONE === '1';
const MOBILE = process.env.MOBILE === '1';
const MAX_PAGES = Number(process.env.MAX_PAGES || '6');
const HREFS = process.env.HREFS ? process.env.HREFS.split(',') : null;

const NETS = {
  fast4g: { offline: false, latency: 60, downloadThroughput: (9 * 1024 * 1024) / 8, uploadThroughput: (3 * 1024 * 1024) / 8 },
  slow4g: { offline: false, latency: 150, downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (750 * 1024) / 8 },
};

const OBSERVE = `
  window.__a = { shifts: [], long: [], mutationsAfterFcp: 0, fcp: 0 };
  try {
    new PerformanceObserver((l) => { for (const e of l.getEntries()) {
      if (e.hadRecentInput) continue;
      window.__a.shifts.push({ t: Math.round(e.startTime), v: +e.value.toFixed(4),
        src: (e.sources || []).slice(0, 4).map((s) => { const n = s.node; if (!n || !n.tagName) return '?';
          return n.tagName.toLowerCase() + (n.id ? '#' + n.id : '') + '.' + String(n.className && n.className.baseVal !== undefined ? n.className.baseVal : n.className).split(/\\s+/).slice(0, 3).join('.'); }) });
    } }).observe({ type: 'layout-shift', buffered: true });
    new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__a.long.push({ t: Math.round(e.startTime), d: Math.round(e.duration) }); }).observe({ type: 'longtask', buffered: true });
    new PerformanceObserver((l) => { for (const e of l.getEntries()) if (e.name === 'first-contentful-paint') window.__a.fcp = e.startTime; }).observe({ type: 'paint', buffered: true });
  } catch (e) {}
  document.addEventListener('DOMContentLoaded', () => {
    const seen = {};
    window.__a.mut = seen;
    new MutationObserver((records) => {
      if (!window.__a.fcp) return;
      for (const r of records) {
        window.__a.mutationsAfterFcp++;
        const n = r.target.nodeType === 1 ? r.target : r.target.parentElement;
        if (!n) continue;
        const key = r.type + ':' + (r.attributeName || '') ;
        seen[key] = (seen[key] || 0) + 1;
      }
    }).observe(document.documentElement, { subtree: true, childList: true, attributes: true, characterData: true });
  });
`;

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch();
  const context = await browser.newContext({
    colorScheme: SCHEME,
    viewport: MOBILE ? { width: 390, height: 844 } : { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    isMobile: MOBILE, hasTouch: MOBILE,
  });
  await context.addInitScript(OBSERVE);
  const page = await context.newPage();
  await page.goto(BASE + '/login');
  await page.evaluate((t) => localStorage.setItem('edify_theme', t), THEME);
  await page.fill('input[name=email]', EMAIL);
  await page.fill('input[name=password]', 'edify');
  await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
  await page.waitForLoadState('load');
  await page.waitForTimeout(1500);

  const cdp = await context.newCDPSession(page);
  if (STANDALONE) await cdp.send('Emulation.setEmulatedMedia', { features: [{ name: 'display-mode', value: 'standalone' }, { name: 'prefers-color-scheme', value: SCHEME }] });
  if (NETS[NET]) { await cdp.send('Network.enable'); await cdp.send('Network.emulateNetworkConditions', NETS[NET]); }
  if (CPU > 1) await cdp.send('Emulation.setCPUThrottlingRate', { rate: CPU });

  let hrefs = HREFS;
  if (!hrefs) {
    hrefs = await page.$$eval('.app-sidebar__item[href]', (els) => els.map((e) => e.getAttribute('href')).filter((h) => h && h.startsWith('/')));
    hrefs = [...new Set(hrefs)].slice(0, MAX_PAGES);
  }
  const start = new URL(page.url()).pathname;
  hrefs.push(start);

  const frames = [];
  let seq = 0; let label = 'warmup';
  cdp.on('Page.screencastFrame', (f) => {
    const name = `${String(seq++).padStart(5, '0')}.jpg`;
    fs.writeFileSync(path.join(OUT, name), Buffer.from(f.data, 'base64'));
    frames.push({ name, ts: f.metadata.timestamp, label });
    cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }).catch(() => {});
  });
  await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 50, everyNthFrame: 1, maxWidth: 720, maxHeight: 450 });

  const navs = [];
  for (const href of hrefs) {
    label = href;
    const selector = MOBILE ? `a[href="${href}"]:visible` : `.app-sidebar__item[href="${href}"]:visible`;
    const link = page.locator(selector).first();
    if (process.env.COLD === '1') { await cdp.send('Network.clearBrowserCache'); }
    const clickedAt = Date.now() / 1000;
    let viaClick = true;
    try {
      await Promise.all([page.waitForNavigation({ waitUntil: 'commit', timeout: 60000 }), link.click({ timeout: 3000, noWaitAfter: true })]);
    } catch (e) { console.log("clickfail", String(e).slice(0,300));
      viaClick = false;
      await page.goto(BASE + href, { waitUntil: 'commit', timeout: 60000 });
    }
    const committedAt = Date.now() / 1000;
    await page.waitForLoadState('load', { timeout: 60000 });
    await page.waitForTimeout(2500);
    const m = await page.evaluate(() => {
      const n = performance.getEntriesByType('navigation')[0];
      const res = performance.getEntriesByType('resource');
      return {
        url: location.pathname, activation: n.activationStart || 0, deliveryType: n.deliveryType || '',
        ttfb: Math.round(n.responseStart), responseEnd: Math.round(n.responseEnd), dcl: Math.round(n.domContentLoadedEventEnd), load: Math.round(n.loadEventEnd),
        fcp: Math.round(window.__a.fcp), htmlKB: Math.round(n.decodedBodySize / 1024), htmlTransferKB: Math.round(n.transferSize / 1024),
        requests: res.length, netRequests: res.filter((r) => r.transferSize > 0).length,
        transferKB: Math.round(res.reduce((s, r) => s + (r.transferSize || 0), 0) / 1024),
        domNodes: document.getElementsByTagName('*').length,
        cls: +window.__a.shifts.reduce((s, e) => s + e.v, 0).toFixed(4), shifts: window.__a.shifts.slice(0, 12),
        longTasks: window.__a.long.length, longTaskMs: window.__a.long.reduce((s, e) => s + e.d, 0), longest: Math.max(0, ...window.__a.long.map((e) => e.d)),
        mutationsAfterFcp: window.__a.mutationsAfterFcp, mut: window.__a.mut,
        theme: document.documentElement.dataset.theme, bg: getComputedStyle(document.body).backgroundColor,
        htmlBg: getComputedStyle(document.documentElement).backgroundColor,
      };
    });
    navs.push({ href, viaClick, clickedAt, committedAt, ...m });
    console.log(JSON.stringify({ href, viaClick, ttfb: m.ttfb, fcp: m.fcp, dcl: m.dcl, load: m.load, cls: m.cls, long: m.longTaskMs, mutAfterFcp: m.mutationsAfterFcp, req: m.netRequests, kb: m.transferKB, theme: m.theme, bg: m.bg }));
  }
  await cdp.send('Page.stopScreencast');
  fs.writeFileSync(path.join(OUT, 'run.json'), JSON.stringify({ config: { SCHEME, THEME, NET, CPU, STANDALONE, MOBILE, EMAIL }, navs, frames }, null, 1));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
