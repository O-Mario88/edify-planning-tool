const fs = require('node:fs');
const path = require('node:path');
const { test, expect } = require('@playwright/test');
const { signIn } = require('./helpers/auth');

const inventory = JSON.parse(
  fs.readFileSync(path.join(__dirname, '..', 'docs', 'platform-page-inventory.json'), 'utf8')
);

const baseURL = process.env.EDIFY_E2E_BASE_URL || 'http://127.0.0.1:8000';
const defaultPassword = process.env.EDIFY_E2E_PASSWORD || 'edify';
const localRoleAccounts = [
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

const productionHosts = new Set([
  'edifyplanning.app',
  'www.edifyplanning.app',
  'edify-planning-fra-ozkgq.ondigitalocean.app',
]);
const productionTarget = productionHosts.has(new URL(baseURL).hostname.toLowerCase());

function productionRoleAccounts() {
  if (process.env.EDIFY_PRODUCTION_SMOKE_MODE !== 'read-only-authenticated') {
    throw new Error(
      'Authenticated production smoke is fail-closed. Set ' +
      'EDIFY_PRODUCTION_SMOKE_MODE=read-only-authenticated only after the release owner ' +
      'approves the isolated accounts and GET-only crawl.'
    );
  }

  const accountFile = process.env.EDIFY_E2E_ACCOUNTS_FILE;
  if (!accountFile || !path.isAbsolute(accountFile)) {
    throw new Error('Production smoke requires an absolute EDIFY_E2E_ACCOUNTS_FILE path.');
  }

  let accounts;
  try {
    accounts = JSON.parse(fs.readFileSync(accountFile, 'utf8'));
  } catch (error) {
    throw new Error(`Cannot read production smoke account manifest: ${error.message}`);
  }
  if (!Array.isArray(accounts)) {
    throw new Error('Production smoke account manifest must be a JSON array.');
  }

  const required = new Map(localRoleAccounts.map(([accountRole, inventoryRole]) => [
    accountRole,
    inventoryRole,
  ]));
  const seen = new Set();
  const normalized = accounts.map(account => {
    const keys = Object.keys(account).sort();
    if (keys.join(',') !== 'accountRole,email,inventoryRole,passwordEnv') {
      throw new Error(
        'Every production account entry must contain only accountRole, inventoryRole, ' +
        'email, and passwordEnv. Passwords must not be stored in the manifest.'
      );
    }
    if (!required.has(account.accountRole) || required.get(account.accountRole) !== account.inventoryRole) {
      throw new Error(`Unexpected role mapping ${account.accountRole}/${account.inventoryRole}.`);
    }
    if (seen.has(account.accountRole)) {
      throw new Error(`Duplicate production smoke role ${account.accountRole}.`);
    }
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(account.email)) {
      throw new Error(`Invalid smoke account email for ${account.accountRole}.`);
    }
    if (!/^EDIFY_E2E_[A-Z0-9_]+_PASSWORD$/.test(account.passwordEnv)) {
      throw new Error(`Unsafe passwordEnv name for ${account.accountRole}.`);
    }
    const password = process.env[account.passwordEnv];
    if (!password) {
      throw new Error(`Missing password environment variable ${account.passwordEnv}.`);
    }
    seen.add(account.accountRole);
    return [account.accountRole, account.inventoryRole, account.email, password];
  });

  const missing = [...required.keys()].filter(role => !seen.has(role));
  if (missing.length) {
    throw new Error(`Production smoke account manifest is incomplete; missing ${missing.join(', ')}.`);
  }
  return normalized;
}

const roleAccounts = productionTarget
  ? productionRoleAccounts()
  : localRoleAccounts.map(([accountRole, inventoryRole, email]) => [
      accountRole,
      inventoryRole,
      email,
      defaultPassword,
    ]);

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

for (const [accountRole, inventoryRole, email, password] of roleAccounts) {
  test(`${accountRole}: every permitted argument-free page opens and exposes operable controls`, async ({
    page,
    browserName,
    isMobile,
  }, testInfo) => {
    test.skip(browserName !== 'chromium' || isMobile, 'Full role crawl runs once; critical public UI runs on every browser/device.');
    test.setTimeout(15 * 60_000);

    await signIn(page, email, password, {
      acceptRequiredAgreements: !productionTarget,
    });
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
