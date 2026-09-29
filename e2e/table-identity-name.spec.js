/*
 * A row's name stays on the row.
 *
 * micro-ux.js wraps a row's identity (its first cell, or the one after a
 * selection box) in <span class="edify-cell-name"> when the name is bare
 * text, so the identity measure holds when the column pins. The cell pass
 * reads first and writes after: the read phase flags which of the cell's
 * children the page hides at this width, and the write phase marks them
 * `edify-cell-hidden` (display: none, consistency.css) by index.
 *
 * The name span was written between the two, in front of the children the
 * flags were read for, and the marks were applied with
 * `classList.toggle(name, flags[index])`. So:
 *
 *  - a cell holding only text had no flag at index 0, and
 *    `toggle(name, undefined)` is a plain toggle: it ADDED the mark and the
 *    row's name rendered blank ("Evidence submission overdue" under Top
 *    Execution Issues, 2026-09-28);
 *  - a cell with text before its elements had every flag moved one child
 *    along: the name took the first element's flag, and a phone-only label
 *    lost its own and showed again.
 *
 * Served as a static page with the real stylesheet and script, so the
 * journey needs no server state.
 */
const { test, expect } = require('@playwright/test');
const path = require('path');
const { snapshotServer } = require('./helpers/snapshot-server');

test.use({ video: 'off', trace: 'off', serviceWorkers: 'block' });

const PAGE = `<!doctype html><html class="theme-light"><head>
<link rel="stylesheet" href="/static/css/design-system.css">
<link rel="stylesheet" href="/static/css/components.css">
<link rel="stylesheet" href="/static/css/consistency.css">
<script defer src="/static/js/micro-ux.js"></script>
</head><body><main id="main-content">
<table id="issues"><tbody>
  <tr><th scope="row">Evidence submission overdue</th><td>160</td></tr>
  <tr><td>Partner execution delay <span class="hidden" data-phone-label>phone only</span><small data-caption>by IA</small></td><td>100</td></tr>
  <tr><td><span class="hidden" data-element-only>phone only</span><span data-element-name>Finance closure pending</span></td><td>1</td></tr>
</tbody></table>
<table id="choices"><tbody>
  <tr><td><input type="checkbox" aria-label="Choose Kampala Primary"></td><td>Kampala Primary</td><td>3</td></tr>
</tbody></table>
</main></body></html>`;

test('a row whose name is bare text keeps its name visible', async ({ page }) => {
  const server = await snapshotServer(path.resolve(__dirname, '..'));
  try {
    server.setHtml(PAGE);
    await page.goto(server.origin + '/page');
    await expect(page.locator('#issues th')).toHaveClass(/edify-cell/);

    // Text alone: the name is written, and never marked hidden.
    const alone = page.locator('#issues tr').nth(0).locator('th > .edify-cell-name');
    await expect(alone).toHaveText('Evidence submission overdue');
    await expect(alone).not.toHaveClass(/edify-cell-hidden/);
    await expect(alone).toBeVisible();

    // Text before elements: each flag stays with the child it was read for.
    const mixed = page.locator('#issues tr').nth(1).locator('td').first();
    await expect(mixed.locator('> .edify-cell-name')).toHaveText('Partner execution delay');
    await expect(mixed.locator('> .edify-cell-name')).not.toHaveClass(/edify-cell-hidden/);
    await expect(mixed.locator('> .edify-cell-name')).toBeVisible();
    // The mark is the script's half; consistency.css keeps a marked child
    // hidden from 768px up (table-cell-hidden-label.spec.js).
    await expect(mixed.locator('[data-phone-label]')).toHaveClass(/edify-cell-hidden/);
    await expect(mixed.locator('[data-phone-label]')).toBeHidden();
    await expect(mixed.locator('[data-caption]')).not.toHaveClass(/edify-cell-hidden/);
    await expect(mixed.locator('[data-caption]')).toBeVisible();

    // Elements only: nothing is wrapped, and the flags apply as they were read.
    const elements = page.locator('#issues tr').nth(2).locator('td').first();
    await expect(elements.locator('.edify-cell-name')).toHaveCount(0);
    await expect(elements.locator('[data-element-only]')).toHaveClass(/edify-cell-hidden/);
    await expect(elements.locator('[data-element-name]')).not.toHaveClass(/edify-cell-hidden/);
    await expect(elements.locator('[data-element-name]')).toBeVisible();

    // The identity after a selection box.
    const chosen = page.locator('#choices td').nth(1).locator('> .edify-cell-name');
    await expect(chosen).toHaveText('Kampala Primary');
    await expect(chosen).not.toHaveClass(/edify-cell-hidden/);
    await expect(chosen).toBeVisible();

    // Rows swapped in later (htmx) go through the same pass.
    await page.evaluate(() => {
      const body = document.querySelector('#issues tbody');
      body.innerHTML = '<tr><th scope="row">IA verification pending</th><td>2</td></tr>';
      body.dispatchEvent(new CustomEvent('htmx:afterSettle', { bubbles: true }));
    });
    const swapped = page.locator('#issues th > .edify-cell-name');
    await expect(swapped).toHaveText('IA verification pending');
    await expect(swapped).not.toHaveClass(/edify-cell-hidden/);
    await expect(swapped).toBeVisible();
  } finally {
    await server.close();
  }
});
