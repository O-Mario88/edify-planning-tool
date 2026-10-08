// One Edify calendar for every date field (owner, 2026-09-26). The real
// stylesheets, Alpine and static/js/date-picker.js on a page of date fields,
// so what is checked is the component itself, not a seeded page around it.
const { test, expect } = require('@playwright/test');
test.use({ video: 'off', trace: 'off', serviceWorkers: 'block' });
const fs = require('node:fs');
const path = require('node:path');

const root = path.resolve(__dirname, '..');
const sheets = [
  'fonts.css', 'main.css', 'design-system.css', 'components.css', 'components/mobile-patterns.css', 'pages.css',
  'drawers.css', 'app.css', 'platform.css', 'consistency.css', 'components/mobile-micro-ux.css', 'form-refinement.css',
  'components/responsive-system.css', 'components/interactions.css',
];
const body = `
<main>
  <form id="form">
    <label for="peer">Peer</label>
    <input type="text" id="peer" class="w-full">
    <label for="visit">Visit date</label>
    <input type="date" id="visit" name="visit" value="2026-10-06" required class="w-full">
    <label for="bounded">Bounded date</label>
    <input type="date" id="bounded" name="bounded" min="2026-10-05" max="2026-10-20" value="2026-10-10">
    <div x-data="{ day: '2026-11-02' }" id="alpine">
      <label for="bound">Bound date</label>
      <input type="date" id="bound" name="bound" x-model="day">
      <output id="echo" x-text="day"></output>
    </div>
    <label>Wrapped date <input type="date" id="wrapped" name="wrapped"></label>
    <div data-native-date><input type="date" id="native-only" name="native_only"></div>
  </form>
</main>`;

async function open(page, extra = '') {
  await page.clock.setFixedTime(new Date(2026, 9, 1, 9, 0, 0));
  await page.route('http://dates.test/**', (route) => {
    const file = path.join(root, new URL(route.request().url()).pathname);
    if (fs.existsSync(file) && fs.statSync(file).isFile()) return route.fulfill({ path: file });
    return route.fulfill({
      contentType: 'text/html',
      body: `<html class="light"><head>${sheets.map((s) => `<link rel="stylesheet" href="/static/css/${s}">`).join('')}
        <script defer src="/static/js/vendor/alpine-3.14.0.min.js"></script>
        <script defer src="/static/js/date-picker.js"></script></head><body>${body}${extra}</body></html>`,
    });
  });
  await page.goto('http://dates.test/');
  const fields = 4 + (extra.match(/type="date"/g) || []).length;
  await page.waitForFunction((n) => window.Alpine && document.querySelectorAll('.edify-datepick').length === n, fields);
}

const fieldOf = (page, id) => page.locator(`#${id} + .edify-datepick .edify-datepick__field`);
const calendar = (page) => page.locator('.edify-datepick__pop:not([hidden])');

test('every date field gets the Edify field and keeps the real one', async ({ page }) => {
  await open(page);
  await expect(fieldOf(page, 'visit')).toHaveValue('Oct 6, 2026');
  await expect(page.locator('#visit')).toHaveAttribute('type', 'date');
  await expect(page.locator('#visit')).toHaveValue('2026-10-06');
  await expect(fieldOf(page, 'wrapped')).toHaveAttribute('placeholder', 'Select a date');
  // An opted-out field keeps the browser's own picker.
  await expect(page.locator('#native-only + .edify-datepick')).toHaveCount(0);
});

test('the visible field is drawn exactly like the fields around it', async ({ page }) => {
  await open(page);
  // To a hundredth of a pixel: at a phone's device scale two boxes drawn alike
  // came back 43.999996 and 43.999992 high (iPhone profile, 2026-10-08).
  const look = (selector) => page.locator(selector).evaluate((el) => {
    const s = getComputedStyle(el);
    const px = (value) => Math.round(value * 100) / 100;
    return [px(el.getBoundingClientRect().height), px(el.getBoundingClientRect().width), s.borderTopWidth, s.borderRadius, s.fontSize, s.backgroundColor];
  });
  const peer = await look('#peer');
  const field = await look('#visit + .edify-datepick .edify-datepick__field');
  expect(field.slice(0, 5)).toEqual(peer.slice(0, 5));
});

test('picking a day writes the real field and announces it once', async ({ page }) => {
  await open(page);
  await page.evaluate(() => {
    window.heard = [];
    const form = document.getElementById('form');
    ['input', 'change'].forEach((type) => form.addEventListener(type, (event) => window.heard.push(`${type}:${event.target.id}`)));
  });
  await fieldOf(page, 'visit').click();
  await expect(calendar(page)).toBeVisible();
  await expect(calendar(page).locator('[data-day="2026-10-06"]')).toHaveAttribute('aria-selected', 'true');
  await expect(calendar(page).locator('[data-day="2026-10-01"]')).toHaveAttribute('aria-current', 'date');
  await calendar(page).locator('[data-day="2026-10-14"]').click();
  await expect(calendar(page)).toHaveCount(0);
  await expect(page.locator('#visit')).toHaveValue('2026-10-14');
  await expect(fieldOf(page, 'visit')).toHaveValue('Oct 14, 2026');
  await expect(fieldOf(page, 'visit')).toBeFocused();
  expect(await page.evaluate(() => window.heard)).toEqual(['input:visit', 'change:visit']);
});

test('the keyboard opens, walks and picks, and Escape stays with the calendar', async ({ page }) => {
  await open(page);
  await page.evaluate(() => {
    window.escapes = 0;
    document.addEventListener('keydown', (event) => { if (event.key === 'Escape') window.escapes += 1; });
  });
  await fieldOf(page, 'visit').focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('.edify-datepick__day:focus')).toHaveAttribute('data-day', '2026-10-06');
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('PageDown');
  await expect(page.locator('.edify-datepick__day:focus')).toHaveAttribute('data-day', '2026-11-14');
  await page.keyboard.press('Escape');
  await expect(calendar(page)).toHaveCount(0);
  await expect(fieldOf(page, 'visit')).toBeFocused();
  // A drawer listening for Escape is not closed by the calendar's Escape.
  expect(await page.evaluate(() => window.escapes)).toBe(0);
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('PageDown');
  await page.keyboard.press('Enter');
  await expect(page.locator('#visit')).toHaveValue('2026-11-06');
});

test('the month view moves by year and month', async ({ page }) => {
  await open(page);
  await fieldOf(page, 'visit').click();
  await calendar(page).locator('.edify-datepick__caption').click();
  await calendar(page).locator('[data-go="next-year"]').click();
  await expect(calendar(page).locator('.edify-datepick__caption')).toHaveText('2027');
  await calendar(page).locator('[data-month="3"]').click();
  await expect(calendar(page).locator('.edify-datepick__caption')).toHaveText('March 2027');
  await calendar(page).locator('[data-day="2027-03-09"]').click();
  await expect(page.locator('#visit')).toHaveValue('2027-03-09');
});

test('days outside min and max cannot be picked', async ({ page }) => {
  await open(page);
  await fieldOf(page, 'bounded').click();
  const before = calendar(page).locator('[data-day="2026-10-04"]');
  await expect(before).toHaveAttribute('aria-disabled', 'true');
  await before.click({ force: true });
  await expect(page.locator('#bounded')).toHaveValue('2026-10-10');
  await expect(calendar(page).locator('[data-day="2026-10-21"]')).toHaveAttribute('aria-disabled', 'true');
});

test('a value written by code or by a test reaches the visible field', async ({ page }) => {
  await open(page);
  await page.locator('#bounded').fill('2026-10-12');
  await expect(fieldOf(page, 'bounded')).toHaveValue('Oct 12, 2026');
  await page.evaluate(() => { document.getElementById('bounded').value = '2026-10-15'; });
  await expect(fieldOf(page, 'bounded')).toHaveValue('Oct 15, 2026');
  await page.evaluate(() => document.getElementById('form').reset());
  await expect(fieldOf(page, 'bounded')).toHaveValue('Oct 10, 2026');
});

test('x-model follows the calendar and the calendar follows x-model', async ({ page }) => {
  await open(page);
  await fieldOf(page, 'bound').click();
  await calendar(page).locator('[data-day="2026-11-20"]').click();
  await expect(page.locator('#echo')).toHaveText('2026-11-20');
  await page.evaluate(() => { window.Alpine.$data(document.getElementById('alpine')).day = '2026-12-25'; });
  await expect(fieldOf(page, 'bound')).toHaveValue('Dec 25, 2026');
});

test('an optional field can be cleared and a required one cannot', async ({ page }) => {
  await open(page);
  await fieldOf(page, 'visit').click();
  await expect(calendar(page).locator('[data-go="clear"]')).toHaveCount(0);
  await page.keyboard.press('Escape');
  await fieldOf(page, 'bounded').click();
  await calendar(page).locator('[data-go="clear"]').click();
  await expect(page.locator('#bounded')).toHaveValue('');
  await expect(fieldOf(page, 'bounded')).toHaveValue('');
});

test('the label names the visible field; a test types into the real one by name', async ({ page }) => {
  await open(page);
  await expect(page.getByLabel('Wrapped date')).toHaveAttribute('role', 'combobox');
  await expect(page.getByRole('combobox', { name: 'Visit date' })).toHaveValue('Oct 6, 2026');
  await page.locator('input[name="wrapped"]').fill('2026-10-09');
  await expect(fieldOf(page, 'wrapped')).toHaveValue('Oct 9, 2026');
  // A label press focuses the field, as it does any field; it does not open it.
  await page.getByText('Bounded date').click();
  await expect(fieldOf(page, 'bounded')).toBeFocused();
  await expect(calendar(page)).toHaveCount(0);
});

test('a missing required date is flagged where the reader can see it', async ({ page }) => {
  await open(page);
  await page.evaluate(() => { document.getElementById('visit').value = ''; });
  const valid = await page.evaluate(() => document.getElementById('form').reportValidity());
  expect(valid).toBe(false);
  await expect(fieldOf(page, 'visit')).toHaveAttribute('aria-invalid', 'true');
  // The browser's message belongs to the date field, so focus stays with it.
  await expect(page.locator('#visit')).toBeFocused();
  await fieldOf(page, 'visit').click();
  await calendar(page).locator('[data-day="2026-10-08"]').click();
  await expect(fieldOf(page, 'visit')).not.toHaveAttribute('aria-invalid', 'true');
});

test('code that focuses a valid date field lands on the visible one', async ({ page }) => {
  await open(page);
  await page.evaluate(() => document.getElementById('bounded').focus());
  await expect(fieldOf(page, 'bounded')).toBeFocused();
});

test('the calendar brings no div into the form', async ({ page }) => {
  // Shared field rules select a control by its container's shape
  // (the filter bars' `div:not(:has(div))`).
  await open(page);
  await fieldOf(page, 'visit').click();
  await expect(calendar(page)).toBeVisible();
  expect(await page.locator('.edify-datepick div').count()).toBe(0);
});

test('a field that is not drawn is left alone until it is', async ({ page }) => {
  // A date field in a closed dialog (the leave page's request drawer) waits to
  // be measured. Safari reports every newly watched element once, whatever its
  // size, so a field taken off the watch and put straight back was reported on
  // every frame, for as long as the page was open (found 2026-10-08).
  await page.addInitScript(() => {
    window.__sizeCalls = 0;
    const Native = window.ResizeObserver;
    window.ResizeObserver = class extends Native {
      constructor(callback) {
        super((entries, observer) => {
          if (entries.some((entry) => entry.target.classList.contains('edify-datepick'))) window.__sizeCalls += 1;
          callback(entries, observer);
        });
      }
    };
  });
  await open(page, `<dialog id="request"><label for="leave">Leave date</label>
    <input type="date" id="leave" name="leave" value="2026-10-10"></dialog>`);
  const frames = (n) => page.evaluate((n) => new Promise((resolve) => {
    const step = () => { n -= 1; if (n > 0) requestAnimationFrame(step); else resolve(window.__sizeCalls); };
    requestAnimationFrame(step);
  }), n);
  const settled = await frames(10);
  // Thirty more frames of a page nobody touches: nothing more is heard.
  expect(await frames(30) - settled).toBe(0);

  // Drawn, it is measured once and is the field it would have been.
  await page.evaluate(() => document.getElementById('request').showModal());
  await expect(fieldOf(page, 'leave')).toBeVisible();
  await expect.poll(() => fieldOf(page, 'leave').evaluate((field) => field.size)).toBeGreaterThan(1);
  const drawn = await frames(10);
  expect(await frames(30) - drawn).toBe(0);
});

test('a field in a closed row is measured when the row opens, not before', async ({ page }) => {
  // Asking a field that is not drawn for its width makes the browser lay its
  // row out there and then. Strategic Priorities has a hundred closed rows
  // with a date field in each: ten seconds of every visit (audit, 2026-10-05).
  await page.addInitScript(() => {
    window.__widthReads = 0;
    const width = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetWidth');
    Object.defineProperty(HTMLElement.prototype, 'offsetWidth', {
      configurable: true,
      get() {
        if (this.closest && this.closest('#closed-row')) window.__widthReads += 1;
        return width.get.call(this);
      },
    });
  });
  const row = (id, field, state) => `<details id="${id}" ${state} style="content-visibility: auto">
    <summary>A row</summary>
    <label for="${field}">A date</label>
    <input type="date" id="${field}" name="${field}" value="2026-10-10">
  </details>`;
  await open(page, row('open-row', 'early', 'open') + row('closed-row', 'late', ''));
  expect(await page.evaluate(() => window.__widthReads)).toBe(0);

  await page.locator('#closed-row > summary').click();
  await expect(fieldOf(page, 'late')).toBeVisible();
  // Once on show it is the field it would have been: `early` is the same
  // markup in the same place, drawn from the start.
  const sized = (id) => page.evaluate((id) => {
    const field = document.querySelector(`#${id} + .edify-datepick .edify-datepick__field`);
    return [field.size, field.style.width, field.value];
  }, id);
  await expect.poll(() => sized('late')).toEqual(await sized('early'));
  expect(await page.evaluate(() => window.__widthReads)).toBeGreaterThan(0);
});
