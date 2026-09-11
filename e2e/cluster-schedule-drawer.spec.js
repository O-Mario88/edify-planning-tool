const { test, expect } = require('@playwright/test');
const { signIn } = require('./helpers/auth');

test.use({ video: 'off', trace: 'off', serviceWorkers: 'block' });

test.describe('Cluster Schedule Drawers stay open and contain cost preview', () => {
  test('Cluster card Schedule button opens planner drawer and stays open', async ({ page }) => {
    test.setTimeout(60000);
    await signIn(page, 'cceo@edify.org', 'edify', { acceptRequiredAgreements: false });
    await page.goto('/clusters');
    await page.waitForLoadState('networkidle');

    // Find the first cluster card schedule button
    const scheduleBtn = page.locator('.school-record-action--schedule').first();
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
    const form = surface.locator('#action-planner-form');
    await expect(form).toBeVisible();

    // Verify the cost preview container is inside the drawer and visible
    const costPreview = surface.locator('#planner-cost-preview-container');
    await expect(costPreview).toBeVisible();

    // Verify that the cost preview did NOT replace #drawer-container (it must be inside the drawer surface)
    const previewInsideDrawer = await surface.locator('#planner-cost-preview-container').count();
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

    const groupTrainingBtn = page.getByRole('button', { name: /Schedule Group Training/i });
    await expect(groupTrainingBtn).toBeVisible();
    await groupTrainingBtn.click();

    const surface = page.locator('.drawer-surface.active');
    await expect(surface).toBeVisible({ timeout: 5000 });

    // Wait past the 100ms trigger
    await page.waitForTimeout(1500);
    await expect(surface).toBeVisible();

    const form = surface.locator('#action-planner-form');
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

    const meetingBtn = page.getByRole('button', { name: /Schedule Cluster Meeting/i });
    await expect(meetingBtn).toBeVisible();
    await meetingBtn.click();

    const surface = page.locator('.drawer-surface.active');
    await expect(surface).toBeVisible({ timeout: 5000 });

    // Wait past the 100ms trigger
    await page.waitForTimeout(1500);
    await expect(surface).toBeVisible();

    const form = surface.locator('#action-planner-form');
    await expect(form).toBeVisible();

    const closeBtn = surface.locator('.drawer-close-btn');
    await closeBtn.click();
    await expect(surface).toHaveCount(0);
  });
});
