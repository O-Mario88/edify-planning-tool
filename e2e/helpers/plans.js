/*
 * A My Plan row with an Actions menu for the signed-in officer.
 *
 * The demo seed is a deterministic April-2026 fixture whose activities are
 * all completed, and since 2026-09-19 a completed row offers "Complete" (the
 * record) instead of the Actions menu, while My Plan lists upcoming work only
 * (2026-09-20). A journey that needs the menu therefore schedules one visit
 * a few days out through the same endpoint the Core Schools drawer posts to,
 * once, and reuses it on every later call in the run.
 */
const { expect } = require('@playwright/test');

const iso = (daysAhead) => {
  const d = new Date();
  d.setDate(d.getDate() + daysAhead);
  return d.toISOString().slice(0, 10);
};

const firstOptions = (html, name) => {
  const select = html.match(new RegExp(`<select[^>]*name="${name}"[\\s\\S]*?</select>`, 'i'));
  return select ? [...select[0].matchAll(/<option[^>]*value="([^"]*)"/g)].map((m) => m[1]).filter(Boolean) : [];
};

async function ensureActionableRow(page) {
  await page.goto('/my-plan');
  if (await page.locator('.row-menu__trigger').count()) return;

  await page.goto('/core-schools');
  const schedule = page.locator('.school-record-action[hx-get*="schedule-activity"]').first();
  await expect(schedule).toBeVisible();
  const schoolId = new URL(await schedule.getAttribute('hx-get'), page.url()).searchParams.get('school_id');
  expect(schoolId, 'a core school to schedule at').toBeTruthy();

  // The Schedule button opens a chooser; the visit form is one step in.
  const drawer = await page.request.get(`/core-schools/schedule-visit?school_id=${schoolId}`, { headers: { 'HX-Request': 'true' } });
  expect(drawer.ok(), 'the schedule visit drawer renders').toBe(true);
  const html = await drawer.text();
  const purposes = firstOptions(html, 'purpose_of_visit');
  const purpose = purposes.includes('ssa_support') ? 'ssa_support' : purposes.find((v) => v !== 'in_school_training');
  expect(purpose, 'a visit purpose to choose').toBeTruthy();

  const csrf = (await page.context().cookies()).find((c) => c.name === 'csrftoken')?.value;
  // No responsible_staff_id: the action then books the visit for the
  // signed-in officer, which is whose My Plan the journey reads.
  const form = {
    school_id: schoolId,
    purpose_of_visit: purpose,
    visit_number: '1',
    scheduled_date: iso(3),
    delivery_type: 'staff',
    visit_justification: 'Browser journey fixture: one upcoming visit so the row menu exists.',
    activity_goal: 'Browser journey fixture',
  };
  const response = await page.request.post('/core-schools/schedule-visit/action', {
    form,
    headers: { 'X-CSRFToken': csrf || '', 'HX-Request': 'true', Referer: page.url() },
  });
  expect(response.status(), `scheduling a visit: ${(await response.text()).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 300)}`).toBeLessThan(400);

  await page.goto('/my-plan');
  await expect(page.locator('.row-menu__trigger').first()).toBeVisible();
}

module.exports = { ensureActionableRow };
