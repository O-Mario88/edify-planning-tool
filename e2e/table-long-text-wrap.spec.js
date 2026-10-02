const { test, expect } = require('@playwright/test');
const { snapshotServer } = require('./helpers/snapshot-server');
const path = require('path');

/* Long text wraps before a table scrolls (owner, 2026-10-02). A record table
 * keeps every cell on one line and scrolls sideways when it is wider than its
 * card. On a laptop or desktop, a table that wrapping would make fit now
 * wraps its long text columns and its over-long headings instead; one that
 * would still scroll is left alone, and nothing wraps on a phone.
 * static/js/micro-ux.js (wrapLongText), static/css/components/interactions.css. */

test.use({ video: 'off', trace: 'off', serviceWorkers: 'block' });

const sentence = 'Follow up on the school improvement plan with the head teacher and the board';
const row = `<tr><td>1650</td><td>Central Division Church of Uganda Primary</td><td>${sentence}</td><td>6 Oct 2026</td><td>UGX 62,000</td><td><button type="button">Actions</button></td></tr>`;
const page_html = (rows) => `<html class="light"><head>
<link rel="stylesheet" href="/static/css/design-system.css">
<link rel="stylesheet" href="/static/css/consistency.css">
<link rel="stylesheet" href="/static/css/components/mobile-micro-ux.css">
<link rel="stylesheet" href="/static/css/components/interactions.css">
<script defer src="/static/js/micro-ux.js"></script></head>
<body><main><h1>Plan</h1><div id="card" style="inline-size:var(--card)"><div class="overflow-x-auto"><table class="edify-record-table" data-mobile-table="scroll" style="inline-size:max-content">
<thead><tr><th>School ID</th><th>School name</th><th>Purpose of visit</th><th>Cluster planned from the visit</th><th>Cost</th><th>Actions</th></tr></thead>
<tbody>${rows}</tbody></table></div></div></main></body></html>`;

async function measure(page) {
  return page.evaluate(() => {
    const table = document.querySelector('table');
    const region = table.parentElement;
    return {
      overflow: region.scrollWidth - region.clientWidth,
      wrapped: table.querySelectorAll('.edify-cell-wrap').length,
      rowHeight: Math.round(table.querySelector('tbody tr').getBoundingClientRect().height),
    };
  });
}

test('a table that wrapping makes fit wraps; one that would still scroll, and any table on a phone, does not', async ({ page }) => {
  const server = await snapshotServer(path.resolve(__dirname, '..'));
  try {
    server.setHtml(page_html(row.repeat(3)));
    await page.setViewportSize({ width: 1600, height: 900 });
    await page.goto(server.origin + '/page');

    // Natural width, one line per cell.
    await page.addStyleTag({ content: ':root{--card:1500px}' });
    const natural = await page.evaluate(() => document.querySelector('table').scrollWidth);
    expect(natural).toBeGreaterThan(900);

    // A card a little narrower than the table: the long sentence wraps and the table fits.
    await page.evaluate(width => { document.documentElement.style.setProperty('--card', width + 'px'); window.dispatchEvent(new Event('resize')); }, natural - 120);
    await expect.poll(async () => (await measure(page)).wrapped).toBeGreaterThan(0);
    const fitted = await measure(page);
    expect(fitted.overflow).toBeLessThanOrEqual(1);
    expect(fitted.rowHeight).toBeGreaterThan(40);
    // The figures and the control stay on one line.
    expect(await page.locator('tbody tr').first().locator('td').nth(4).evaluate(cell => getComputedStyle(cell).whiteSpace)).toBe('nowrap');

    // It holds still: the same overflow and marks over twenty frames.
    const samples = await page.evaluate(() => new Promise(done => {
      const seen = new Set(); let frames = 0;
      const tick = () => {
        const table = document.querySelector('table');
        seen.add(table.parentElement.scrollWidth + ':' + table.querySelectorAll('.edify-cell-wrap').length);
        frames += 1;
        if (frames < 20) requestAnimationFrame(tick); else done(seen.size);
      };
      requestAnimationFrame(tick);
    }));
    expect(samples).toBe(1);

    // A card far too narrow to be saved by wrapping: nothing wraps, the table scrolls as it always did.
    await page.evaluate(() => { document.documentElement.style.setProperty('--card', '420px'); window.dispatchEvent(new Event('resize')); });
    await expect.poll(async () => (await measure(page)).wrapped).toBe(0);
    expect((await measure(page)).overflow).toBeGreaterThan(100);

    // A phone: nothing wraps whatever the width.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.evaluate(() => { document.documentElement.style.setProperty('--card', '100%'); });
    await page.waitForTimeout(400);
    expect((await measure(page)).wrapped).toBe(0);
  } finally {
    await server.close();
  }
});
