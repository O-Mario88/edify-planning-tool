'use strict';
const { chromium } = require('@playwright/test');
const BASE = process.env.BASE || 'http://127.0.0.1:8376';
(async () => {
  const browser = await chromium.launch();
  const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 } })).newPage();
  await page.goto(BASE + '/login');
  await page.fill('input[name=email]', process.env.EMAIL);
  await page.fill('input[name=password]', 'edify');
  await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
  await page.goto(BASE + process.env.PATHNAME, { waitUntil: 'load', timeout: 180000 });
  await page.waitForTimeout(4000);
  const out = await page.evaluate(async () => {
    const full = () => { // force a whole-document style recalculation and time it
      const samples = [];
      for (let i = 0; i < 3; i++) {
        if (!window.__probe) { window.__probe = document.createElement('style'); document.head.appendChild(window.__probe); }
        window.__probe.textContent = '*{--audit-probe:' + Math.random() + '}';
        const t = performance.now(); getComputedStyle(document.body).color; void document.body.offsetWidth; samples.push(performance.now() - t);
      }
      samples.sort((a, b) => a - b); return +samples[1].toFixed(1);
    };
    const one = () => { // a single-element class change, as the enhancer scripts make hundreds of
      const el = document.querySelector('main td') || document.querySelector('main div');
      const samples = [];
      for (let i = 0; i < 5; i++) { if (el.hasAttribute('aria-hidden')) el.removeAttribute('aria-hidden'); else el.setAttribute('aria-hidden', 'true'); const t = performance.now(); getComputedStyle(el).color; void el.offsetWidth; samples.push(performance.now() - t); }
      samples.sort((a, b) => a - b); return +samples[2].toFixed(1);
    };
    const res = { elements: document.getElementsByTagName('*').length, baselineFull: full(), baselineOne: one(), sheets: [] };
    const links = Array.from(document.querySelectorAll('link[rel=stylesheet]'));
    for (const l of links) {
      l.disabled = true; await new Promise((r) => setTimeout(r, 50));
      res.sheets.push({ sheet: l.href.split('/static/')[1].split('?')[0].replace(/\.[0-9a-f]{12}\./, '.'), fullWithout: full(), oneWithout: one() });
      l.disabled = false; await new Promise((r) => setTimeout(r, 50)); full();
    }
    for (const l of links) l.disabled = true; await new Promise((r) => setTimeout(r, 50));
    res.noCssFull = full(); res.noCssOne = one();
    return res;
  });
  console.log('elements', out.elements, '| full recalc', out.baselineFull, 'ms | single-element class change', out.baselineOne, 'ms | with no stylesheets: full', out.noCssFull, 'one', out.noCssOne);
  for (const s of out.sheets.sort((a, b) => a.fullWithout - b.fullWithout)) console.log(`  without ${s.sheet.padEnd(48)} full ${String(s.fullWithout).padStart(7)} ms (saves ${(out.baselineFull - s.fullWithout).toFixed(0)})   one ${String(s.oneWithout).padStart(6)} ms (saves ${(out.baselineOne - s.oneWithout).toFixed(1)})`);
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
