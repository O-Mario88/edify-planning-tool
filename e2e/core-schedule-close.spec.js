const { test, expect } = require('@playwright/test');
const { signIn } = require('./helpers/auth');

test('core scheduling closes after success and preserves validation errors', async ({ page }) => {
  await signIn(page, 'cceo@edify.org', 'edify', { acceptRequiredAgreements: false });
  await page.goto('/core-schools');
  // Training is an entry in the row's one Actions menu (owner, 2026-09-26).
  const training = '[role="menuitem"][hx-get^="/core-schools/schedule-training?"]';
  const row = page.locator('.core-school-row').filter({ has: page.locator(training) }).first();
  await row.locator('.row-menu__trigger').click();
  await row.locator(training).click();
  const schoolId = await page.locator('#schedule-training-drawer-root [name="school_id"]').inputValue();

  // Exercise the actual HTMX response contract without creating activities.
  for (const kind of ['training', 'visit']) {
    if (kind === 'visit') {
      await page.evaluate(id => htmx.ajax('GET', `/core-schools/schedule-visit?school_id=${encodeURIComponent(id)}`, {
        target: '#drawer-container', swap: 'innerHTML',
      }), schoolId);
    }
    const drawer = page.locator(`#schedule-${kind}-drawer-root`);
    await expect(drawer).toBeVisible();
    let invalid = true;
    await page.route(`**/core-schools/schedule-${kind}/action`, route => route.fulfill({
      status: invalid ? 400 : 200,
      headers: invalid ? {} : { 'HX-Trigger': JSON.stringify({ 'close-drawer': true, 'planning-saved': true }) },
      contentType: 'text/html',
      body: invalid ? '<p>Choose a valid date</p>' : '',
    }));
    const form = drawer.locator('form[hx-post]');
    await form.evaluate(el => { el.noValidate = true; htmx.trigger(el, 'submit'); });
    await expect(drawer.getByText('Choose a valid date')).toBeVisible();
    invalid = false;
    await form.evaluate(el => htmx.trigger(el, 'submit'));
    await expect(drawer).toHaveCount(0);
  }
});
