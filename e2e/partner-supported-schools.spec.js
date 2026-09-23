// Partner-supported schools, end to end in a real browser (owner, 2026-09-23).
//
// Partner support changes delivery responsibility, not school ownership. The
// eight journeys below walk that rule through the pages people use: the
// school stays on Planning with its owner beside the Partner's name, staff
// plan only the whitelisted direct work there, Cluster Planning stays open,
// Partner work runs through the Partner's own My Plan, IA and payment, and
// Partner Monitoring shows each Partner's work in its own table.
//
// State the browser cannot produce on its own — a handover to set up, a
// Partner's evidence, an IA verification, a Partner's return — is created by
// scripts/e2e_partner_support_fixture.py through the canonical services, never
// by writing rows. The mutating journeys run once, on chromium-desktop; the
// read-only layout checks run on every project, including tablet and phone.

const { test, expect } = require('@playwright/test');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const { signIn } = require('./helpers/auth');

const root = path.resolve(__dirname, '..');
const pythonBin = (() => {
  if (process.env.PYTHON) return process.env.PYTHON;
  const venv = path.join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  return fs.existsSync(venv) ? venv : 'python';
})();

function fixture(...args) {
  const out = execFileSync(pythonBin, [path.join(root, 'scripts/e2e_partner_support_fixture.py'), ...args], {
    cwd: root,
    env: { ...process.env, PYTHONPATH: root },
    encoding: 'utf8',
  });
  const lines = out.trim().split('\n');
  return JSON.parse(lines[lines.length - 1]);
}

const PASSWORD = process.env.DEMO_LOGIN_PASSWORD || 'edify';
const EVIDENCE = path.join(root, 'test-results', 'partner-supported-schools');

async function shoot(page, name, testInfo) {
  fs.mkdirSync(EVIDENCE, { recursive: true });
  await page.screenshot({ path: path.join(EVIDENCE, `${testInfo.project.name}-${name}.png`), fullPage: false });
}

async function planningRow(page, school, fy) {
  const year = fy ? `&fy=${fy}` : '';
  await page.goto(`/planning?tab=client&q=${encodeURIComponent(school.school_id)}${year}`);
  // By school ID: the demo directory holds several schools with one name.
  const row = page.locator(`.planning-school-row:has(input[value="${school.school_id}"])`);
  await expect(row).toBeVisible();
  return row;
}

async function setDrawerDate(page, isoDate) {
  await page.evaluate(date => {
    const holder = [...document.querySelectorAll('#drawer-container [x-data]')]
      .find(el => window.Alpine && 'selectedDate' in window.Alpine.$data(el));
    window.Alpine.$data(holder).selectedDate = date;
  }, isoDate);
}

// An activity is on a My Plan when one of its row actions points at it.
function activityControls(page, id) {
  return page.locator(`[href*="${id}"], [hx-get*="/${id}"]`);
}

async function noPageOverflow(page) {
  return page.evaluate(() => {
    const main = document.querySelector('main') || document.body;
    return {
      document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      main: main.scrollWidth - main.clientWidth,
    };
  });
}

let data;
let days;

test.describe.configure({ mode: 'serial' });
test.use({ video: 'off', serviceWorkers: 'block' });

test.beforeAll(() => {
  fixture('reset');
  data = fixture('setup');
  // Weekdays the calendar policy accepts, each with its financial year: late
  // in the year the later ones fall in the next FY, and the Planning page is
  // read for the year the work is in.
  days = fixture('dates', '6').dates;
});

test.describe('Partner-supported schools — journeys', () => {
  test.beforeEach(({}, testInfo) => {
    test.skip(testInfo.project.name !== 'chromium-desktop', 'mutating journeys run once, on desktop Chromium');
  });

  test('J1 · a Partner-supported school stays on Planning with its owner', async ({ page }, testInfo) => {
    const [hope] = data.handovers;
    await signIn(page, 'cceo@edify.org', PASSWORD);
    const row = await planningRow(page, hope);

    const responsible = row.locator('[data-responsible="partner"] .planning-responsible');
    await expect(responsible).toContainText('Partner');
    await expect(responsible).toContainText(hope.partner);
    // The owner is unchanged; like every school's, it sits in the row's
    // details, which the name opens.
    await row.locator('.school-plan-table__name-toggle').click();
    await expect(page.locator(`#planning-school-details-${hope.school_pk}`)).toContainText(data.cceo_name);
    await expect(row.getByRole('button', { name: `Schedule activity for ${hope.name}` })).toBeEnabled();
    // The shared Visit and Training Status badges, beside the school's name.
    await expect(row.locator('[data-planning-badges="visits"] .school-planning-badge').first()).toBeVisible();
    await expect(row.locator('[data-planning-badges="trainings"] .school-planning-badge').first()).toBeVisible();

    const facts = fixture('inspect', hope.school_id);
    expect(facts.assignments).toBe(1);
    await shoot(page, 'j1-planning-row', testInfo);
  });

  test('J2 · Data Gathering, Content Gathering and Donor Visit are planned directly', async ({ page }, testInfo) => {
    const [hope] = data.handovers;
    const known = new Set(fixture('inspect', hope.school_id).activities.map(a => a.id));
    await signIn(page, 'cceo@edify.org', PASSWORD);
    const planned = [];
    for (const [index, purpose] of ['donor_visit', 'story_gathering', 'ssa_support'].entries()) {
      const row = await planningRow(page, hope);
      await row.getByRole('button', { name: `Schedule activity for ${hope.name}` }).click();
      const drawer = page.locator('#drawer-container');
      await expect(drawer.locator('[data-partner-support-notice]')).toContainText(hope.partner);
      await drawer.locator('#purpose_of_visit').selectOption(purpose);
      await setDrawerDate(page, days[index].date);
      await drawer.locator('#activity_purpose_text').fill(`E2E ${purpose} at a Partner-supported school`);
      await drawer.locator('.schedule-drawer-submit').click();
      await expect(page.locator('#drawer-container .schedule-drawer-submit')).toHaveCount(0, { timeout: 15_000 });
      planned.push(purpose);
      if (index === 0) await shoot(page, 'j2-scheduled', testInfo);
    }

    const facts = fixture('inspect', hope.school_id);
    const staffWork = facts.activities.filter(a => !known.has(a.id));
    expect(staffWork.map(a => a.type).sort()).toEqual(
      ['donor_visit', 'school_visit_ssa_collection', 'story_gathering_visit'].sort(),
    );
    for (const activity of staffWork) {
      expect(activity.responsible).toBeTruthy();
      expect(activity.delivery).toBe('staff');
    }
    expect(facts.assignments).toBe(1);

    await page.goto(`/my-plan?q=${encodeURIComponent(hope.name)}`);
    for (const activity of staffWork) {
      await expect(activityControls(page, activity.id).first()).toBeAttached();
    }
    await shoot(page, 'j2-my-plan', testInfo);
  });

  test('J3 · other direct support is explained in the drawer and refused by the server', async ({ page, context }, testInfo) => {
    const [hope] = data.handovers;
    await signIn(page, 'cceo@edify.org', PASSWORD);
    const row = await planningRow(page, hope);
    await row.getByRole('button', { name: `Schedule activity for ${hope.name}` }).click();
    const drawer = page.locator('#drawer-container');
    await expect(drawer.locator('[data-partner-lock-reason]')).toContainText(
      'Staff may directly plan Data Gathering, Content Gathering, or Donor Visits',
    );
    for (const locked of ['in_school_training', 'training_follow_up', 'social_visit']) {
      await expect(drawer.locator(`#purpose_of_visit option[value="${locked}"]`)).toBeDisabled();
    }
    await shoot(page, 'j3-locked-purposes', testInfo);

    const before = fixture('inspect', hope.school_id).activities.length;
    const csrf = (await context.cookies()).find(c => c.name === 'csrftoken');
    const response = await page.request.post('/planning/schedule-action', {
      form: {
        school_id: hope.school_id,
        scheduled_date: days[3].date,
        purpose_of_visit: 'social_visit',
        activity_purpose_text: 'Manipulated request',
        require_catalogue: 'yes',
      },
      headers: { 'X-CSRFToken': csrf ? csrf.value : '', 'HX-Request': 'true' },
    });
    expect(response.status()).toBe(400);
    expect(await response.text()).toContain(`supported by ${hope.partner}`);
    expect(fixture('inspect', hope.school_id).activities.length).toBe(before);
  });

  test('J4 · Cluster Planning adds the Partner-supported school by name', async ({ page }, testInfo) => {
    const [hope] = data.handovers;
    await signIn(page, 'cceo@edify.org', PASSWORD);
    await page.goto(`/clusters/${hope.cluster_id}`);
    const row = page.locator(`tr:has([hx-get$="school_id=${hope.school_id}"])`);
    await expect(row).toBeVisible({ timeout: 15_000 });
    await expect(row.locator('[data-responsible="partner"]').first()).toBeVisible();
    await row.locator('[data-add-to-cluster="meeting"]').click();

    const drawer = page.locator('#drawer-container');
    await expect(drawer.locator(`input[name="invited_school_ids"][value="${hope.school_pk}"]`)).toBeChecked();
    await shoot(page, 'j4-cluster-drawer', testInfo);
    await setDrawerDate(page, days[2].date);
    await drawer.locator('textarea[name="activity_goal"]').fill('E2E cluster meeting with a Partner-supported school');
    await drawer.locator('button[type="submit"]').last().click();
    await expect(page.locator('#drawer-container button[type="submit"]')).toHaveCount(0, { timeout: 15_000 });

    const planningAfter = await planningRow(page, hope, days[2].fy);
    await expect(planningAfter.locator('[data-planning-badges="trainings"]')).toContainText('Planned');
    await shoot(page, 'j4-training-badges', testInfo);
  });

  test('J5 · the Partner schedules; staff see the badge, not the work', async ({ page }, testInfo) => {
    const [hope] = data.handovers;
    // The Partner, in the Partner portal.
    await signIn(page, 'partner@edify.org', PASSWORD);
    await page.goto('/partner/assignments');
    const card = page.locator(`[href*="${hope.assignment_id}"], [hx-get*="${hope.assignment_id}"]`).first();
    await expect(card).toBeAttached({ timeout: 15_000 });
    await page.goto(`/partner/assignments/${hope.assignment_id}`);
    await page.locator(`[hx-get*="/partner/assignments/${hope.assignment_id}/schedule-drawer"]`).first().click();
    const drawer = page.locator('#drawer-container');
    const dateInput = drawer.locator('input[name="scheduled_date"]');
    if ((await dateInput.getAttribute('type')) === 'hidden') {
      await setDrawerDate(page, days[4].date);
    } else {
      await dateInput.fill(days[4].date);
    }
    await drawer.locator('input[name="delivery_contact_name"]').fill('Grace Visitor');
    await drawer.getByRole('button', { name: 'Submit' }).click();
    await expect(page.locator('#drawer-container input[name="delivery_contact_name"]')).toHaveCount(0, { timeout: 15_000 });

    const facts = fixture('inspect', hope.school_id);
    const partnerWork = facts.activities.find(a => a.delivery === 'partner');
    expect(partnerWork).toBeTruthy();
    expect(partnerWork.staff_fundable).toBe(false);

    await page.goto('/my-plan');
    await expect(activityControls(page, partnerWork.id).first()).toBeAttached();
    await shoot(page, 'j5-partner-my-plan', testInfo);

    // Staff: the badge moves, the work stays off their My Plan.
    await page.context().clearCookies();
    await signIn(page, 'cceo@edify.org', PASSWORD);
    const row = await planningRow(page, hope, partnerWork.fy);
    await expect(row.locator('[data-planning-badges="visits"]')).toContainText('Planned');
    await expect(row.locator('[data-partner-workflow]')).toContainText('Scheduled');
    await expect(row.locator('.planning-responsible[data-responsible="partner"]')).toContainText(hope.partner);
    await page.goto('/my-plan');
    await expect(activityControls(page, partnerWork.id)).toHaveCount(0);
    // Partner Monitoring reads one financial year; the Partner dated this work
    // into the year its activity carries.
    await page.goto(`/partner-oversight/?partner=${hope.partner_id}&fy=${partnerWork.fy}`);
    const monitored = page.locator(`tr[data-assignment="${hope.assignment_id}"]`);
    await expect(monitored).toContainText('Scheduled');
    await expect(monitored).toContainText('Grace Visitor');
    await shoot(page, 'j5-monitoring-scheduled', testInfo);
  });

  test('J6 · evidence and IA verification move the badge and the monitoring row', async ({ page }, testInfo) => {
    const [hope] = data.handovers;
    const progressed = fixture('partner-progress', hope.assignment_id);
    expect(progressed.status).toBe('awaiting_ia_verification');

    const fy = fixture('inspect', hope.school_id).activities.find(a => a.id === progressed.activity_id).fy;
    await signIn(page, 'cceo@edify.org', PASSWORD);
    let row = await planningRow(page, hope, fy);
    await expect(row.locator('[data-planning-badges="visits"]')).toContainText('Awaiting Verification');
    await page.goto(`/partner-oversight/?partner=${hope.partner_id}&fy=${fy}`);
    let monitored = page.locator(`tr[data-assignment="${hope.assignment_id}"]`);
    await expect(monitored).toContainText('Evidence Submitted');
    await expect(monitored).toContainText('Pending');
    await shoot(page, 'j6-under-ia-review', testInfo);

    const verified = fixture('ia-verify', progressed.activity_id);
    expect(verified.ia).toBe('confirmed');

    row = await planningRow(page, hope, fy);
    await expect(row.locator('[data-planning-badges="visits"]')).toContainText('1 Complete');
    await page.goto(`/partner-oversight/?partner=${hope.partner_id}&fy=${fy}`);
    monitored = page.locator(`tr[data-assignment="${hope.assignment_id}"]`);
    await expect(monitored).toContainText('Verified');
    await expect(monitored).toContainText('Awaiting Payment');
    await shoot(page, 'j6-verified', testInfo);

    expect(fixture('inspect', hope.school_id).partner_credits).toBe(0);
  });

  test('J7 · each Partner is its own table for the Programme Lead', async ({ page }, testInfo) => {
    await signIn(page, data.pl_email, PASSWORD);
    for (const handover of data.handovers.slice(0, 3)) {
      await page.goto(`/partner-oversight/?partner=${handover.partner_id}`);
      const table = page.locator('[data-partner-monitoring-table]');
      await expect(table).toHaveCount(1);
      await expect(table).toContainText(handover.name);
      await expect(table).toContainText(data.cceo_name);
      for (const other of data.handovers.filter(h => h.partner_id !== handover.partner_id)) {
        await expect(table.locator(`tr[data-assignment="${other.assignment_id}"]`)).toHaveCount(0);
      }
      const tab = page.locator('.oversight-entity-tabs__link.is-active .oversight-entity-tabs__count');
      const summary = page.locator('[data-monitoring-summary]');
      const assigned = parseInt((await summary.textContent()).trim(), 10);
      expect(parseInt((await tab.textContent()).trim(), 10)).toBe(assigned);
      await shoot(page, `j7-${handover.partner.replace(/\s+/g, '-').toLowerCase()}`, testInfo);
    }
  });

  test('J8 · a Partner return is flagged on Planning and resolved once', async ({ page }, testInfo) => {
    const returned = data.handovers[3];
    fixture('partner-return', returned.assignment_id);
    const before = fixture('inspect', returned.school_id);

    await signIn(page, 'cceo@edify.org', PASSWORD);
    const row = await planningRow(page, returned);
    await expect(row.locator('[data-partner-workflow="returned"]')).toContainText('Partner Returned — Staff Action Required');
    await shoot(page, 'j8-planning-returned', testInfo);

    await page.goto(`/partner-oversight/?partner=${returned.partner_id}&status=returned`);
    const monitored = page.locator(`tr[data-assignment="${returned.assignment_id}"]`);
    await expect(monitored.locator('[title*="national examinations"]')).toHaveCount(1);
    await monitored.getByRole('button', { name: 'Resolve Exception' }).click();
    const drawer = page.locator('#drawer-container');
    await expect(drawer).toContainText('The school is closed for national examinations.');
    await drawer.locator('input[name="resolution"][value="staff_delivery"]').check();
    await shoot(page, 'j8-resolve-drawer', testInfo);
    await Promise.all([
      page.waitForEvent('load'),
      drawer.getByRole('button', { name: 'Record decision' }).click(),
    ]);

    const after = fixture('inspect', returned.school_id);
    expect(after.assignments).toBe(before.assignments);
    expect(after.activities.length).toBe(before.activities.length);
    const planningAfter = await planningRow(page, returned);
    await expect(planningAfter.locator('[data-partner-workflow="returned"]')).toHaveCount(0);
    await expect(planningAfter.locator('.planning-responsible[data-responsible="staff"]')).toContainText(data.cceo_name);
  });
});

test.describe('Partner-supported schools — layout on every screen', () => {
  test('Planning and Partner Monitoring fit the screen and keep their controls on one line', async ({ page }, testInfo) => {
    const [hope] = data.handovers;
    await signIn(page, 'cceo@edify.org', PASSWORD);
    const row = await planningRow(page, hope);
    await expect(row.locator('[data-responsible]').first()).toBeVisible();
    const indicator = row.locator('[data-planning-badges="visits"] .school-planning-badge').first();
    const box = await indicator.boundingBox();
    const lineHeight = await indicator.evaluate(el => parseFloat(getComputedStyle(el).lineHeight) || 16);
    expect(box.height).toBeLessThan(lineHeight * 2 + 8);
    expect((await noPageOverflow(page)).document).toBeLessThanOrEqual(1);
    await shoot(page, 'layout-planning', testInfo);

    await page.goto(`/partner-oversight/?partner=${hope.partner_id}`);
    const table = page.locator('[data-partner-monitoring-table]');
    await expect(table).toBeVisible();
    const headers = await table.locator('thead th').evaluateAll(cells =>
      cells.map(cell => cell.getBoundingClientRect().height),
    );
    expect(Math.max(...headers) - Math.min(...headers)).toBeLessThanOrEqual(2);
    expect((await noPageOverflow(page)).document).toBeLessThanOrEqual(1);
    await shoot(page, 'layout-monitoring', testInfo);
  });
});
