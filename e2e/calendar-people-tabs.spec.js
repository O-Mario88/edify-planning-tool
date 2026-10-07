// Whose calendar a reader may open (owner, 2026-10-07): "can we have leads
// have access to calendar page for their cceo, cd to have calendar for every
// one organized by tabs with theirs first", then "make sure the table pill
// counters are also accurate and refreshes with changing data" and "calendar
// oversights are strictly read only".
//
// The rules are pinned in apps/frontend/test_calendar_people_tabs.py. What
// only a browser can say is here: a tab keeps the month and the kind of event
// chosen in the page, the strip scrolls inside itself on a phone, and the
// page is whole after it reads its live part again.
const { test, expect } = require('@playwright/test');
const { signIn } = require('./helpers/auth');

test.use({ video: 'off', trace: 'off', serviceWorkers: 'block' });

// The demo seed's work is dated April 2026.
const MONTH = '/calendar?year=2026&month=4';
const strips = page => page.locator('.calendar-workspace__people nav');
const pill = tab => tab.locator('.oversight-entity-tabs__count');
const activities = page =>
  page.locator('.calendar-workspace__filters button').nth(1).locator('.calendar-workspace__filter-count');

test("a Programme Lead opens a CCEO's calendar from the strip, and only reads it", async ({ page }) => {
  await signIn(page, 'pl1@edify.org', 'edify', { acceptRequiredAgreements: false });
  await page.goto(MONTH);

  const people = strips(page).first().locator('a');
  await expect(strips(page)).toHaveCount(1);
  await expect(people.first()).toHaveText(/My calendar/);
  await expect(people.first()).toHaveAttribute('aria-current', 'page');
  expect(await people.count()).toBeGreaterThan(1);

  // The kind of event chosen in the page goes with the reader to the tab.
  await page.locator('.calendar-workspace__filters button').nth(1).click();
  const officer = people.nth(1);
  const name = (await officer.locator('span').first().textContent()).trim();
  const count = (await pill(officer).textContent()).trim();
  await officer.click();
  await expect(page).toHaveURL(/person=/);
  const url = new URL(page.url());
  expect(url.searchParams.get('month')).toBe('4');
  expect(url.searchParams.get('event_kind')).toBe('activity');

  const open = strips(page).first().locator('a[aria-current="page"]');
  await expect(open).toHaveCount(1);
  await expect(open.locator('span').first()).toHaveText(name);
  // The number on the tab is the number of activities its calendar counts.
  await expect(pill(open)).toHaveText(count);
  await expect(activities(page)).toHaveText(count);

  // Read, never run: nothing to tick, no bar, no action in the header.
  await expect(page.locator('#calendar-workspace input[type="checkbox"]')).toHaveCount(0);
  await expect(page.locator('[data-activity-bar]')).toHaveCount(0);
  await expect(page.getByRole('link', { name: 'Apply for Leave' })).toHaveCount(0);
  expect(await page.locator('#calendar-workspace form').evaluateAll(forms =>
    forms.map(form => (form.getAttribute('method') || 'get').toLowerCase()))).toEqual(['get']);

  // The page reads its live part again when the plan changes
  // (static/js/live-regions.js): the strip is in it, and is whole afterwards.
  await page.evaluate(() => new Promise(resolve => {
    document.addEventListener('edify:live-refreshed', () => setTimeout(resolve, 100), { once: true });
    window.EdifyLive.refresh();
  }));
  await expect(strips(page).first().locator('a[aria-current="page"] span').first()).toHaveText(name);
  await expect(pill(strips(page).first().locator('a[aria-current="page"]'))).toHaveText(count);

  await strips(page).first().locator('a').first().click();
  await expect(page).not.toHaveURL(/person=/);
  await expect(page.getByRole('link', { name: 'Apply for Leave' })).toHaveCount(1);
});

test("the Country Director has their own calendar first, then every team's and its people", async ({ page }) => {
  await signIn(page, 'cd@edify.org', 'edify', { acceptRequiredAgreements: false });
  await page.goto(MONTH);

  await expect(strips(page)).toHaveCount(1);
  const teams = strips(page).first().locator('a');
  await expect(teams.first()).toHaveText(/My calendar/);
  await expect(teams.first()).toHaveAttribute('aria-current', 'page');
  expect(await teams.count()).toBeGreaterThan(1);

  const team = (await teams.nth(1).locator('span').first().textContent()).trim();
  const total = Number((await pill(teams.nth(1)).textContent()).trim());
  await teams.nth(1).click();

  // A team opens on its first person, with its people in a strip of their own.
  await expect(strips(page)).toHaveCount(2);
  await expect(strips(page).nth(1)).toHaveAttribute('aria-label', team);
  const members = strips(page).nth(1).locator('a');
  await expect(members.first()).toHaveAttribute('aria-current', 'page');
  const each = await members.locator('.oversight-entity-tabs__count').allTextContents();
  expect(each.map(Number).reduce((sum, value) => sum + value, 0)).toBe(total);

  if (await members.count() > 1) {
    const count = (await pill(members.nth(1)).textContent()).trim();
    await members.nth(1).click();
    await expect(strips(page).nth(1).locator('a[aria-current="page"]')).toHaveCount(1);
    await expect(activities(page)).toHaveText(count);
  }
  await expect(page.locator('#calendar-workspace input[type="checkbox"]')).toHaveCount(0);
  await expect(page.locator('.calendar-event-composer')).toHaveCount(0);
});

test('on a phone the strip scrolls inside itself and the page does not', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await signIn(page, 'cd@edify.org', 'edify', { acceptRequiredAgreements: false });
  await page.goto(MONTH);
  await strips(page).first().locator('a').nth(1).click();
  await expect(strips(page)).toHaveCount(2);

  for (const strip of await strips(page).all()) {
    const box = await strip.evaluate(nav => ({
      rows: new Set([...nav.querySelectorAll('a')].map(a => Math.round(a.getBoundingClientRect().top))).size,
      right: nav.getBoundingClientRect().right,
    }));
    expect(box.rows).toBe(1);
    expect(box.right).toBeLessThanOrEqual(390);
  }
  expect(await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
});
