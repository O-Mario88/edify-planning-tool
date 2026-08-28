const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('@playwright/test');
const { signIn } = require('./helpers/auth');

const inventory = JSON.parse(
  fs.readFileSync(path.join(__dirname, '..', 'docs', 'platform-page-inventory.json'), 'utf8')
);

const defaultPassword = process.env.EDIFY_E2E_PASSWORD || 'edify';
const roleAccounts = [
  ['CCEO', 'CCEO', 'cceo@edify.org'],
  ['PL', 'PL', 'pl1@edify.org'],
  ['CD', 'CD', 'cd@edify.org'],
  ['RVP', 'RVP', 'rvp@edify.org'],
  ['IA', 'IA', 'ia@edify.org'],
  ['ACCOUNTANT', 'ACCOUNTANT', 'accountant@edify.org'],
  ['HR', 'HR', 'hr@edify.org'],
  ['PROJECT_COORDINATOR', 'PROJECT_COORDINATOR', 'coordinator@edify.org'],
  ['PARTNER_ADMIN', 'PARTNER', 'partner-admin@edify.org'],
  ['PARTNER', 'PARTNER', 'partner@edify.org'],
  ['BUSINESS_TRANSFORMATION', 'BUSINESS_TRANSFORMATION', 'business-transformation@edify.org'],
  ['MFI_ADMIN', 'MFI_ADMIN', 'mfi-admin@edify.org'],
  ['MFI_OFFICER', 'MFI_OFFICER', 'mfi-officer@edify.org'],
  ['ADMIN', 'ADMIN', 'admin@edify.org'],
];

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

for (const [accountRole, inventoryRole, email] of roleAccounts) {
  test(`${accountRole}: every permitted argument-free page opens and exposes operable controls`, async ({
    page,
    browserName,
    isMobile,
  }, testInfo) => {
    test.skip(browserName !== 'chromium' || isMobile, 'Full role crawl runs once; critical public UI runs on every browser/device.');
    test.setTimeout(15 * 60_000);

    await signIn(page, email, defaultPassword);
    const records = [];
    const errors = [];
    let currentRoute = '';
    page.on('console', message => {
      if (message.type() === 'error') errors.push(`${currentRoute}: console: ${message.text()}`);
    });
    page.on('pageerror', error => errors.push(`${currentRoute}: pageerror: ${error.message}`));

    for (const route of routesForRole(inventoryRole)) {
      currentRoute = route;
      const started = Date.now();
      let response;
      try {
        response = await page.goto(route, { waitUntil: 'domcontentloaded', timeout: 20_000 });
      } catch (error) {
        errors.push(`${route}: navigation: ${error.message}`);
        continue;
      }

      const status = response?.status() || 0;
      const finalPath = new URL(page.url()).pathname;
      const pageRecord = await page.evaluate(() => {
        const normalizedText = value => value?.trim().replace(/\s+/g, ' ').slice(0, 160) || '';
        const accessibleName = element => {
          const labelledBy = (element.getAttribute('aria-labelledby') || '')
            .split(/\s+/)
            .filter(Boolean)
            .map(id => normalizedText(document.getElementById(id)?.textContent))
            .filter(Boolean)
            .join(' ');
          const explicitLabels = element.labels
            ? [...element.labels].map(label => normalizedText(label.textContent)).filter(Boolean).join(' ')
            : '';
          return normalizedText(element.getAttribute('aria-label')) || labelledBy ||
            explicitLabels || normalizedText(element.getAttribute('title')) ||
            normalizedText(element.textContent) || normalizedText(element.getAttribute('alt')) ||
            normalizedText(element.getAttribute('placeholder')) ||
            normalizedText(element.getAttribute('value'));
        };
        const selector = [
          'a[href]', 'button', 'input[type="submit"]', 'input[type="reset"]',
          '[role="button"]', '[role="tab"]', '[hx-get]', '[hx-post]', '[hx-put]',
          '[hx-patch]', '[hx-delete]', 'select', 'input[type="checkbox"]',
          'input[type="radio"]', 'input[type="file"]', 'input[type="search"]',
        ].join(',');
        const controls = [...document.querySelectorAll(selector)].map((element, index) => ({
          id: element.id || element.dataset.testid || `control-${index + 1}`,
          tag: element.tagName.toLowerCase(),
          type: element.getAttribute('type') || element.getAttribute('role') || '',
          label: accessibleName(element),
          href: element.getAttribute('href') || '',
          disabled: element.matches(':disabled,[aria-disabled="true"]'),
          visible: Boolean(element.getClientRects().length),
          action: element.getAttribute('hx-get') || element.getAttribute('hx-post') ||
            element.getAttribute('hx-put') || element.getAttribute('hx-patch') ||
            element.getAttribute('hx-delete') || element.getAttribute('formaction') || '',
        }));
        return {
          title: document.title,
          domNodes: document.querySelectorAll('*').length,
          horizontalOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
          controls,
        };
      });

      const unlabeledVisibleControls = pageRecord.controls.filter(control =>
        control.visible && !control.disabled && !control.label && control.tag !== 'select'
      );
      if (status >= 400) errors.push(`${route}: HTTP ${status}`);
      if (finalPath.startsWith('/policy-agreement') || finalPath.startsWith('/documents/') || finalPath === '/login') {
        errors.push(`${route}: redirected to onboarding gate ${finalPath}`);
      }
      if (pageRecord.domNodes > 10_000) errors.push(`${route}: ${pageRecord.domNodes} DOM nodes`);
      if (pageRecord.horizontalOverflow) errors.push(`${route}: horizontal overflow`);
      if (unlabeledVisibleControls.length) {
        errors.push(`${route}: ${unlabeledVisibleControls.length} visible controls lack an accessible name`);
      }
      records.push({
        role: accountRole,
        route,
        status,
        durationMs: Date.now() - started,
        ...pageRecord,
      });
    }

    await testInfo.attach(`${accountRole.toLowerCase()}-interaction-inventory.json`, {
      body: Buffer.from(JSON.stringify({ role: accountRole, inventoryRole, email, records, errors }, null, 2)),
      contentType: 'application/json',
    });

    expect(records.length).toBeGreaterThan(0);
    expect(errors).toEqual([]);
  });
}
