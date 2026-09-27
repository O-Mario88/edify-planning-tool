/*
 * The phone layout holds on the pages a field team lives in (owner's mobile
 * directive, 2026-09-27): no page wider than the phone, tables that stay
 * tables, tick boxes that are whole and 44px to a finger, a record's Actions
 * on its name's line, KPIs that fit without swiping, and a bottom navigation
 * that covers nothing. Asserted on rendered geometry at 320, 360, 390 and
 * 430px — the layout is the promise, not the class list.
 *
 * Run: npx playwright test e2e/mobile-layout.spec.js --project chromium-desktop --no-deps
 * (the viewport is set per width here, with touch emulation).
 */
const { test, expect } = require('@playwright/test');
const { signIn } = require('./helpers/auth');

const WIDTHS = [320, 360, 390, 430];
const PAGES = {
  'cceo@edify.org': ['/dashboard', '/my-plan', '/core-schools', '/schools', '/planning', '/work-plan'],
  'cd@edify.org': ['/staff', '/projects/planning', '/clusters', '/analytics/country-director'],
  'pl1@edify.org': ['/dashboard'],
  'hr@edify.org': ['/my-performance'],
};

/* Runs in the page. Returns a list of broken promises, empty when the page
   holds. Source text rather than a closure: Playwright serialises it. */
function layoutDefects() {
  const defects = [];
  const vw = document.documentElement.clientWidth;
  const main = document.querySelector('main');
  const shown = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && (!el.checkVisibility || el.checkVisibility()); };
  const name = (el) => el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '');
  const target = (el) => {
    const r = el.getBoundingClientRect(); let w = r.width; let h = r.height;
    const after = getComputedStyle(el, '::after');
    if (after.content && after.content !== 'none' && after.position === 'absolute') { w = Math.max(w, parseFloat(after.width) || 0); h = Math.max(h, parseFloat(after.height) || 0); }
    return [w, h];
  };

  if (document.documentElement.scrollWidth > document.documentElement.clientWidth + 1) defects.push('the page scrolls sideways');
  if (main && main.scrollWidth > main.clientWidth + 1) defects.push('the workspace scrolls sideways');

  main.querySelectorAll('table').forEach((table) => {
    if (!shown(table) || table.closest('.fc')) return;
    const row = table.querySelector('tbody tr'); const cell = row && row.querySelector('td, th');
    if (!row || !cell) return;
    const display = [getComputedStyle(table).display, getComputedStyle(row).display, getComputedStyle(cell).display].join('/');
    if (display !== 'table/table-row/table-cell') defects.push(`${name(table)} is drawn as ${display}, not a table`);
    const head = table.querySelector('thead');
    if (head && !shown(head)) defects.push(`${name(table)} hides its header row`);
    const hidden = [...table.querySelectorAll('thead th')].filter((th) => getComputedStyle(th).display === 'none' && !th.classList.contains('sr-only'));
    if (hidden.length) defects.push(`${name(table)} hides ${hidden.length} column(s)`);
  });

  main.querySelectorAll('input[type="checkbox"]').forEach((box) => {
    if (!shown(box)) return;
    const r = box.getBoundingClientRect();
    // 14px on a phone, scaling to 16px (owner, 2026-09-27: "the size of
    // checkboxes should adjust dynamically"); smaller is a clipped box.
    if (r.width < 13.5 || r.height < 13.5) defects.push(`a tick box is ${Math.round(r.width)}x${Math.round(r.height)}`);
    for (let n = box.parentElement; n && n !== main; n = n.parentElement) {
      const s = getComputedStyle(n);
      if (s.overflowX === 'visible' && s.overflowY === 'visible') continue;
      if (/(auto|scroll)/.test(s.overflowX)) break;
      const nr = n.getBoundingClientRect();
      if (r.left < nr.left - 0.5 || r.right > nr.right + 0.5) { defects.push(`a tick box is cut by ${name(n)}`); break; }
    }
    const label = box.closest('label') || (box.id && document.querySelector(`label[for="${box.id}"]`));
    const [w, h] = label ? target(label) : [r.width, r.height];
    if (Math.max(w, r.width) < 43.5 || Math.max(h, r.height) < 43.5) defects.push(`a tick box's target is ${Math.round(Math.max(w, r.width))}x${Math.round(Math.max(h, r.height))}`);
  });

  main.querySelectorAll('.row-menu__trigger').forEach((trigger) => {
    if (!shown(trigger)) return;
    const [w, h] = target(trigger);
    if (w < 43.5 || h < 43.5) defects.push(`an Actions button's target is ${Math.round(w)}x${Math.round(h)}`);
    const row = trigger.closest('li, article, .card, .school-record-row');
    if (!row || trigger.closest('tr')) return;
    const title = row.querySelector('h2, h3, [data-record-title], .school-record-row__title');
    if (title && !title.contains(trigger) && trigger.getBoundingClientRect().top >= title.getBoundingClientRect().bottom - 2) {
      defects.push(`${name(row)}: Actions sits under the name`);
    }
  });

  document.querySelectorAll('.context-metrics__sentence').forEach((strip) => {
    if (!shown(strip)) return;
    const r = strip.getBoundingClientRect();
    if (strip.scrollWidth > strip.clientWidth + 1) defects.push('a KPI strip scrolls sideways');
    if (r.right > vw + 1) defects.push('a KPI strip is wider than the phone');
  });

  const nav = document.querySelector('.edify-bottom-nav');
  if (nav && shown(nav)) {
    main.scrollTop = main.scrollHeight;
    const navTop = nav.getBoundingClientRect().top;
    const content = [...main.querySelectorAll('button, a[href], input, select, textarea, p, td, li, h2, h3')].filter((el) => shown(el) && getComputedStyle(el).position !== 'fixed');
    const last = content[content.length - 1];
    if (last && last.getBoundingClientRect().bottom > navTop + 1) defects.push(`the bottom navigation covers ${name(last)}`);
    main.scrollTop = 0;
  }
  return defects;
}

for (const [email, routes] of Object.entries(PAGES)) {
  test(`${email}: phone layout holds at ${WIDTHS.join(', ')}px`, async ({ browser }) => {
    test.setTimeout(240_000);
    const context = await browser.newContext({ isMobile: true, hasTouch: true, viewport: { width: 390, height: 844 } });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    page.on('console', (message) => { if (message.type() === 'error' && !/Failed to load resource/.test(message.text())) errors.push(message.text()); });
    await signIn(page, email, 'edify', { acceptRequiredAgreements: false });
    const failures = [];
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: 800 });
      for (const route of routes) {
        await page.goto(route);
        await page.waitForLoadState('load');
        await page.waitForTimeout(600);
        const defects = await page.evaluate(layoutDefects);
        if (defects.length) failures.push(`${route} @${width}: ${[...new Set(defects)].slice(0, 6).join('; ')}`);
      }
    }
    await context.close();
    expect(failures, failures.join('\n')).toEqual([]);
    expect(errors).toEqual([]);
  });
}

test('a selection table pins its tick boxes and the name beside them on a phone', async ({ browser }) => {
  test.setTimeout(120_000);
  const context = await browser.newContext({ isMobile: true, hasTouch: true, viewport: { width: 360, height: 800 } });
  const page = await context.newPage();
  await signIn(page, 'cd@edify.org', 'edify', { acceptRequiredAgreements: false });
  for (const route of ['/staff', '/planning', '/projects/planning']) {
    await page.goto(route);
    const box = page.locator('main tbody td input[type="checkbox"]').first();
    await expect(box).toBeVisible();
    await box.scrollIntoViewIfNeeded();
    const result = await box.evaluate(async (input) => {
      const region = input.closest('.edify-table-scroll-region');
      const cell = input.closest('td');
      const identity = cell.nextElementSibling;
      const before = cell.getBoundingClientRect().left;
      region.scrollLeft = 240;
      await new Promise((resolve) => setTimeout(resolve, 300));
      const box = input.getBoundingClientRect();
      const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
      const out = {
        state: region.dataset.scrollState,
        cellStays: Math.abs(cell.getBoundingClientRect().left - before) < 1,
        identityBeside: identity.getBoundingClientRect().left >= cell.getBoundingClientRect().right - 1,
        boxOnTop: Boolean(hit && cell.contains(hit)),
      };
      region.scrollLeft = 0;
      return out;
    });
    if (result.state === 'none') continue; // fits this phone: nothing to pin
    expect(result, route).toEqual({ state: result.state, cellStays: true, identityBeside: true, boxOnTop: true });
  }
  await context.close();
});

test('tablets keep the KPI strip and desktops keep the Actions beside the name', async ({ browser }) => {
  test.setTimeout(120_000);
  const context = await browser.newContext({ viewport: { width: 768, height: 1024 } });
  const page = await context.newPage();
  await signIn(page, 'cceo@edify.org', 'edify', { acceptRequiredAgreements: false });
  await page.goto('/core-schools');
  const strip = page.locator('.context-metrics__sentence').first();
  await expect(strip).toHaveCSS('display', 'flex');
  await page.setViewportSize({ width: 1280, height: 900 });
  const sameLine = await page.locator('.core-school-row').first().evaluate((row) => {
    const title = row.querySelector('.school-record-row__title').getBoundingClientRect();
    return row.querySelector('.row-menu__trigger').getBoundingClientRect().top < title.bottom;
  });
  expect(sameLine).toBe(true);
  await context.close();
});
