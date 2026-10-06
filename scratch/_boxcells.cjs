/* Which pages have a row whose first cell holds a box itself, once the page has settled? Audit tooling. */
const { chromium } = require('@playwright/test');
const B = 'http://127.0.0.1:8376'; const PAGES = JSON.parse(process.argv[2]);
(async () => { const browser = await chromium.launch();
  for (const [account, paths] of Object.entries(PAGES)) { const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: 'block' }); const page = await context.newPage();
    await page.goto(B + '/login'); await page.fill('input[name=email]', account); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
    for (const p of paths) { const r = await page.goto(B + p, { waitUntil: 'load', timeout: 120000 }); await page.waitForTimeout(2500);
      const found = await page.evaluate(() => { const BOX = ':is(input[type="checkbox"], input[type="radio"], .edify-table-choice)'; const cells = [...document.querySelectorAll('table > :is(thead, tbody, tfoot) > tr > *')];
        const truth = cells.filter((c) => c.matches(':first-child:has(> ' + BOX + ')')); const marked = cells.filter((c) => c.hasAttribute('data-edify-box-cell'));
        const pinned = [...document.querySelectorAll('.edify-table-scroll-region:is([data-scroll-state="start"], [data-scroll-state="middle"], [data-scroll-state="end"]) > table > tbody > tr > [data-edify-box-cell]:first-child + *')].length;
        return { cells: cells.length, truth: truth.length, marked: marked.length, agree: truth.length === marked.length && truth.every((c) => c.hasAttribute('data-edify-box-cell')), pinnedAfterBox: pinned, states: [...new Set([...document.querySelectorAll('.edify-table-scroll-region')].map((r) => r.dataset.scrollState || '-'))].join(',') }; });
      console.log(account.split('@')[0].padEnd(12), p.padEnd(28), r.status(), JSON.stringify(found)); }
    await context.close(); }
  await browser.close(); })().catch((e) => { console.error(e); process.exit(1); });
