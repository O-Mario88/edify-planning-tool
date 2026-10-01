const { test, expect } = require('@playwright/test');
const { signIn } = require('./helpers/auth');

/* The wide-screen shell (owner, 2026-10-01). A page used to stop at 100rem and
 * centre itself in <main> while the sidebar stayed on the viewport's left edge
 * — on a 2560px monitor that left 375px of empty canvas between the navigation
 * and the page. Two rules replace that. The page is 144rem wide, so up to a
 * 2560px monitor it simply fills the screen beside the sidebar. Beyond that the
 * shell centres sidebar, top bar and page as one frame, once there is room for
 * a real margin either side. static/css/components.css, "Wide-screen frame";
 * static/css/platform.css, --edify-page-max-size. */

test.use({ video: 'off', trace: 'off', serviceWorkers: 'block' });

async function frame(page) {
  return page.evaluate(() => {
    const edges = element => {
      const box = element.getBoundingClientRect();
      return { left: Math.round(box.left), right: Math.round(box.right), width: Math.round(box.width) };
    };
    const main = document.querySelector('main#main-content');
    const canvas = Array.from(main.children).find(child => child.getBoundingClientRect().height > 0);
    const canvasBox = canvas.getBoundingClientRect();
    return {
      viewport: window.innerWidth,
      sidebar: edges(document.querySelector('aside.app-sidebar')),
      topbar: edges(document.querySelector('.edify-topbar')),
      main: edges(main),
      // The page's painted edge: its canvas box less the gutter it pads itself with.
      pageLeft: Math.round(canvasBox.left + parseFloat(getComputedStyle(canvas).paddingLeft)),
      overflow: document.documentElement.scrollWidth - window.innerWidth,
      shellBackground: getComputedStyle(document.querySelector('.edify-shell')).backgroundColor,
    };
  });
}

test('the page fills a wide monitor beside the sidebar, and an ultra-wide one frames it', async ({ page }) => {
  await signIn(page, 'pl1@edify.org', 'edify', { acceptRequiredAgreements: false });
  await page.goto('/schools');
  await expect(page.locator('main#main-content')).toBeVisible();

  // From a laptop to a 2560px monitor the shell is edge to edge and the page
  // starts one gutter from the sidebar: no dead band between them, no margin.
  for (const width of [1440, 1920, 2560]) {
    await page.setViewportSize({ width, height: 1000 });
    const shell = await frame(page);
    expect(shell.sidebar.left, `sidebar on the edge at ${width}`).toBe(0);
    expect(shell.topbar.right, `top bar reaches the edge at ${width}`).toBe(width);
    expect(shell.pageLeft - shell.sidebar.right, `page sits against the sidebar at ${width}`).toBeLessThanOrEqual(32);
    expect(shell.overflow, `no page overflow at ${width}`).toBeLessThanOrEqual(1);
  }

  for (const width of [3000, 3440]) {
    await page.setViewportSize({ width, height: 1200 });
    const shell = await frame(page);
    const leftMargin = shell.sidebar.left;
    const rightMargin = width - shell.topbar.right;
    expect(leftMargin, `a real left margin at ${width}`).toBeGreaterThanOrEqual(72);
    expect(Math.abs(leftMargin - rightMargin), `frame centred at ${width}`).toBeLessThanOrEqual(1);
    // The stage is exactly the page width (144rem), so the top bar's ends line
    // up with the page column rather than with the viewport.
    expect(shell.topbar.width, `stage is the page width at ${width}`).toBe(2304);
    expect(shell.topbar.left, `top bar starts where the sidebar ends at ${width}`).toBe(shell.sidebar.right);
    expect(shell.pageLeft - shell.sidebar.right, `page sits against the sidebar at ${width}`).toBeLessThanOrEqual(32);
    expect(shell.overflow, `no page overflow at ${width}`).toBeLessThanOrEqual(1);
    // The margins are their own surfaces; the shell keeps the page canvas.
    expect(shell.shellBackground).toBe('rgb(219, 228, 235)');
  }
});

test('the frame follows the sidebar when it collapses to its rail', async ({ page }) => {
  await page.addInitScript(() => {
    try { localStorage.setItem('edify-sidebar-collapsed', '1'); } catch (error) { /* storage blocked */ }
  });
  await signIn(page, 'pl1@edify.org', 'edify', { acceptRequiredAgreements: false });
  await page.setViewportSize({ width: 3440, height: 1200 });
  await page.goto('/schools');
  await expect(page.locator('aside.app-sidebar.app-sidebar--collapsed')).toBeVisible();

  // Alpine applies the collapsed class after load and the width eases to it.
  await expect.poll(async () => (await frame(page)).sidebar.width).toBe(72);
  const shell = await frame(page);
  expect(shell.topbar.width, 'the rail gives its width to the margins, not the page').toBe(2304);
  expect(Math.abs(shell.sidebar.left - (3440 - shell.topbar.right)), 'frame centred').toBeLessThanOrEqual(1);
  expect(shell.pageLeft - shell.sidebar.right, 'page sits against the rail').toBeLessThanOrEqual(32);
});
