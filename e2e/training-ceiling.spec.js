const { test, expect } = require('@playwright/test');
const { signIn } = require('./helpers/auth');

test.use({ video: 'off', trace: 'off', serviceWorkers: 'block' });

// The training ceiling in the Group Training drawer (owner, 2026-10-06).
//
// A Programme Lead sets how many schools an officer may schedule for a
// training in a fiscal year. The drawer asks for the training first, shows the
// SSA intervention the Training Catalogue links it to as a read-only field,
// and counts on from what the officer has already scheduled: "18 / 20". At the
// ceiling the schools not yet ticked are greyed and cannot be ticked, and the
// drawer says the ceiling is reached.
//
// The save counts again on the server behind a row lock
// (apps/planning/test_training_ceilings.py, test_training_ceiling_concurrency.py);
// this spec pins what only a browser can show. The capacity answer is stubbed,
// so the spec reads the page and writes nothing.
function capacity(scheduled, ceiling) {
  return {
    managed: true,
    ceiling,
    scheduled,
    group: scheduled,
    inSchool: 0,
    remaining: Math.max(ceiling - scheduled, 0),
    staffName: 'Paul N.',
    fy: '2027',
  };
}

async function openGroupDrawer(page) {
  await page.goto('/clusters');
  await page.waitForLoadState('networkidle');
  await page.getByRole('button', { name: 'Schedule Group Training', exact: true }).click();
  const drawer = page.locator('.drawer-surface.active');
  await expect(drawer).toBeVisible();
  await expect(drawer.locator('#cluster-planner-form')).toBeVisible();
  return drawer;
}

async function chooseTraining(page, drawer, label) {
  const answered = page.waitForResponse(response => response.url().includes('/planning/training-capacity'));
  await drawer.locator('#training_activity').selectOption({ label });
  await answered;
}

const boxes = drawer => drawer.locator('input[name=invited_school_ids]');

test.describe('Group Training drawer holds the training ceiling', () => {
  test('the training comes first and brings its SSA intervention', async ({ page }) => {
    await signIn(page, 'cceo@edify.org', 'edify', { acceptRequiredAgreements: false });
    await page.route('**/planning/training-capacity**', route =>
      route.fulfill({ json: capacity(0, 20) }));
    const drawer = await openGroupDrawer(page);

    // Training, then its SSA intervention, then the cluster, the date and the schools.
    const tops = await drawer.evaluate(element =>
      ['#training_activity', '[data-training-ssa-intervention]', '#cluster-picker', '[name=scheduled_date]', 'input[name=invited_school_ids]']
        .map(selector => element.querySelector(selector).getBoundingClientRect().top));
    expect([...tops].sort((a, b) => a - b)).toEqual(tops);

    await chooseTraining(page, drawer, 'SSA Training');
    const intervention = drawer.locator('[data-training-ssa-intervention] [data-linked-intervention]');
    await expect(intervention).toHaveValue('Leadership');
    await expect(intervention).not.toBeEditable();
    // Nothing is posted for it: the server reads the catalogue, so a request
    // cannot name another, and there is no list to choose another from.
    await expect(drawer.locator('[name=focus_intervention]')).toHaveCount(0);
  });

  test('at 18 of 20 only two more schools can be ticked', async ({ page }) => {
    await signIn(page, 'cceo@edify.org', 'edify', { acceptRequiredAgreements: false });
    await page.route('**/planning/training-capacity**', route =>
      route.fulfill({ json: capacity(18, 20) }));
    const drawer = await openGroupDrawer(page);
    await chooseTraining(page, drawer, 'Leadership');

    const all = boxes(drawer);
    const total = await all.count();
    test.skip(total < 4, 'the first cluster needs four schools to show the ceiling');

    // Start from none ticked, whatever the drawer pre-ticked.
    const toggle = drawer.getByRole('button', { name: /^(Select all|Clear all)$/ });
    if (await drawer.locator('input[name=invited_school_ids]:checked').count()) {
      if ((await toggle.innerText()).trim() !== 'Clear all') await toggle.click();
      await toggle.click();
    }
    await expect(drawer.locator('input[name=invited_school_ids]:checked')).toHaveCount(0);
    const counter = drawer.locator('[data-training-ceiling-count]');
    await expect(counter).toHaveText('18 / 20');

    await all.nth(0).check();
    await expect(counter).toHaveText('19 / 20');
    await expect(drawer.locator('input[name=invited_school_ids]:disabled')).toHaveCount(0);

    await all.nth(1).check();
    await expect(counter).toHaveText('20 / 20');
    // The ceiling is reached: every other school is greyed and cannot be ticked.
    await expect(drawer.locator('input[name=invited_school_ids]:disabled')).toHaveCount(total - 2);
    await expect(drawer.locator('[data-training-ceiling-reached]')).toBeVisible();
    await expect(drawer.locator('[data-training-ceiling-reached]')).toContainText('cannot add any more schools');
    await expect(all.nth(2)).toBeDisabled();
    await all.nth(2).evaluate(element => element.click());
    await expect(all.nth(2)).not.toBeChecked();
    await expect(counter).toHaveText('20 / 20');

    // Select all ticks no more than fit.
    await toggle.click();
    await toggle.click();
    await expect(drawer.locator('input[name=invited_school_ids]:checked')).toHaveCount(2);

    // Removing a school gives its place back.
    await drawer.locator('input[name=invited_school_ids]:checked').first().uncheck();
    await expect(counter).toHaveText('19 / 20');
    await expect(drawer.locator('input[name=invited_school_ids]:disabled')).toHaveCount(0);
  });

  test('with the ceiling already reached no school can be ticked', async ({ page }) => {
    await signIn(page, 'cceo@edify.org', 'edify', { acceptRequiredAgreements: false });
    await page.route('**/planning/training-capacity**', route =>
      route.fulfill({ json: capacity(20, 20) }));
    const drawer = await openGroupDrawer(page);
    await chooseTraining(page, drawer, 'Leadership');

    const total = await boxes(drawer).count();
    await expect(drawer.locator('input[name=invited_school_ids]:checked')).toHaveCount(0);
    await expect(drawer.locator('input[name=invited_school_ids]:disabled')).toHaveCount(total);
    await expect(drawer.locator('[data-training-ceiling-count]')).toHaveText('20 / 20');
    await expect(drawer.locator('[data-training-ceiling-reached]')).toContainText('cannot add any more schools');
  });

  test('a school already scheduled for the training takes no place', async ({ page }) => {
    // A ceiling counts schools (owner, 2026-10-08): the capacity answer names
    // the ones already scheduled, and such a school can still be ticked at a
    // full ceiling, taking no place, while every other school is held.
    await signIn(page, 'cceo@edify.org', 'edify', { acceptRequiredAgreements: false });
    const drawer = await openGroupDrawer(page);
    const counted = await boxes(drawer).first().getAttribute('value');
    await page.route('**/planning/training-capacity**', route =>
      route.fulfill({ json: { ...capacity(20, 20), schoolIds: [counted] } }));
    await chooseTraining(page, drawer, 'Leadership');

    const total = await boxes(drawer).count();
    const first = boxes(drawer).first();
    await expect(first).toBeEnabled();
    await expect(drawer.locator('input[name=invited_school_ids]:disabled')).toHaveCount(total - 1);
    await first.check();
    await expect(first).toBeChecked();
    await expect(drawer.locator('input[name=invited_school_ids]:checked')).toHaveCount(1);
    await expect(drawer.locator('input[name=invited_school_ids]:disabled')).toHaveCount(total - 1);
    await expect(drawer.locator('[data-training-ceiling-count]')).toHaveText('20 / 20');
  });

  test('a cluster meeting asks for a training only when it is one', async ({ page }) => {
    await signIn(page, 'cceo@edify.org', 'edify', { acceptRequiredAgreements: false });
    await page.route('**/planning/training-capacity**', route =>
      route.fulfill({ json: capacity(20, 20) }));
    await page.goto('/clusters');
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: 'Schedule Cluster Meeting', exact: true }).click();
    const drawer = page.locator('.drawer-surface.active');
    await expect(drawer).toBeVisible();

    const kind = drawer.locator('#meeting_kind');
    await expect(kind.locator('option')).toHaveText(['Training', 'Only Meeting', 'Cluster Leaders Meeting']);
    await expect(kind).toHaveValue('only_meeting');
    await expect(drawer.locator('#meeting_training_course')).toHaveCount(0);
    const total = await boxes(drawer).count();

    await kind.selectOption('cluster_leaders');
    await expect(drawer.locator('#meeting_training_course')).toHaveCount(0);
    await expect(drawer.locator('input[name=invited_school_ids]:disabled')).toHaveCount(0);

    // A Training meeting names its training and is held to its ceiling.
    await kind.selectOption('training');
    await expect(drawer.locator('#meeting_training_course')).toBeVisible();
    const answered = page.waitForResponse(response => response.url().includes('/planning/training-capacity'));
    await drawer.locator('#meeting_training_course').selectOption({ label: 'Leadership' });
    await answered;
    await expect(drawer.locator('[data-training-ssa-intervention] [data-linked-intervention]')).toHaveValue('Leadership');
    await expect(drawer.locator('input[name=invited_school_ids]:disabled')).toHaveCount(total);

    // Back to a meeting only: nothing is held, and no training is asked for.
    await kind.selectOption('only_meeting');
    await expect(drawer.locator('#meeting_training_course')).toHaveCount(0);
    await expect(drawer.locator('input[name=invited_school_ids]:disabled')).toHaveCount(0);
  });
});
