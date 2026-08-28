#!/usr/bin/env node
/* Attribute synchronous style-recalculation cost to top-level rules in one
 * stylesheet. The browser's CSSOM preserves nested media rules, which makes
 * this safer than slicing CSS text at braces. This is a diagnostic: it never
 * edits the stylesheet or application data. */
import { chromium } from 'playwright';

const baseURL = process.env.EDIFY_BASE_URL || 'http://127.0.0.1:8000';
const route = process.argv[2] || '/analytics';
const stylesheetNeedle = process.argv[3] || '/static/css/consistency.css';
const repetitions = Number(process.env.EDIFY_RECALC_REPETITIONS || 3);
const chunkSize = Number(process.env.EDIFY_RECALC_CHUNK_SIZE || 24);
const ruleStart = Number(process.env.EDIFY_RULE_START || 0);
const ruleEnd = Number(process.env.EDIFY_RULE_END || Number.MAX_SAFE_INTEGER);
const disableAlso = (process.env.EDIFY_DISABLE_ALSO || '').split(',').filter(Boolean);
const targetSelector = process.env.EDIFY_RECALC_TARGET || 'main > *';
const omitPattern = process.env.EDIFY_OMIT_PATTERN || '';

function median(values) {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
}

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
await page.goto(`${baseURL}/login`, { waitUntil: 'domcontentloaded' });
if (page.url().includes('/login')) {
  await page.locator('input[name="email"]').fill(process.env.EDIFY_TEST_EMAIL || 'admin@edify.org');
  await page.locator('input[name="password"]').fill(process.env.EDIFY_TEST_PASSWORD || 'edify');
  await Promise.all([
    page.waitForURL((url) => !url.pathname.endsWith('/login')),
    page.locator('button[type="submit"]').click(),
  ]);
}
await page.goto(`${baseURL}${route}`, { waitUntil: 'networkidle' });
for (const needle of disableAlso) {
  await page.locator(`link[href*="${needle}"]`).evaluate((node) => { node.disabled = true; });
}

const session = await page.context().newCDPSession(page);
await session.send('Performance.enable');

async function recalcMedian() {
  const samples = [];
  for (let i = 0; i < repetitions; i += 1) {
    const before = await session.send('Performance.getMetrics');
    await page.evaluate(({ iteration, selector }) => {
      const target = document.querySelector(selector) || document.querySelector('main');
      target.classList.toggle(`edify-recalc-probe-${iteration}`);
      void getComputedStyle(target).color;
    }, { iteration: i, selector: targetSelector });
    const after = await session.send('Performance.getMetrics');
    const metric = (result, name) => result.metrics.find((item) => item.name === name).value;
    samples.push((metric(after, 'RecalcStyleDuration') - metric(before, 'RecalcStyleDuration')) * 1000);
  }
  return Number(median(samples).toFixed(2));
}

const sheet = page.locator(`link[href*="${stylesheetNeedle}"]`);
if (await sheet.count() !== 1) throw new Error(`Expected one stylesheet matching ${stylesheetNeedle}`);
const ruleInfo = await page.evaluate((needle) => {
  const owner = document.querySelector(`link[href*="${needle}"]`);
  const cssSheet = Array.from(document.styleSheets).find((candidate) => candidate.ownerNode === owner);
  return Array.from(cssSheet.cssRules).map((rule, index) => ({
    index,
    cssText: rule.cssText,
    label: rule.selectorText || rule.conditionText || rule.cssText.slice(0, 90),
  }));
}, stylesheetNeedle);

const baselineMs = await recalcMedian();
await sheet.evaluate((node) => { node.disabled = true; });
const withoutStylesheetMs = await recalcMedian();
const chunks = [];
let withoutPatternMs = null;
if (omitPattern) {
  const retained = ruleInfo.filter((rule) => !rule.cssText.includes(omitPattern))
    .map((rule) => rule.cssText).join('\n');
  await page.evaluate((text) => {
    const style = document.createElement('style');
    style.id = 'edify-attribution-pattern-style';
    style.textContent = text;
    document.head.appendChild(style);
    void getComputedStyle(document.querySelector('main')).color;
  }, retained);
  withoutPatternMs = await recalcMedian();
  await page.evaluate(() => document.getElementById('edify-attribution-pattern-style')?.remove());
}
for (let start = ruleStart; start < Math.min(ruleInfo.length, ruleEnd); start += chunkSize) {
  const end = Math.min(ruleInfo.length, ruleEnd, start + chunkSize);
  const css = ruleInfo.filter((rule) => rule.index < start || rule.index >= end)
    .map((rule) => rule.cssText).join('\n');
  await page.evaluate(({ text, id }) => {
    document.getElementById(id)?.remove();
    const style = document.createElement('style');
    style.id = id;
    style.textContent = text;
    document.head.appendChild(style);
  }, { text: css, id: 'edify-attribution-style' });
  await page.evaluate(() => void getComputedStyle(document.querySelector('main')).color);
  const omittedMs = await recalcMedian();
  chunks.push({
    start,
    end: end - 1,
    firstRule: ruleInfo[start].label,
    omittedMs,
    improvementMs: Number((baselineMs - omittedMs).toFixed(2)),
  });
  await page.evaluate(() => document.getElementById('edify-attribution-style')?.remove());
}

console.log(JSON.stringify({
  route,
  stylesheetNeedle,
  ruleCount: ruleInfo.length,
  repetitions,
  targetSelector,
  baselineMs,
  withoutStylesheetMs,
  omitPattern,
  withoutPatternMs,
  chunks: chunks.sort((a, b) => b.improvementMs - a.improvementMs),
}, null, 2));
await browser.close();
