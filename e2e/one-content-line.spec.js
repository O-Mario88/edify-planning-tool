const { test, expect } = require('@playwright/test');
test.use({ video: 'off', trace: 'off', serviceWorkers: 'block' });
const path = require('node:path');
const { snapshotServer } = require('./helpers/snapshot-server');

/* One content line (owner, 2026-10-02): "fix all the padding on every card so
 * that everything is well aligned ... content inside cards, table padding,
 * tabs, content inside kpi strips" and "tabs inside the cards should be
 * aligned with the content inside the cards".
 *
 * Before it, a table card started its content 12px in, a plain card 16px, a
 * band inside a padded card 32px, and a tab strip in an edge-to-edge card sat
 * on the card's edge. These are the card anatomies the platform is written
 * in, drawn with the real stylesheets and micro-ux.js and no database: in
 * each, the title, the tabs, the figures, the first column of the table and
 * the pager start on the same line, --edify-card-inset from the card's edge.
 */
const root = path.resolve(__dirname, '..');
const sheets = ['fonts.css', 'main.css', 'design-system.css', 'components.css', 'pages.css', 'drawers.css', 'app.css', 'platform.css', 'components/interactions.css', 'consistency.css', 'components/mobile-micro-ux.css'];
const servers = new WeakMap();
test.afterEach(async ({ page }) => { await servers.get(page)?.close(); });

const table = `
  <div class="overflow-x-auto"><table class="edify-record-table w-full">
    <thead><tr><th class="px-5 py-3">School ID</th><th class="px-3 py-3">School</th><th class="px-5 py-3">Status</th></tr></thead>
    <tbody><tr><td class="px-5 py-3">1650</td><td class="px-3 py-3">Central Division Primary</td><td class="px-5 py-3">Planned</td></tr></tbody>
  </table></div>`;
const pager = `<nav class="edify-pagination px-4 py-3" aria-label="Schools pages"><p class="edify-pagination__summary">Showing 1–1 of 1</p></nav>`;
const kpis = `<section class="context-metrics" data-context-metrics><div class="context-metrics__sentence" role="list">
  <span class="context-metrics__fact" role="listitem"><span class="context-metrics__text"><span class="context-metrics__label">Officers on my team</span><strong class="context-metrics__value">5</strong><span class="context-metrics__helper">CCEOs you line-manage</span></span></span>
  <span class="context-metrics__fact" role="listitem"><span class="context-metrics__text"><span class="context-metrics__label">Team handoffs waiting on you for a decision this month</span><strong class="context-metrics__value">0 of 5</strong><span class="context-metrics__helper">on track</span></span></span>
  <span class="context-metrics__fact" role="listitem"><span class="context-metrics__text"><span class="context-metrics__label">SSA coverage</span><strong class="context-metrics__value">0%</strong><span class="context-metrics__helper">0 of 155 schools confirmed this financial year</span></span></span>
</div></section>`;
const tabs = `<nav class="oversight-entity-tabs" aria-label="Work"><a class="oversight-entity-tabs__link is-active" href="#a">Schools assigned 1</a><a class="oversight-entity-tabs__link" href="#b">Visits 0</a></nav>`;

const cards = {
  // An edge-to-edge card: header, tabs, loose text, table, pager.
  shell: `<section class="card p-0 overflow-hidden" data-card>
    <header class="px-5 py-4"><h2 data-line="title">Build Africa</h2></header>
    ${tabs.replace('<nav', '<nav data-line="tabs"')}
    <p data-line="text">Schools assigned (1)</p>
    ${table}${pager}</section>`,
  // The same card written without `p-0`: its sections pad themselves and rule
  // themselves off. It was padded twice.
  unmarkedShell: `<div class="edify-surface rounded-surface border" data-card>
    <div class="px-5 py-3 border-b"><h2 data-line="title">Operational decisions</h2></div>
    ${kpis}${table}</div>`,
  // A padded card: its band and its table bleed through the padding.
  padded: `<section class="edify-surface rounded-surface border p-5" data-card>
    <h2 class="edify-table-titlebar" data-line="title">Reach by district</h2>
    <p data-line="text">Least-reached districts first.</p>
    ${table}</section>`,
  // The dashboards' card family: a header band over figures and a table.
  family: `<section class="edify-surface rounded-surface border rpl-card" data-card>
    <header class="rpl-card__header"><div class="rpl-card__heading"><h2 class="rpl-card__title" data-line="title">Needs your action</h2></div></header>
    ${kpis}${table}</section>`,
  // A plain padded card holding a table further down.
  leaf: `<div class="edify-surface rounded-surface border p-4" data-card>
    <h3 data-line="title">Coverage</h3>
    <div class="space-y-2"><p data-line="text">By district</p>${table}</div></div>`,
};

async function render(page, html, width = 1280) {
  await page.setViewportSize({ width, height: 900 });
  let server = servers.get(page);
  if (!server) { server = await snapshotServer(root); servers.set(page, server); }
  server.setHtml(`<html class="theme-light light"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">${sheets.map((s) => `<link rel="stylesheet" href="/static/css/${s}">`).join('')}</head><body><main style="padding:24px;max-width:none"><div class="space-y-4">${html}</div></main><script src="/static/js/micro-ux.js"></script></body></html>`);
  await page.goto(server.origin + '/page');
  await page.evaluate(() => document.fonts.ready);
  // micro-ux marks sectioned cards before paint and fits tables after it.
  await page.waitForFunction(() => !document.querySelector('table') || document.querySelector('[data-table-scroll-region]'));
  await page.waitForTimeout(150);
}

/* Where each part of the card starts, from the card's inner edge: the first
 * glyph of the title and the loose text, the box of the tab strip and of the
 * strip of figures, the first glyph of the first heading and first body cell,
 * the pager's first glyph. */
const measure = () => {
  const card = document.querySelector('[data-card]');
  const edge = card.getBoundingClientRect().left + parseFloat(getComputedStyle(card).borderLeftWidth || 0);
  const glyph = (el) => {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (!node.nodeValue.trim()) continue;
      const range = document.createRange(); range.selectNodeContents(node);
      const rect = range.getClientRects()[0];
      if (rect && rect.width) return rect.left;
    }
    return null;
  };
  const out = {};
  const put = (name, value) => { if (value !== null && value !== undefined) out[name] = Math.round((value - edge) * 10) / 10; };
  card.querySelectorAll('[data-line]').forEach((el) => put(el.dataset.line, el.dataset.line === 'tabs' ? el.getBoundingClientRect().left : glyph(el)));
  const strip = card.querySelector('.context-metrics__sentence');
  if (strip) put('figures', strip.getBoundingClientRect().left);
  const th = card.querySelector('thead th'); if (th) put('column', glyph(th));
  const td = card.querySelector('tbody td'); if (td) put('row', glyph(td));
  const summary = card.querySelector('.edify-pagination__summary'); if (summary) put('pager', glyph(summary));
  // The far side: the last column's padding, where the table fits its card
  // (a phone scrolls it, and its far side is off the screen).
  const lastTh = card.querySelector('thead th:last-child');
  const region = card.querySelector('[data-table-scroll-region]');
  const right = card.getBoundingClientRect().right - parseFloat(getComputedStyle(card).borderRightWidth || 0);
  if (lastTh && region && region.scrollWidth <= region.clientWidth + 1) out.lastColumnEnd = Math.round((right - lastTh.getBoundingClientRect().right + parseFloat(getComputedStyle(lastTh).paddingRight)) * 10) / 10;
  out.pageOverflow = document.documentElement.scrollWidth > innerWidth;
  out.pokes = [...card.children].filter((child) => {
    const r = child.getBoundingClientRect(); const c = card.getBoundingClientRect();
    return r.width && (r.left < c.left - 1 || r.right > c.right + 1);
  }).length;
  return out;
};

for (const [name, html] of Object.entries(cards)) {
  for (const width of [1280, 390]) {
    test(`${name} card at ${width}px: every part starts on the card's line`, async ({ page }) => {
      await render(page, html, width);
      const inset = await page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--edify-surface-padding-inline')) * parseFloat(getComputedStyle(document.documentElement).fontSize));
      const at = await page.evaluate(measure);
      const { pageOverflow, pokes, lastColumnEnd, ...lines } = at;
      expect(Object.keys(lines).length, JSON.stringify(at)).toBeGreaterThan(2);
      for (const [part, x] of Object.entries(lines)) {
        expect(Math.abs(x - inset), `${part} starts ${x}px in, the line is ${inset}px: ${JSON.stringify(at)}`).toBeLessThanOrEqual(1.5);
      }
      // The table's last column ends the same distance from the other edge.
      if (lastColumnEnd !== undefined) expect(Math.abs(lastColumnEnd - inset), JSON.stringify(at)).toBeLessThanOrEqual(1.5);
      expect(pokes, 'nothing bleeds out of the card').toBe(0);
      expect(pageOverflow, 'the page does not scroll sideways').toBe(false);
    });
  }
}

test('a table inside a drawer keeps the cell padding: the line is the card\'s', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  const server = await snapshotServer(root); servers.set(page, server);
  server.setHtml(`<html class="theme-light light"><head><meta charset="utf-8">${sheets.map((s) => `<link rel="stylesheet" href="/static/css/${s}">`).join('')}</head><body><div class="drawer-body">${table}</div></body></html>`);
  await page.goto(server.origin + '/page');
  const padding = await page.evaluate(() => ['thead th:first-child', 'tbody td:first-child', 'thead th:last-child'].map((sel) => { const cs = getComputedStyle(document.querySelector(sel)); return sel.includes('last') ? cs.paddingRight : cs.paddingLeft; }));
  expect(padding).toEqual(['12px', '12px', '12px']);
});

test('the figures of a strip sit on one line, and so do their helpers', async ({ page }) => {
  // Six facts across 1100px: the long label wraps, the short ones do not.
  const six = kpis.replace('</div></section>', `
  <span class="context-metrics__fact" role="listitem"><span class="context-metrics__text"><span class="context-metrics__label">Schools</span><strong class="context-metrics__value">175</strong></span></span>
  <span class="context-metrics__fact" role="listitem"><span class="context-metrics__text"><span class="context-metrics__label">Team exceptions needing your action before the month closes</span><strong class="context-metrics__value">5</strong><span class="context-metrics__helper">late decisions, missing agreements and uncovered leave</span></span></span>
  <span class="context-metrics__fact" role="listitem"><span class="context-metrics__text"><span class="context-metrics__label">Open handoffs</span><strong class="context-metrics__value">0</strong><span class="context-metrics__helper">none</span></span></span>
</div></section>`);
  await render(page, `<div data-card>${six}</div>`, 1100);
  const tops = await page.evaluate(() => ({
    values: [...document.querySelectorAll('.context-metrics__value')].map((el) => Math.round(el.getBoundingClientRect().top)),
    helpers: [...document.querySelectorAll('.context-metrics__helper')].map((el) => Math.round(el.getBoundingClientRect().top)),
    labels: [...document.querySelectorAll('.context-metrics__label')].map((el) => Math.round(el.getBoundingClientRect().height)),
  }));
  // The fixture's second label wraps; without the shared rows its figure sat
  // a line below the others.
  expect(Math.max(...tops.labels)).toBeGreaterThan(Math.min(...tops.labels));
  expect(new Set(tops.values).size, JSON.stringify(tops)).toBe(1);
  expect(new Set(tops.helpers).size, JSON.stringify(tops)).toBe(1);
});
