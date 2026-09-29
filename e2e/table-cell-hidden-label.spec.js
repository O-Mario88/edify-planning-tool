/*
 * A label the page hides stays hidden in a table cell.
 *
 * micro-ux.js marks a cell's child that the page hides — a phone-only label
 * (`hidden`, `sm:hidden`), an `x-cloak`, a record-field label — with
 * `edify-cell-hidden`, and consistency.css keeps a marked child hidden from
 * 768px up ("a child the page hides at this width stays hidden, marker or
 * not"). The cell-text rule that lays a cell's text children on one line
 * (`display: inline !important`, about 0,12,4) out-ranked that hide rule
 * (0,5,3), so a marked `span`, `small` or `p` — which micro-ux also marks as
 * cell text — was put back on the line: "Name phone only" on a 1280px screen
 * (2026-09-29). Below 768px the same rule showed a child the page hides at
 * every width.
 *
 * Served as a static page with the stylesheets base.html serves, in its
 * order, and the real script, so the journey needs no server state.
 */
const { test, expect } = require('@playwright/test');
const path = require('path');
const { snapshotServer } = require('./helpers/snapshot-server');

test.use({ video: 'off', trace: 'off', serviceWorkers: 'block' });

const STYLES = [
  'build/css/main.css',
  'build/css/design-system.css',
  'build/css/components.css',
  'build/css/pages.css',
  'build/css/platform.css',
  'build/css/consistency.css',
  'build/css/components/mobile-micro-ux.css',
  'build/css/components/responsive-system.css',
  'build/css/components/interactions.css',
].map((href) => `<link rel="stylesheet" href="/static/${href}">`).join('\n');

const PAGE = `<!doctype html><html class="theme-light"><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
${STYLES}
<script defer src="/static/js/micro-ux.js"></script>
</head><body><main id="main-content">
<table id="people"><tbody>
  <tr>
    <td>Kampala Primary <span class="hidden" data-always>phone only</span></td>
    <td>Mukono <span class="sm:hidden" data-phone>district</span></td>
    <td><span data-owner>Officer One</span><small class="md:hidden" data-phone-small>CCEO</small></td>
    <td>12</td>
  </tr>
  <tr>
    <td>Wakiso Hill School <small data-caption>SCH-0042</small></td>
    <td>Wakiso</td>
    <td><span data-owner>Officer Two</span></td>
    <td>7</td>
  </tr>
</tbody></table>
</main></body></html>`;

async function open(page, server, width) {
  await page.setViewportSize({ width, height: 800 });
  await page.goto(server.origin + '/page');
  await expect(page.locator('#people td').first()).toHaveClass(/edify-cell/);
}

test.describe('a hidden-marked text child in a table cell', () => {
  let server;
  test.beforeAll(async () => {
    server = await snapshotServer(path.resolve(__dirname, '..'));
    server.setHtml(PAGE);
  });
  test.afterAll(async () => {
    await server.close();
  });

  for (const width of [768, 1280]) {
    test(`stays hidden at ${width}px while the name beside it shows`, async ({ page }) => {
      await open(page, server, width);
      const first = page.locator('#people tr').nth(0);

      // The row's identity: bare text wrapped as the name, the label marked.
      const name = first.locator('td').nth(0).locator('> .edify-cell-name');
      await expect(name).toHaveText('Kampala Primary');
      await expect(name).toBeVisible();
      const always = first.locator('[data-always]');
      await expect(always).toHaveClass(/edify-cell-hidden/);
      await expect(always).toHaveClass(/edify-cell-text/);
      await expect(always).toBeHidden();

      // A phone-only span after bare text, and a phone-only small after a name.
      await expect(first.locator('td').nth(1)).toContainText('Mukono');
      await expect(first.locator('[data-phone]')).toHaveClass(/edify-cell-hidden/);
      await expect(first.locator('[data-phone]')).toBeHidden();
      await expect(first.locator('[data-owner]')).toBeVisible();
      await expect(first.locator('[data-phone-small]')).toHaveClass(/edify-cell-hidden/);
      await expect(first.locator('[data-phone-small]')).toBeHidden();

      // A caption the page shows is not marked, and stays on the line.
      const caption = page.locator('#people tr').nth(1).locator('[data-caption]');
      await expect(caption).not.toHaveClass(/edify-cell-hidden/);
      await expect(caption).toBeVisible();
      await expect(page.locator('#people tr').nth(1).locator('td').first().locator('> .edify-cell-name')).toBeVisible();
    });
  }

  test('on a phone the page decides: a phone-only label shows, a hidden one does not', async ({ page }) => {
    await open(page, server, 360);
    const first = page.locator('#people tr').nth(0);
    await expect(first.locator('td').nth(0).locator('> .edify-cell-name')).toBeVisible();
    await expect(first.locator('[data-always]')).toBeHidden();
    await expect(first.locator('[data-phone]')).toBeVisible();
    await expect(first.locator('[data-phone-small]')).toBeVisible();
    await expect(page.locator('#people tr').nth(1).locator('[data-caption]')).toBeVisible();
  });
});
