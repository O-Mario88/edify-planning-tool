/*
 * Clicking Actions on a plan row opens a menu you can read and choose from.
 *
 * The regression this pins: micro-ux.js marks every button inside a table with
 * `edify-table-action` / `edify-cell-control` so the row line stays 32px, and
 * those markers reached the buttons inside the row-actions dropdown. The menu
 * items took `display: inline-flex` and a 24px cell-control height, and with
 * the cell's inherited `white-space: nowrap` all of them laid out on one line
 * — a 527x34 strip showing the first item and hiding the rest off its own
 * right edge. The menu opened; it just did not look or behave like a menu.
 *
 * Asserted against the rendered geometry rather than the class list, because
 * the class list is the mechanism and the geometry is the promise: items
 * stacked, each one inside the menu's box, no two sharing a line.
 */
const { test, expect } = require('@playwright/test');
const { signIn } = require('./helpers/auth');
const { ensureActionableRow } = require('./helpers/plans');

test.describe('row actions menu', () => {
  test('opens as a stacked list of actions', async ({ page }) => {
    test.setTimeout(120_000);
    await signIn(page, 'cceo@edify.org', 'edify', { acceptRequiredAgreements: false });

    // My Plan lists upcoming work, and the seed's rows are all completed
    // (a completed row offers its record, not the menu), so the helper books
    // one visit ahead of today for this officer when none is there yet.
    await ensureActionableRow(page);
    const trigger = page.locator('.row-menu__trigger').first();
    await expect(trigger).toBeVisible();

    await trigger.scrollIntoViewIfNeeded();
    await trigger.click();

    const menu = page.locator('.row-menu__list').first();
    await expect(menu).toBeVisible();
    await expect(trigger).toHaveAttribute('aria-expanded', 'true');

    const items = menu.locator('.row-menu__item');
    const count = await items.count();
    expect(count, 'a row offers more than one next step').toBeGreaterThan(1);

    const menuBox = await menu.boundingBox();
    let previousBottom = null;
    for (let index = 0; index < count; index += 1) {
      const box = await items.nth(index).boundingBox();
      expect(box, `item ${index} has a box`).not.toBeNull();

      // Inside the menu, not spilling past its right edge.
      expect(box.x + box.width).toBeLessThanOrEqual(menuBox.x + menuBox.width + 1);
      // Full-width, so the whole row is the target and the label has room.
      expect(box.width).toBeGreaterThan(menuBox.width - 20);
      // Stacked: each item starts at or below the previous one's bottom.
      if (previousBottom !== null) expect(box.y).toBeGreaterThanOrEqual(previousBottom - 1);
      previousBottom = box.y + box.height;
    }

    // The menu is as tall as the items it holds, not one flattened line.
    expect(menuBox.height).toBeGreaterThan(previousBottom - menuBox.y - 1);

    // It drops DOWN from the button (owner, 2026-09-27), in the top layer,
    // where no row, card or workspace container can move or clip it.
    const triggerBox = await trigger.boundingBox();
    expect(menuBox.y).toBeGreaterThanOrEqual(triggerBox.y + triggerBox.height);
    expect(await menu.evaluate((el) => el.matches(':popover-open'))).toBe(true);

    // And it still closes.
    await page.keyboard.press('Escape');
    await expect(menu).toBeHidden();
  });

  test('drops down from a button at the foot of the screen', async ({ page }) => {
    test.setTimeout(120_000);
    await signIn(page, 'cceo@edify.org', 'edify', { acceptRequiredAgreements: false });
    await ensureActionableRow(page);
    const trigger = page.locator('.row-menu__trigger').first();
    await expect(trigger).toBeVisible();

    // Scroll whatever holds the button until it sits just above the foot of
    // the window, where the old menu flipped up over the button.
    await trigger.evaluate((el) => {
      el.scrollIntoView({ block: 'end' });
      let box = el.parentElement;
      while (box && box.scrollHeight <= box.clientHeight) box = box.parentElement;
      if (box) box.scrollTop -= 8;
    });
    await trigger.click();

    const menu = page.locator('.row-menu__list:popover-open');
    await expect(menu).toBeVisible();
    const triggerBox = await trigger.boundingBox();
    const menuBox = await menu.boundingBox();
    const viewport = page.viewportSize();
    expect(menuBox.y, 'below the button, not over it').toBeGreaterThanOrEqual(triggerBox.y + triggerBox.height);
    expect(menuBox.y + menuBox.height, 'the whole menu on screen').toBeLessThanOrEqual(viewport.height);
    expect(menuBox.x).toBeGreaterThanOrEqual(0);
    expect(menuBox.x + menuBox.width).toBeLessThanOrEqual(viewport.width);
  });
});
