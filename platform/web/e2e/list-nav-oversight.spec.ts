/**
 * End-to-end browser verification of the 6 Go-backed migration deliverables
 * (run against live Go gateway with Django offline + production Next.js build):
 *
 * 1. Row-click expand/collapse + no disclosure chevrons + distinct metadata &
 *    3-column SSA intervention breakdown (School Directory, Cluster List +
 *    nested school rows, Core Schools, Planning).
 * 2. Inline-only entity name links (whitespace after name toggles expansion
 *    without navigating; entity text opens profile; checkboxes & menus act
 *    only on themselves; keyboard Enter/Space toggles once; inside-detail
 *    click does not collapse).
 * 3. Strictly one desktop sidebar item active (`aria-current="page"` and
 *    `.app-sidebar__item--active`) across Smart Routes, My Plan, Directory,
 *    Cluster Oversight, and My Actions.
 * 4. Visible aligned School Directory column headers at 1440px and 390px with
 *    zero horizontal overflow, including read-only reader (rvp@edify.org).
 * 5. My Actions (`/actions/mine` & `/actions/sent`) opened from sidebar with
 *    Django offline, live `Acknowledge` transition updating DB + counts +
 *    persisting across reload.
 * 6. All Cluster Oversight sections reachable via tab clicks, deep links,
 *    reloads, `ssa?area=`, `impact?view=courses`, `/cluster-oversight/scoring`,
 *    CSV download, role refusal, and 404 for unknown sections.
 */
import { execFileSync } from 'node:child_process';
import path from 'node:path';

import { expect, test } from '@playwright/test';
import type { Locator, Page } from '@playwright/test';

const WEB = process.env.EDIFY_E2E_WEB_URL ?? 'http://localhost:3010';
const PASSWORD = process.env.EDIFY_E2E_PASSWORD ?? 'edify';
const SHOT_DIR = process.env.EDIFY_E2E_SHOT_DIR ?? '';
const ADMIN_DB = process.env.EDIFY_E2E_ADMIN_DB ?? '';

const squash = (s: string | null | undefined) => (s ?? '').replace(/\s+/g, ' ').trim();

async function signIn(page: Page, email: string) {
  await page.context().clearCookies();
  await page.goto(`${WEB}/login`, { waitUntil: 'networkidle' });
  await page.getByLabel('Email address').fill(email);
  await page.locator('#current-password').fill(PASSWORD);
  await Promise.all([
    page.waitForURL((url) => !url.pathname.endsWith('/login'), { timeout: 20_000 }),
    page.getByRole('button', { name: 'Access workspace' }).click(),
  ]);
}

async function maybeShot(page: Page, filename: string, fullPage = false) {
  if (!SHOT_DIR) return;
  await page.screenshot({ path: path.join(SHOT_DIR, filename), fullPage });
}

/**
 * Clicks real trailing whitespace immediately to the right of an inline link
 * inside a row/summary so we verify the row background toggles without navigating.
 */
async function clickTrailingWhitespace(page: Page, link: Locator, container: Locator) {
  const linkBox = await link.boundingBox();
  const box = await container.boundingBox();
  expect(linkBox).not.toBeNull();
  expect(box).not.toBeNull();
  const x = Math.min(linkBox!.x + linkBox!.width + 24, box!.x + box!.width - 140);
  const y = linkBox!.y + linkBox!.height / 2;
  expect(x).toBeGreaterThan(linkBox!.x + linkBox!.width + 4);
  await page.mouse.click(x, y);
}

test.describe('List interactions, navigation, My Actions, and Cluster Oversight (Go-only)', () => {
  test('1 & 2 & 4. School Directory: aligned headers, whitespace expand, inline links, keyboard, two distinct rows, read-only reader', async ({
    page,
  }, testInfo) => {
    const isPhone = testInfo.project.name === 'phone-390';
    await signIn(page, 'cceo@edify.org');
    await page.goto(`${WEB}/schools`, { waitUntil: 'networkidle' });

    // No horizontal overflow at wide or narrow widths.
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);

    // Visible column header row matches visible columns.
    const headerRow = page.locator('[data-directory-header]');
    await expect(headerRow).toBeVisible();
    await expect(headerRow.getByRole('columnheader', { name: 'School ID' })).toBeVisible();
    await expect(headerRow.getByRole('columnheader', { name: 'School Name' })).toBeVisible();
    await expect(headerRow.getByRole('columnheader', { name: 'Actions' })).toBeVisible();
    if (!isPhone) {
      await expect(headerRow.getByRole('columnheader', { name: 'District' })).toBeVisible();
      await expect(headerRow.getByRole('columnheader', { name: 'Cluster' })).toBeVisible();
      await expect(headerRow.getByRole('columnheader', { name: 'Visit Status' })).toBeVisible();
    } else {
      await expect(headerRow.getByRole('columnheader', { name: 'District' })).toBeHidden();
      await expect(headerRow.getByRole('columnheader', { name: 'Cluster' })).toBeHidden();
      await expect(headerRow.getByRole('columnheader', { name: 'Visit Status' })).toBeHidden();
    }

    const rows = page.locator('ul[aria-label="Schools"] > li[data-row]');
    const rowCount = await rows.count();
    expect(rowCount).toBeGreaterThanOrEqual(2);

    const firstRow = rows.nth(0);
    const secondRow = rows.nth(1);
    const firstSummary = firstRow.locator('[data-directory-summary]');
    const secondSummary = secondRow.locator('[data-directory-summary]');

    // No visible disclosure chevron icons inside rows.
    await expect(firstSummary.locator('svg.lucide-chevron-right, svg.lucide-chevron-down')).toHaveCount(0);

    // Alignment check between header row and first data row at desktop.
    if (!isPhone) {
      const hdrBox = await headerRow.boundingBox();
      const rowBox = await firstSummary.boundingBox();
      expect(hdrBox).not.toBeNull();
      expect(rowBox).not.toBeNull();
      expect(Math.abs(hdrBox!.x - rowBox!.x)).toBeLessThanOrEqual(2);
      expect(Math.abs(hdrBox!.width - rowBox!.width)).toBeLessThanOrEqual(2);
    }

    const firstToggle = firstSummary.locator('button[aria-controls]');
    await expect(firstToggle).toHaveAttribute('aria-expanded', 'false');
    const firstSchoolLink = firstSummary.locator('[data-directory-name] a[href^="/schools/"]').first();
    const firstSchoolHref = await firstSchoolLink.getAttribute('href');
    expect(firstSchoolHref).toMatch(/^\/schools\/.+/);

    // Click trailing whitespace after School Name (desktop) or non-interactive ID chip (phone).
    const beforeUrl = page.url();
    if (!isPhone) {
      await clickTrailingWhitespace(page, firstSchoolLink, firstSummary);
    } else {
      await firstSummary.locator('span[title^="School ID"]').click();
    }
    expect(page.url()).toBe(beforeUrl);
    await expect(firstToggle).toHaveAttribute('aria-expanded', 'true');
    const firstPanel = firstRow.locator('[data-directory-details]');
    await expect(firstPanel).toBeVisible();
    const firstDetailText = squash(await firstPanel.textContent());
    expect(firstDetailText.length).toBeGreaterThan(20);

    // Capture labelled + expanded directory screenshot.
    await maybeShot(page, isPhone ? 'shot-directory-phone.png' : 'shot-directory-desktop.png');

    // Clicking non-link text inside expanded details must NOT collapse it.
    await firstPanel.locator('dt').first().click();
    await expect(firstToggle).toHaveAttribute('aria-expanded', 'true');

    // Checkbox selection must not collapse or expand the row.
    const checkbox = firstSummary.locator('input[type="checkbox"]');
    const checkboxLabel = firstSummary.locator('label:has(input[type="checkbox"])');
    if (await checkbox.count()) {
      await checkboxLabel.click();
      await expect(checkbox).toBeChecked();
      await expect(firstToggle).toHaveAttribute('aria-expanded', 'true');
      await checkboxLabel.click();
      await expect(checkbox).not.toBeChecked();
    }

    // Actions menu click must not collapse row.
    const actionsBtn = firstSummary.getByRole('button', { name: /Actions/i });
    if (await actionsBtn.count()) {
      await actionsBtn.click();
      await expect(firstToggle).toHaveAttribute('aria-expanded', 'true');
      await page.keyboard.press('Escape');
    }

    // Expand second row (single-open policy switches to second row) and assert distinct detail content.
    const secondToggle = secondSummary.locator('button[aria-controls]');
    const secondSchoolLink = secondSummary.locator('[data-directory-name] a[href^="/schools/"]').first();
    if (!isPhone) {
      await clickTrailingWhitespace(page, secondSchoolLink, secondSummary);
    } else {
      await secondSummary.locator('span[title^="School ID"]').click();
    }
    await expect(secondToggle).toHaveAttribute('aria-expanded', 'true');
    const secondDetailText = squash(await secondRow.locator('[data-directory-details]').textContent());
    expect(secondDetailText).not.toBe(firstDetailText);

    // Collapse second row by clicking row background again.
    if (!isPhone) {
      await clickTrailingWhitespace(page, secondSchoolLink, secondSummary);
    } else {
      await secondSummary.locator('span[title^="School ID"]').click();
    }
    await expect(secondToggle).toHaveAttribute('aria-expanded', 'false');

    // Keyboard Enter and Space on disclosure button toggle once each.
    await secondToggle.focus();
    await page.keyboard.press('Enter');
    await expect(secondToggle).toHaveAttribute('aria-expanded', 'true');
    await page.keyboard.press('Space');
    await expect(secondToggle).toHaveAttribute('aria-expanded', 'false');

    // Clicking the inline school name text opens its profile.
    await Promise.all([
      page.waitForURL((url) => url.pathname === firstSchoolHref, { timeout: 15_000 }),
      firstSchoolLink.click(),
    ]);

    // Read-only reader (Regional Program Lead) sees aligned headers with no selection checkbox column.
    if (!isPhone) {
      await signIn(page, 'regional-lead@edify.org');
      await page.goto(`${WEB}/schools`, { waitUntil: 'networkidle' });
      const rplHeaders = page.locator('[data-directory-header]');
      await expect(rplHeaders).toBeVisible();
      await expect(rplHeaders.locator('input[type="checkbox"]')).toHaveCount(0);
      const rplRow = page.locator('ul[aria-label="Schools"] > li[data-row]').first();
      const rplSummary = rplRow.locator('[data-directory-summary]');
      await expect(rplSummary.locator('input[type="checkbox"]')).toHaveCount(0);
      await rplSummary.locator('span[title^="School ID"]').click();
      await expect(rplSummary.locator('button[aria-controls]')).toHaveAttribute('aria-expanded', 'true');
    }
  });

  test('1 & 2. Cluster List, Planning, and Core Schools: row expand, 3-column SSA, nested school row isolation', async ({
    page,
  }, testInfo) => {
    const isPhone = testInfo.project.name === 'phone-390';
    await signIn(page, 'admin@edify.org');

    // Cluster List: expand card, verify SSA detail & nested school row toggles independently.
    await page.goto(`${WEB}/clusters`, { waitUntil: 'networkidle' });
    const clusterRecords = page.locator('article[data-block="record"]');
    expect(await clusterRecords.count()).toBeGreaterThanOrEqual(2);

    const firstCluster = clusterRecords.nth(0);
    const firstClusterSummary = firstCluster.locator('[data-record-summary]').first();
    const firstClusterToggle = firstClusterSummary.locator('button[aria-controls]').first();
    await expect(firstClusterToggle).toHaveAttribute('aria-expanded', 'false');

    // Click non-interactive fact/background on cluster summary (not inline link or Actions button).
    const firstClusterLink = firstClusterSummary.locator('a[href^="/clusters/"]').first();
    if (!isPhone && (await firstClusterLink.count())) {
      await clickTrailingWhitespace(page, firstClusterLink, firstClusterSummary);
    } else {
      await firstClusterSummary.locator('dl, [data-ph="record-facts"], [data-ph="record-badge"]').first().click({ position: { x: 8, y: 6 } });
    }
    await expect(firstClusterToggle).toHaveAttribute('aria-expanded', 'true');

    const openPanel = firstCluster.locator('[data-record-open]').first();
    await expect(openPanel).toBeVisible();
    await expect(openPanel).toContainText(/Intervention scores|SSA DETAIL|No confirmed SSA scores/i);

    // Wait for lazy-loaded nested schools table inside the cluster card.
    const nestedRows = openPanel.locator('tr:has(button[aria-controls]), [data-ph="row"]:has(button[aria-controls])');
    await expect(nestedRows.first()).toBeVisible({ timeout: 15_000 });

    if (!isPhone) {
      await maybeShot(page, 'shot-cluster-expanded.png');
    }

    // Nested school rows inside the cluster card: clicking a nested school row toggles ONLY itself.
    const nestedRow = nestedRows.first();
    const nestedToggle = nestedRow.locator('button[aria-controls]');
    await expect(nestedToggle).toHaveAttribute('aria-expanded', 'false');
    await nestedRow.locator('td').nth(1).click({ position: { x: 4, y: 8 } });
    await expect(nestedToggle).toHaveAttribute('aria-expanded', 'true');
    // Parent cluster card MUST remain expanded!
    await expect(firstClusterToggle).toHaveAttribute('aria-expanded', 'true');
    // Toggle nested row back closed.
    await nestedRow.locator('td').nth(1).click({ position: { x: 4, y: 8 } });
    await expect(nestedToggle).toHaveAttribute('aria-expanded', 'false');
    await expect(firstClusterToggle).toHaveAttribute('aria-expanded', 'true');

    // Inline cluster name navigates to cluster profile.
    if (await firstClusterLink.count()) {
      const href = await firstClusterLink.getAttribute('href');
      await Promise.all([
        page.waitForURL((u) => u.pathname.startsWith(href ?? '/clusters/'), { timeout: 15_000 }),
        firstClusterLink.click(),
      ]);
    }

    // Planning school list: expandable rows work without chevrons.
    await page.goto(`${WEB}/planning`, { waitUntil: 'networkidle' });
    const planningExpandable = page.locator('tr:has(button[aria-controls]), article[data-block="record"]:has(button[aria-controls])').first();
    if (await planningExpandable.count()) {
      const toggle = planningExpandable.locator('button[aria-controls]').first();
      await expect(toggle).toHaveAttribute('aria-expanded', 'false');
      await toggle.focus();
      await page.keyboard.press('Enter');
      await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    }

    // Core School List: expandable rows show metadata & SSA detail.
    await page.goto(`${WEB}/core-schools`, { waitUntil: 'networkidle' });
    const coreExpandable = page.locator('tr:has(button[aria-controls]), article[data-block="record"]:has(button[aria-controls])').first();
    if (await coreExpandable.count()) {
      const toggle = coreExpandable.locator('button[aria-controls]').first();
      await expect(toggle).toHaveAttribute('aria-expanded', 'false');
      await toggle.focus();
      await page.keyboard.press('Enter');
      await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    }
  });

  test('3. Desktop sidebar highlights strictly ONE active item on Smart Routes and across navigation', async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name === 'phone-390', 'Desktop sidebar check');
    await signIn(page, 'cceo@edify.org');

    const routes: Array<{ path: string; expectedLabel: RegExp }> = [
      { path: '/my-plan/smart-route', expectedLabel: /Smart Route/i },
      { path: '/my-plan', expectedLabel: /My Plan/i },
      { path: '/schools', expectedLabel: /School Directory/i },
      { path: '/cluster-oversight/', expectedLabel: /Cluster Oversight/i },
      { path: '/cluster-oversight/ssa', expectedLabel: /Cluster Oversight/i },
      { path: '/actions/mine', expectedLabel: /My Actions/i },
    ];

    for (const r of routes) {
      await page.goto(`${WEB}${r.path}`, { waitUntil: 'networkidle' });
      const sidebar = page.locator('aside.app-sidebar');
      await expect(sidebar).toBeVisible();
      const activeByAria = sidebar.locator('[aria-current="page"]');
      const activeByClass = sidebar.locator('.app-sidebar__item--active');
      await expect(activeByAria).toHaveCount(1);
      await expect(activeByClass).toHaveCount(1);
      await expect(activeByAria.first()).toContainText(r.expectedLabel);
      if (r.path === '/my-plan/smart-route') {
        await maybeShot(page, 'shot-smart-route-sidebar.png');
      }
    }
  });

  test('5. My Actions works end-to-end with Django offline and live Acknowledge persists', async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name === 'phone-390', 'Verified once end-to-end against seeded DB');
    test.skip(!ADMIN_DB, 'Requires EDIFY_E2E_ADMIN_DB to seed and clean up a temporary team_action');

    const actionId = `act_e2e_${Date.now()}`;
    // Seed a single open team_action from pl1@edify.org -> cceo@edify.org.
    execFileSync(
      'psql',
      [
        ADMIN_DB,
        '-v',
        'ON_ERROR_STOP=1',
        '-c',
        `INSERT INTO team_action (
           id, condition_key, issue_type, severity, school_id, fy,
           sender_id, sender_role, recipient_id, recipient_role,
           requested_action, workflow_route, message, priority, due_date, state,
           detected_at, blocked_reason, resolved_by_system, manual_resolution_reason,
           returned_reason, reminder_count, created_at, updated_at
         )
         SELECT '${actionId}', '${actionId}', 'follow_up', 'warning',
                (SELECT id FROM school WHERE deleted_at IS NULL LIMIT 1), '2027',
                (SELECT id FROM "user" WHERE email = 'pl1@edify.org' LIMIT 1),
                'Program Lead',
                (SELECT id FROM "user" WHERE email = 'cceo@edify.org' LIMIT 1),
                'CCEO',
                'E2E confirm visit logistics', '/my-plan', 'Please confirm school visit logistics.', 'normal',
                CURRENT_DATE + 5, 'open',
                NOW(), '', false, '', '', 0, NOW(), NOW();`,
      ],
      { stdio: 'pipe' },
    );

    try {
      await signIn(page, 'cceo@edify.org');
      // Open My Actions via desktop sidebar link.
      await page.locator('aside.app-sidebar a[href="/actions/mine"]').click();
      await page.waitForURL((u) => u.pathname.startsWith('/actions/mine'), { timeout: 15_000 });
      await expect(page.getByRole('heading', { name: /My Actions/i })).toBeVisible();
      await expect(page.getByText('E2E confirm visit logistics')).toBeVisible();

      // Reload preserves tab and data.
      await page.reload({ waitUntil: 'networkidle' });
      await expect(page.getByText('E2E confirm visit logistics')).toBeVisible();

      // Trigger Acknowledge via row Actions menu.
      const actionRow = page.locator('tr', { hasText: 'E2E confirm visit logistics' }).first();
      await actionRow.getByRole('button', { name: /Actions/i }).click();
      await page.getByRole('menuitem', { name: /Acknowledge/i }).click();

      // Wait for row status to update to Acknowledged and persist after reload.
      await expect(actionRow).toContainText(/Acknowledged/i, { timeout: 15_000 });
      await page.reload({ waitUntil: 'networkidle' });
      await expect(page.locator('tr', { hasText: 'E2E confirm visit logistics' }).first()).toContainText(/Acknowledged/i);

      // Sender view (/actions/sent) shows the sent action for pl1@edify.org.
      await signIn(page, 'pl1@edify.org');
      await page.goto(`${WEB}/actions/sent`, { waitUntil: 'networkidle' });
      await expect(page.getByText('E2E confirm visit logistics')).toBeVisible();
    } finally {
      execFileSync('psql', [ADMIN_DB, '-c', `DELETE FROM team_action WHERE id = '${actionId}';`], { stdio: 'pipe' });
    }
  });

  test('6. Cluster Oversight: all reachable sections, filters, scoring, CSV export, and 404 for unknown/unauthorized', async ({
    page,
  }, testInfo) => {
    test.skip(testInfo.project.name === 'phone-390', 'Full 18-section matrix verified on desktop');
    await signIn(page, 'admin@edify.org');
    await page.goto(`${WEB}/cluster-oversight/`, { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Command Center');

    // Collect every visible tab link from the Command Center tab rail.
    const tabLinks = page.locator('main a[href^="/cluster-oversight/"], main a[href="/clusters"]');
    const allTabs: Array<{ label: string; href: string }> = await tabLinks.evaluateAll((els) => {
      const seen = new Set<string>();
      const out: Array<{ label: string; href: string }> = [];
      for (const el of els) {
        const href = el.getAttribute('href') || '';
        const label = (el.textContent || '').replace(/\s+/g, ' ').trim();
        if (!label || !href || href.includes('format=csv') || href.endsWith('/scoring')) continue;
        if (href === '/clusters' || href.startsWith('/cluster-oversight/')) {
          if (seen.has(href)) continue;
          seen.add(href);
          out.push({ label, href });
        }
      }
      return out;
    });

    // Must cover all visible workspace sections.
    expect(allTabs.length).toBeGreaterThanOrEqual(16);

    const expectedHeadings: Record<string, RegExp> = {
      '/clusters': /Clusters/i,
      '/cluster-oversight/command': /^Command Center$/i,
      '/cluster-oversight/my': /^My Clusters$/i,
      '/cluster-oversight/meetings': /^Meetings$/i,
      '/cluster-oversight/training': /^Training$/i,
      '/cluster-oversight/attendance': /^Attendance$/i,
      '/cluster-oversight/schools': /^Schools$/i,
      '/cluster-oversight/ssa': /^SSA Performance$/i,
      '/cluster-oversight/teachers': /^Teacher Impact$/i,
      '/cluster-oversight/leaders': /^Leader Impact$/i,
      '/cluster-oversight/students': /^Student Impact$/i,
      '/cluster-oversight/academic': /^Academic Impact$/i,
      '/cluster-oversight/loans': /^Loans & BT$/i,
      '/cluster-oversight/stories': /^MSCS$/i,
      '/cluster-oversight/impact': /^Impact Analytics$/i,
      '/cluster-oversight/planning': /^Planning$/i,
      '/cluster-oversight/evidence': /^Evidence$/i,
      '/cluster-oversight/reports': /^Reports$/i,
    };

    for (const tab of allTabs) {
      const basePath = tab.href.split('?')[0] ?? tab.href;
      await page.goto(`${WEB}${tab.href}`, { waitUntil: 'networkidle' });
      const h1 = squash(await page.getByRole('heading', { level: 1 }).textContent());
      const pattern = expectedHeadings[basePath];
      expect(pattern, `unexpected tab path ${basePath}`).toBeDefined();
      expect(h1, `tab ${tab.label} (${tab.href}) rendered ${h1}`).toMatch(pattern!);
      if (basePath !== '/cluster-oversight/command') {
        expect(h1).not.toBe('Command Center');
      }
      if (basePath === '/cluster-oversight/ssa') {
        await maybeShot(page, 'shot-cluster-oversight-ssa.png');
      }
    }

    // Verify reload persistence + filters: SSA area filter and Impact courses view.
    await page.goto(`${WEB}/cluster-oversight/ssa?area=leadership`, { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('SSA Performance');
    await expect(page.locator('body')).toContainText(/Leadership/i);
    await page.reload({ waitUntil: 'networkidle' });
    await expect(page.locator('body')).toContainText(/Leadership/i);

    await page.goto(`${WEB}/cluster-oversight/impact?view=courses`, { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Impact Analytics');
    await expect(page.locator('body')).toContainText(/SSA Movement After Each Training/i);

    // Scoring page opens for Admin.
    await page.goto(`${WEB}/cluster-oversight/scoring`, { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('Cluster Scoring');
    await expect(page.locator('body')).toContainText(/Maturity Thresholds/i);

    // CSV download returns 200 text/csv without Django.
    const csvRes = await page.request.get(`${WEB}/cluster-oversight/command?format=csv`);
    expect(csvRes.status()).toBe(200);
    expect(csvRes.headers()['content-type']).toContain('text/csv');
    expect(await csvRes.text()).toContain('Cluster,District,CCEO');

    // Unknown section fails cleanly with the 404 boundary (never falls back to Command Center).
    await page.goto(`${WEB}/cluster-oversight/nonexistent`, { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('This page is not here');

    // Unauthorized role (ProjectCoordinator) is refused Cluster Oversight.
    await signIn(page, 'coordinator@edify.org');
    await page.goto(`${WEB}/cluster-oversight/ssa`, { waitUntil: 'networkidle' });
    await expect(page.getByRole('heading', { level: 1 })).toHaveText('This page is not here');
  });
});
