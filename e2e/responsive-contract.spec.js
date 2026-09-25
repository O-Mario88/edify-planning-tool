// The responsive contract, page family by page family.
//
// One representative page from every family the responsive standard names
// (2026-09-23), opened by a role that works in it, measured at all thirteen
// geometries — phones and tablets in a touch context, laptops and wider in a
// desktop one. Each page loads once per context and is resized through its
// geometries, so a resize or a rotation that breaks a layout fails here too.
//
// The shared measurement lives in helpers/responsive.js, so this spec and the
// platform-wide matrix (responsive-matrix.spec.js) count a wrapped button or
// an overflowing workspace the same way.
//
// EDIFY_RESPONSIVE_EVIDENCE=<label> also writes screenshots for the before /
// after record to test-results/responsive-evidence/<label>/.
const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('@playwright/test');
const { signIn } = require('./helpers/auth');
const {
  GEOMETRIES,
  TOUCH_CONTEXT,
  DESKTOP_CONTEXT,
  WRAP_KEYS,
  measureLayout,
  settle,
} = require('./helpers/responsive');

test.use({ video: 'off', trace: 'off', serviceWorkers: 'block' });

const password = process.env.EDIFY_E2E_PASSWORD || 'edify';
const evidence = process.env.EDIFY_RESPONSIVE_EVIDENCE;
const evidenceDir = evidence && path.join(__dirname, '..', 'test-results', 'responsive-evidence', evidence);
const EVIDENCE_GEOMETRIES = new Set(['mobile-390', 'tablet-768', 'square-1024', 'desktop-1440']);

const FAMILIES = [
  { family: 'dashboard', email: 'cceo@edify.org', route: '/dashboard' },
  { family: 'planning', email: 'cceo@edify.org', route: '/planning' },
  { family: 'my-plan', email: 'cceo@edify.org', route: '/my-plan' },
  { family: 'school-directory', email: 'cceo@edify.org', route: '/schools' },
  { family: 'clusters', email: 'cceo@edify.org', route: '/clusters' },
  { family: 'messages', email: 'cceo@edify.org', route: '/messages' },
  { family: 'performance', email: 'cceo@edify.org', route: '/my-performance' },
  { family: 'partner-monitoring', email: 'pl1@edify.org', route: '/partner-oversight/' },
  { family: 'team-oversight', email: 'cd@edify.org', route: '/country-planning-oversight/' },
  { family: 'analytics', email: 'cd@edify.org', route: '/analytics' },
  { family: 'verification', email: 'ia@edify.org', route: '/ia/verification/' },
  { family: 'finance', email: 'accountant@edify.org', route: '/fund-requests' },
  { family: 'hr', email: 'hr@edify.org', route: '/hr-today' },
  { family: 'loans', email: 'mfi-admin@edify.org', route: '/loans' },
  { family: 'administration', email: 'admin@edify.org', route: '/admin-panel/users' },
  { family: 'settings', email: 'cceo@edify.org', route: '/settings' },
  { family: 'program-lead-analytics', email: 'pl1@edify.org', route: '/analytics/program-lead' },
];

function onlyChromiumDesktop({ browserName, isMobile }) {
  test.skip(browserName !== 'chromium' || isMobile, 'Builds its own touch and desktop contexts.');
}

async function openAs(browser, baseURL, mode, geometry, email) {
  const context = await browser.newContext({
    ...mode,
    baseURL,
    viewport: { width: geometry.width, height: geometry.height },
  });
  const page = await context.newPage();
  await signIn(page, email, password, { acceptRequiredAgreements: false });
  return { context, page };
}

function describeDefects(measure) {
  const found = [];
  if (measure.documentOverflow) found.push('page scrolls sideways');
  if (measure.mainOverflow) found.push('workspace scrolls sideways');
  if (measure.tables.unscrolled.length) found.push(`table without a scroll region: ${measure.tables.unscrolled.join(', ')}`);
  for (const key of WRAP_KEYS) {
    if (measure[key].count) found.push(`${key} wrap: ${measure[key].examples.join(' | ')}`);
  }
  return found;
}

test.describe('Responsive contract — every page family at every geometry', () => {
  for (const { family, email, route } of FAMILIES) {
    test(`${family}: ${route}`, async ({ browser, baseURL, browserName, isMobile }) => {
      onlyChromiumDesktop({ browserName, isMobile });
      test.setTimeout(3 * 60_000);
      const failures = [];
      for (const mode of [TOUCH_CONTEXT, DESKTOP_CONTEXT]) {
        const geometries = GEOMETRIES.filter(g => g.touch === mode.hasTouch);
        const { context, page } = await openAs(browser, baseURL, mode, geometries[0], email);
        try {
          const response = await page.goto(route, { waitUntil: 'domcontentloaded' });
          expect(response.status(), route).toBeLessThan(400);
          await expect(page.locator('main#main-content')).toBeVisible();
          await page.locator('.htmx-request').first().waitFor({ state: 'detached', timeout: 10_000 }).catch(() => {});
          for (const geometry of geometries) {
            await page.setViewportSize({ width: geometry.width, height: geometry.height });
            await settle(page);
            const measure = await page.evaluate(measureLayout);
            describeDefects(measure).forEach(defect => failures.push(`${geometry.key}: ${defect}`));
            if (evidenceDir && EVIDENCE_GEOMETRIES.has(geometry.key)) {
              fs.mkdirSync(evidenceDir, { recursive: true });
              await page.screenshot({ path: path.join(evidenceDir, `${family}-${geometry.key}.png`) });
            }
          }
        } finally {
          await context.close();
        }
      }
      expect(failures, `${route} at the responsive geometries`).toEqual([]);
    });
  }
});

test.describe('Responsive contract — behaviours', () => {
  test('a wide table keeps its identity column in view and says it scrolls', async ({ browser, baseURL, browserName, isMobile }) => {
    onlyChromiumDesktop({ browserName, isMobile });
    const { context, page } = await openAs(browser, baseURL, TOUCH_CONTEXT, { width: 390, height: 844 }, 'pl1@edify.org');
    try {
      await page.evaluate(() => sessionStorage.removeItem('edify-table-swipe-learned'));
      await page.goto('/partner-oversight/');
      const region = page.locator('[data-partner-monitoring-table]').first().locator('xpath=ancestor::*[contains(@class,"edify-table-scroll-region")][1]');
      await expect(region).toHaveAttribute('data-scroll-state', 'start');
      await expect(page.locator('.edify-table-scroll-hint')).toHaveText('Swipe to view more columns');
      const identity = region.locator('tbody tr').first().locator('> :first-child');
      await expect(identity).toHaveCSS('position', 'sticky');
      const before = await identity.boundingBox();

      await region.evaluate(element => { element.scrollLeft = 240; });
      await expect(region).toHaveAttribute('data-scroll-state', /middle|end/);
      await expect(page.locator('.edify-table-scroll-hint')).toHaveCount(0);
      const after = await identity.boundingBox();
      expect(Math.abs(after.x - before.x)).toBeLessThan(1);
      // Pinned, the identity leaves most of the region for the columns it
      // introduces, and a cut name keeps its full text as a title.
      const regionWidth = await region.evaluate(element => element.clientWidth);
      expect(after.width).toBeLessThanOrEqual(regionWidth * 0.6);
      const name = identity.locator('> :first-child');
      if (await name.evaluate(e => e.scrollWidth > e.clientWidth + 1)) {
        await expect(name).toHaveAttribute('title', /\S/);
      }

      // Learned once, the hint stays away for the rest of the session.
      await page.reload();
      await expect(region).toHaveAttribute('data-scroll-state', 'start');
      await expect(page.locator('.edify-table-scroll-hint')).toHaveCount(0);
      // The page itself never moved sideways.
      expect(await page.evaluate(() => {
        const main = document.querySelector('main');
        return main.scrollWidth - main.clientWidth;
      })).toBeLessThanOrEqual(1);
    } finally {
      await context.close();
    }
  });

  test('a drawer on a phone is a sheet from the bottom edge; a tablet keeps the card', async ({ browser, baseURL, browserName, isMobile }) => {
    onlyChromiumDesktop({ browserName, isMobile });
    const { context, page } = await openAs(browser, baseURL, TOUCH_CONTEXT, { width: 390, height: 844 }, 'cceo@edify.org');
    try {
      await page.goto('/clusters');
      await page.locator('[hx-get="/clusters/create-drawer"]').first().click();
      const sheet = page.locator('.drawer-surface.active');
      await expect(sheet).toBeVisible();
      await page.addStyleTag({ content: '*,*::before,*::after{transition:none!important;animation:none!important}' });
      for (const [width, height] of [[320, 568], [390, 844], [430, 932]]) {
        await page.setViewportSize({ width, height });
        const box = await sheet.boundingBox();
        // Edge to edge and flush with the bottom, within emulation rounding.
        expect(Math.abs(box.x)).toBeLessThan(1);
        expect(Math.abs(box.width - width)).toBeLessThan(2);
        expect(Math.abs(box.y + box.height - height)).toBeLessThanOrEqual(3);
        expect(box.y).toBeGreaterThanOrEqual(8);
        expect(await sheet.evaluate(e => e.scrollWidth - e.clientWidth)).toBeLessThanOrEqual(2);
        const submit = sheet.locator('button[type="submit"]').last();
        if (await submit.count()) {
          const action = await submit.boundingBox();
          expect(action.y + action.height).toBeLessThanOrEqual(height);
          expect(await submit.evaluate(e => getComputedStyle(e).whiteSpace)).toBe('nowrap');
        }
      }
      await page.setViewportSize({ width: 834, height: 1194 });
      const card = await sheet.boundingBox();
      expect(Math.abs(card.x + card.width / 2 - 417)).toBeLessThan(2);
      expect(card.x).toBeGreaterThanOrEqual(8);
    } finally {
      await context.close();
    }
  });

  test('rotation, 200% zoom and enlarged text keep every page family inside the screen', async ({ browser, baseURL, browserName, isMobile }) => {
    onlyChromiumDesktop({ browserName, isMobile });
    test.setTimeout(3 * 60_000);
    const failures = [];
    // Portrait to landscape on a phone.
    {
      const { context, page } = await openAs(browser, baseURL, TOUCH_CONTEXT, { width: 390, height: 844 }, 'cceo@edify.org');
      try {
        for (const route of ['/planning', '/my-plan', '/schools']) {
          await page.setViewportSize({ width: 390, height: 844 });
          await page.goto(route);
          for (const [width, height] of [[844, 390], [390, 844]]) {
            await page.setViewportSize({ width, height });
            await settle(page);
            describeDefects(await page.evaluate(measureLayout)).forEach(d => failures.push(`${route} ${width}x${height}: ${d}`));
          }
        }
        // Enlarged mobile text: the reader's own 125% text size.
        await page.setViewportSize({ width: 390, height: 844 });
        await page.goto('/planning');
        await page.addStyleTag({ content: 'html{font-size:125%!important}' });
        await settle(page);
        const enlarged = await page.evaluate(measureLayout);
        if (enlarged.documentOverflow || enlarged.mainOverflow) failures.push('/planning at 125% text: overflow');
      } finally {
        await context.close();
      }
    }
    // Browser zoom: 1280px at 200% is a 640px CSS viewport at twice the pixels.
    {
      const { context, page } = await openAs(browser, baseURL, { ...DESKTOP_CONTEXT, deviceScaleFactor: 2 }, { width: 640, height: 400 }, 'cceo@edify.org');
      try {
        for (const route of ['/planning', '/my-plan', '/dashboard']) {
          await page.goto(route);
          await settle(page);
          describeDefects(await page.evaluate(measureLayout)).forEach(d => failures.push(`${route} at 200% zoom: ${d}`));
          await expect(page.locator('main#main-content')).toBeVisible();
        }
      } finally {
        await context.close();
      }
    }
    expect(failures).toEqual([]);
  });

  test('controls are reachable by keyboard with a visible focus ring and touch-sized on a phone', async ({ browser, baseURL, browserName, isMobile }) => {
    onlyChromiumDesktop({ browserName, isMobile });
    const { context, page } = await openAs(browser, baseURL, TOUCH_CONTEXT, { width: 390, height: 844 }, 'cceo@edify.org');
    try {
      await page.goto('/planning');
      // Into the workspace the way the skip link takes a keyboard user, then
      // one Tab to its first control.
      await page.evaluate(() => {
        const main = document.querySelector('main#main-content');
        if (!main.hasAttribute('tabindex')) main.setAttribute('tabindex', '-1');
        main.focus();
      });
      await page.keyboard.press('Tab');
      expect(await page.evaluate(() => document.activeElement.closest('main') !== null)).toBe(true);
      // The platform draws its focus ring as an outline or as a box-shadow
      // ring (--edify-focus-ring); either is a visible indicator.
      const ring = await page.evaluate(() => {
        const style = getComputedStyle(document.activeElement);
        return {
          outline: style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) >= 2,
          shadow: style.boxShadow !== 'none',
        };
      });
      expect(ring.outline || ring.shadow, 'visible focus indicator').toBe(true);

      const small = await page.evaluate(measureLayout);
      expect(small.smallTargets.examples, 'controls under 24px on a phone').toEqual([]);
    } finally {
      await context.close();
    }
  });

  test('filters share one row on a desktop and several to a row on a phone', async ({ browser, baseURL, browserName, isMobile }) => {
    onlyChromiumDesktop({ browserName, isMobile });
    // A row is the fields whose controls end on one line: "More filters" is a
    // button without a label above it, bottom-aligned with the selects.
    const rowsOf = (page, selector) => page.evaluate(sel => {
      const form = document.querySelector(sel);
      const rows = new Map();
      [...form.children]
        .filter(field => field.querySelector('select') && field.getBoundingClientRect().width)
        .forEach(field => {
          const bottom = Math.round(field.getBoundingClientRect().bottom);
          rows.set(bottom, (rows.get(bottom) || 0) + 1);
        });
      const clipped = [...form.querySelectorAll('select')]
        .filter(select => select.getBoundingClientRect().width && select.scrollWidth > select.clientWidth + 1)
        .map(select => select.name);
      return { rows: [...rows.values()], clipped };
    }, selector);

    // Partner Monitoring's filters are three and More on one row, even on the
    // smallest phone (owner, 2026-09-25).
    {
      const { context, page } = await openAs(browser, baseURL, TOUCH_CONTEXT, { width: 320, height: 568 }, 'pl1@edify.org');
      try {
        await page.goto('/partner-oversight/');
        const { rows, clipped } = await rowsOf(page, 'form.oversight-period-filter');
        expect(rows[0]).toBe(4);
        expect(clipped).toEqual([]);
      } finally {
        await context.close();
      }
    }
    // Planning's eight filters: one full-width row on a desktop — five fields
    // and "More filters" holding the other three, the School Directory's six
    // slots (owner, 2026-09-25) — and several to a row on a phone.
    {
      const { context, page } = await openAs(browser, baseURL, DESKTOP_CONTEXT, { width: 1440, height: 900 }, 'cceo@edify.org');
      try {
        await page.goto('/planning');
        const { rows, clipped } = await rowsOf(page, '#filters-form');
        expect(rows).toEqual([6]);
        expect(clipped).toEqual([]);
        await expect(page.locator('#filters-form [data-edify-filter-more-panel] select')).toHaveCount(3);
      } finally {
        await context.close();
      }
    }
    {
      const { context, page } = await openAs(browser, baseURL, TOUCH_CONTEXT, { width: 390, height: 844 }, 'cceo@edify.org');
      try {
        await page.goto('/planning');
        await page.evaluate(() => document.querySelectorAll('details.mobile-family-filter').forEach(d => { d.open = true; }));
        const { rows, clipped } = await rowsOf(page, '#filters-form');
        expect(rows.length).toBeLessThanOrEqual(4);
        expect(Math.max(...rows)).toBeGreaterThanOrEqual(3);
        expect(clipped).toEqual([]);
      } finally {
        await context.close();
      }
    }
  });

  test('reduced motion stills the scroll hint', async ({ browser, baseURL, browserName, isMobile }) => {
    onlyChromiumDesktop({ browserName, isMobile });
    const { context, page } = await openAs(browser, baseURL, { ...TOUCH_CONTEXT, reducedMotion: 'reduce' }, { width: 390, height: 844 }, 'pl1@edify.org');
    try {
      await page.evaluate(() => sessionStorage.removeItem('edify-table-swipe-learned'));
      await page.goto('/partner-oversight/');
      const hint = page.locator('.edify-table-scroll-hint');
      await expect(hint).toBeVisible();
      expect(await hint.evaluate(e => getComputedStyle(e).animationName)).toBe('none');
    } finally {
      await context.close();
    }
  });
});
