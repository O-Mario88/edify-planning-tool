// The responsive audit matrix: every argument-free page each seeded role can
// open, measured at the thirteen geometries of the responsive standard.
//
// Heavy by design — about a thousand role/page pairs — so it runs only when
// asked for (EDIFY_RESPONSIVE_MATRIX=1) and writes evidence rather than
// failing on the first defect:
//
//   EDIFY_RESPONSIVE_MATRIX=1 EDIFY_RESPONSIVE_LABEL=after \
//     npx playwright test e2e/responsive-matrix.spec.js --project=chromium-desktop
//   node scripts/build_responsive_matrix.cjs
//
// Each page loads once per input mode (touch for phones and tablets, desktop
// for laptops and wider) and is then resized through that mode's geometries
// without reloading — which is also the orientation and split-screen test.
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('@playwright/test');
const { signIn } = require('./helpers/auth');
const { localRoleAccounts } = require('./helpers/accounts');
const {
  GEOMETRIES,
  TOUCH_CONTEXT,
  DESKTOP_CONTEXT,
  measureLayout,
  grade,
  settle,
} = require('./helpers/responsive');

test.use({ video: 'off', trace: 'off' });

const inventory = JSON.parse(
  fs.readFileSync(path.join(__dirname, '..', 'docs', 'platform-page-inventory.json'), 'utf8')
);
const label = process.env.EDIFY_RESPONSIVE_LABEL || 'current';
const outDir = path.join(__dirname, '..', 'test-results', 'responsive-matrix', label);
const password = process.env.EDIFY_E2E_PASSWORD || 'edify';
const onlyRoles = (process.env.EDIFY_RESPONSIVE_ROLES || '').split(',').filter(Boolean);

function routesForRole(role) {
  return [...new Set(inventory.pages
    .filter(surface =>
      surface.surface_kind === 'page' &&
      surface.role_access.includes(role) &&
      !surface.route.includes('<') &&
      !surface.route.includes('logout')
    )
    .map(surface => surface.route))].sort();
}

async function crawl(browser, baseURL, email, routes, mode, geometries, records) {
  const first = geometries[0];
  const context = await browser.newContext({
    ...mode,
    baseURL,
    viewport: { width: first.width, height: first.height },
  });
  const page = await context.newPage();
  try {
    await signIn(page, email, password, { acceptRequiredAgreements: true });
    for (const route of routes) {
      await page.setViewportSize({ width: first.width, height: first.height });
      let status = 0;
      try {
        const response = await page.goto(route, { waitUntil: 'domcontentloaded', timeout: 20_000 });
        status = response?.status() || 0;
        await page.locator('.htmx-request').first().waitFor({ state: 'detached', timeout: 10_000 }).catch(() => {});
      } catch (error) {
        records.push({ route, status: 0, error: error.message.split('\n')[0] });
        continue;
      }
      const finalPath = new URL(page.url()).pathname;
      const title = await page.title();
      for (const geometry of geometries) {
        await page.setViewportSize({ width: geometry.width, height: geometry.height });
        await settle(page);
        const measure = await page.evaluate(measureLayout);
        records.push({
          route,
          finalPath,
          title,
          status,
          geometry: geometry.key,
          band: geometry.band,
          grade: grade(measure),
          ...measure,
        });
      }
    }
  } finally {
    await context.close();
  }
}

for (const [accountRole, inventoryRole, email] of localRoleAccounts) {
  test(`${accountRole}: responsive matrix`, async ({ browser, baseURL, browserName, isMobile }) => {
    test.skip(!process.env.EDIFY_RESPONSIVE_MATRIX, 'Set EDIFY_RESPONSIVE_MATRIX=1 to crawl the matrix.');
    test.skip(browserName !== 'chromium' || isMobile, 'The matrix builds its own touch and desktop contexts.');
    test.skip(onlyRoles.length > 0 && !onlyRoles.includes(accountRole), 'Role not selected.');
    test.setTimeout(90 * 60_000);

    const routes = routesForRole(inventoryRole);
    const records = [];
    await crawl(browser, baseURL, email, routes, TOUCH_CONTEXT, GEOMETRIES.filter(g => g.touch), records);
    await crawl(browser, baseURL, email, routes, DESKTOP_CONTEXT, GEOMETRIES.filter(g => !g.touch), records);

    fs.mkdirSync(outDir, { recursive: true });
    fs.writeFileSync(
      path.join(outDir, `${accountRole.toLowerCase()}.json`),
      JSON.stringify({ role: accountRole, inventoryRole, label, records }, null, 1)
    );
  });
}
