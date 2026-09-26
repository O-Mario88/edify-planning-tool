const { test, expect } = require('@playwright/test');
const { signIn } = require('./helpers/auth');

test.use({ video: 'off', trace: 'off', serviceWorkers: 'block' });

// Every cluster entry point opens the SAME drawer since 2026-09-17 — the
// Planning one, which the Clusters page's own buttons now target (owner: "use
// the same cluster meeting planning drawer ... everywhere there is cluster
// planning"). The contract this spec has always pinned is unchanged: the
// drawer opens, it does not flash away when the cost preview fires, and the
// preview lands INSIDE the drawer rather than replacing #drawer-container.
// Only the element names moved: #action-planner-form -> #cluster-planner-form,
// #planner-cost-preview-container -> #cluster-cost-preview.
//
// The preview assertion earns its keep: htmx inherits hx-target, so the new
// drawer's preview was briefly swapped into the form's error box instead of
// its own container.
test.describe('Cluster Schedule Drawers stay open and contain cost preview', () => {
  test('Cluster card Schedule button opens planner drawer and stays open', async ({ page }) => {
    test.setTimeout(60000);
    await signIn(page, 'cceo@edify.org', 'edify', { acceptRequiredAgreements: false });
    await page.goto('/clusters');
    await page.waitForLoadState('networkidle');

    // The first cluster card's Schedule, an entry in the card's one Actions
    // menu since 2026-09-26 (owner: "switch to Action button with options to
    // schedule and assign").
    const card = page.locator('.cluster-card:has(.row-menu__trigger)').first();
    await card.locator('.row-menu__trigger').click();
    const scheduleBtn = card.getByRole('menuitem', { name: /^Schedule Group Training for / });
    await expect(scheduleBtn).toBeVisible();
    await scheduleBtn.click();

    // Drawer should open and be active
    const surface = page.locator('.drawer-surface.active');
    await expect(surface).toBeVisible({ timeout: 5000 });

    // Wait well past the 100ms delay of the cost preview auto-trigger
    await page.waitForTimeout(1500);

    // Verify drawer is still active and visible (did not flash away)
    await expect(surface).toBeVisible();

    // Verify the action planner form is present inside the drawer
    const form = surface.locator('#cluster-planner-form');
    await expect(form).toBeVisible();

    // Verify the cost preview container is inside the drawer and visible
    const costPreview = surface.locator('#cluster-cost-preview');
    await expect(costPreview).toBeVisible();

    // Verify that the cost preview did NOT replace #drawer-container (it must be inside the drawer surface)
    const previewInsideDrawer = await surface.locator('#cluster-cost-preview').count();
    expect(previewInsideDrawer).toBe(1);

    // Close the drawer
    const closeBtn = surface.locator('.drawer-close-btn');
    await closeBtn.click();
    await expect(surface).toHaveCount(0);
  });

  test('Top-level Schedule Group Training button opens planner drawer and stays open', async ({ page }) => {
    test.setTimeout(60000);
    await signIn(page, 'cceo@edify.org', 'edify', { acceptRequiredAgreements: false });
    await page.goto('/clusters');
    await page.waitForLoadState('networkidle');

    const groupTrainingBtn = page.getByRole('button', { name: 'Schedule Group Training', exact: true });
    await expect(groupTrainingBtn).toBeVisible();
    await groupTrainingBtn.click();

    const surface = page.locator('.drawer-surface.active');
    await expect(surface).toBeVisible({ timeout: 5000 });

    // Wait past the 100ms trigger
    await page.waitForTimeout(1500);
    await expect(surface).toBeVisible();

    const form = surface.locator('#cluster-planner-form');
    await expect(form).toBeVisible();

    const closeBtn = surface.locator('.drawer-close-btn');
    await closeBtn.click();
    await expect(surface).toHaveCount(0);
  });

  test('Top-level Schedule Cluster Meeting button opens planner drawer and stays open', async ({ page }) => {
    test.setTimeout(60000);
    await signIn(page, 'cceo@edify.org', 'edify', { acceptRequiredAgreements: false });
    await page.goto('/clusters');
    await page.waitForLoadState('networkidle');

    const meetingBtn = page.getByRole('button', { name: 'Schedule Cluster Meeting', exact: true });
    await expect(meetingBtn).toBeVisible();
    await meetingBtn.click();

    const surface = page.locator('.drawer-surface.active');
    await expect(surface).toBeVisible({ timeout: 5000 });

    // Wait past the 100ms trigger
    await page.waitForTimeout(1500);
    await expect(surface).toBeVisible();

    const form = surface.locator('#cluster-planner-form');
    await expect(form).toBeVisible();

    const closeBtn = surface.locator('.drawer-close-btn');
    await closeBtn.click();
    await expect(surface).toHaveCount(0);
  });
});
