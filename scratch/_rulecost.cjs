'use strict';
const fs = require('node:fs');
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
  const out = await page.evaluate(async (needle) => {
    const probe = document.createElement('style'); document.head.appendChild(probe);
    const full = (n) => { const a = []; for (let i = 0; i < (n || 3); i++) { probe.textContent = '*{--audit-probe:' + Math.random() + '}'; const t = performance.now(); getComputedStyle(document.body).color; void document.body.offsetWidth; a.push(performance.now() - t); } a.sort((x, y) => x - y); return a[Math.floor(a.length / 2)]; };
    const link = Array.from(document.querySelectorAll('link[rel=stylesheet]')).find((l) => l.href.includes(needle));
    const sheet = link.sheet; const base = full(5);
    const rules = Array.from(sheet.cssRules).map((r) => r.cssText);
    const measureWithout = (from, to) => { // remove rules [from,to) then restore
      for (let i = to - 1; i >= from; i--) sheet.deleteRule(i);
      const ms = full(3);
      for (let i = from; i < to; i++) sheet.insertRule(rules[i], i);
      return ms;
    };
    const CH = 40; const chunks = [];
    for (let i = 0; i < rules.length; i += CH) chunks.push({ from: i, to: Math.min(rules.length, i + CH), saved: base - measureWithout(i, Math.min(rules.length, i + CH)) });
    chunks.sort((a, b) => b.saved - a.saved);
    const singles = [];
    for (const c of chunks.slice(0, 8)) for (let i = c.from; i < c.to; i++) { const saved = base - measureWithout(i, i + 1); if (saved > 1.0) singles.push({ index: i, saved: +saved.toFixed(1), len: rules[i].length, text: rules[i].slice(0, 420) }); }
    singles.sort((a, b) => b.saved - a.saved);
    return { base: +base.toFixed(1), ruleCount: rules.length, chunks: chunks.slice(0, 12).map((c) => ({ ...c, saved: +c.saved.toFixed(1) })), sumTopChunks: +chunks.slice(0, 8).reduce((s, c) => s + c.saved, 0).toFixed(0), singles: singles.slice(0, 40) };
  }, process.env.SHEET || 'consistency');
  fs.writeFileSync(process.env.OUT, JSON.stringify(out, null, 1));
  console.log('base full recalc', out.base, 'ms; top-level rules', out.ruleCount, '; top 8 chunks save', out.sumTopChunks);
  console.log(JSON.stringify(out.chunks));
  for (const s of out.singles.slice(0, 25)) console.log(String(s.saved).padStart(6), 'ms  #' + s.index, 'len', s.len, '|', s.text.slice(0, 230).replace(/\s+/g, ' '));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
