// A calendar (or any dropdown) opened from the last field of a phone drawer
// whose content fits (owner, 2026-09-30: "Assign to partner drawer calendar
// from the cluster school list is clipped off on mobile mode not showing
// up. apply this to all related issues through out the platform").
//
// Dropdowns drop DOWN from their field (top-layer.js); with nothing below the
// field to scroll away, the calendar was squeezed into the 25px left above
// the covered bottom navigation. The layer now lengthens the sheet's content
// under the field while the panel is open, so the field rises and the
// calendar opens whole, and takes that room away again when it closes.
const { test, expect } = require('@playwright/test');
const fs = require('node:fs');
const path = require('node:path');

test.use({ video: 'off', trace: 'off', serviceWorkers: 'block', viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

const root = path.resolve(__dirname, '..');
const sheets = [
  'fonts.css', 'main.css', 'design-system.css', 'components.css', 'components/mobile-patterns.css', 'pages.css',
  'drawers.css', 'app.css', 'platform.css', 'consistency.css', 'components/mobile-micro-ux.css', 'form-refinement.css',
  'components/responsive-system.css', 'components/interactions.css',
];
// The cluster list's Assign to partner drawer, cut to its shape: the sheet,
// a short form whose last field is a date, the sticky footer, and the bottom
// navigation behind it, inert while the drawer is open.
const body = `
<div inert aria-hidden="true"><nav class="edify-bottom-nav" style="position:fixed;left:0;right:0;bottom:0;height:56px;background:#eef"></nav></div>
<div id="drawer-container"><div class="edify-drawer-root relative z-50" data-edify-drawer>
  <div class="drawer-backdrop active type-center"></div>
  <div class="drawer-surface active size-sm type-center" role="dialog" aria-modal="true" aria-labelledby="t">
    <header class="drawer-header"><h3 id="t">Assign to partner</h3></header>
    <div class="drawer-body edify-has-drawer-footer">
      <form id="form" class="space-y-4">
        <p>Each school's top eligible Catalogue recommendation goes to the partner.</p>
        <div class="space-y-1"><label for="partner">Partner</label>
          <select id="partner" name="partner_id" class="w-full h-10"><option>Select a partner…</option></select></div>
        <div class="space-y-1"><label for="target">Target date</label>
          <input id="target" type="date" name="scheduled_date" class="w-full h-10">
          <p id="help">Leave blank if the partner will choose the date.</p></div>
        <div class="drawer-footer"><button type="button">Cancel</button><button type="submit">Assign</button></div>
      </form>
    </div>
  </div>
</div></div>`;

async function open(page) {
  await page.clock.setFixedTime(new Date(2026, 8, 30, 9, 0, 0));
  await page.route('http://drawer.test/**', (route) => {
    const file = path.join(root, new URL(route.request().url()).pathname);
    if (fs.existsSync(file) && fs.statSync(file).isFile()) return route.fulfill({ path: file });
    return route.fulfill({
      contentType: 'text/html',
      body: `<html class="light"><head><meta name="viewport" content="width=device-width, initial-scale=1">
        ${sheets.map((s) => `<link rel="stylesheet" href="/static/css/${s}">`).join('')}
        <script defer src="/static/js/vendor/alpine-3.14.0.min.js"></script>
        <script defer src="/static/js/top-layer.js"></script>
        <script defer src="/static/js/date-picker.js"></script></head><body>${body}</body></html>`,
    });
  });
  await page.goto('http://drawer.test/');
  await page.waitForFunction(() => window.EdifyLayer && document.querySelectorAll('.edify-datepick').length === 1);
}

const field = (page) => page.locator('#target + .edify-datepick .edify-datepick__field');
const calendar = (page) => page.locator('.edify-datepick__pop:not([hidden])');

test('the last field of a phone drawer opens its whole calendar, below the field', async ({ page }) => {
  await open(page);
  const before = await page.locator('.drawer-surface').boundingBox();
  await field(page).click();
  await expect(calendar(page)).toBeVisible();

  const got = await page.evaluate(() => {
    const pop = document.querySelector('.edify-datepick__pop');
    const box = pop.getBoundingClientRect();
    const at = document.querySelector('#target + .edify-datepick .edify-datepick__field').getBoundingClientRect();
    return { top: box.top, bottom: box.bottom, height: box.height, needed: pop.scrollHeight, fieldBottom: at.bottom, maxHeight: pop.style.maxHeight };
  });
  // Whole: nothing of the month scrolls inside a sliver.
  expect(got.maxHeight).toBe('');
  expect(got.height).toBeGreaterThanOrEqual(got.needed);
  // Down from the field, never over it, and inside the window.
  expect(got.top).toBeGreaterThanOrEqual(got.fieldBottom);
  expect(got.bottom).toBeLessThanOrEqual(844);
  // The sheet grew upward to lift the field; the footer stays at its foot.
  const grown = await page.locator('.drawer-surface').boundingBox();
  expect(grown.height).toBeGreaterThan(before.height);
  const footer = await page.locator('.drawer-footer').boundingBox();
  expect(Math.round(footer.y + footer.height)).toBeGreaterThanOrEqual(Math.round(grown.y + grown.height) - 2);
});

test('the room is taken away again once a day is picked', async ({ page }) => {
  await open(page);
  const before = await page.locator('.drawer-surface').boundingBox();
  await field(page).click();
  await calendar(page).locator('[data-day="2026-09-29"]').click();
  await expect(calendar(page)).toHaveCount(0);
  await expect(page.locator('#target')).toHaveValue('2026-09-29');
  await expect(page.locator('[data-edify-room]')).toHaveCount(0);
  const after = await page.locator('.drawer-surface').boundingBox();
  expect(Math.round(after.height)).toBe(Math.round(before.height));
});

test('Escape closes the calendar and takes the room away too', async ({ page }) => {
  await open(page);
  await field(page).click();
  await expect(calendar(page)).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(calendar(page)).toHaveCount(0);
  await expect(page.locator('[data-edify-room]')).toHaveCount(0);
});
