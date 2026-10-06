/* Every date field on every audited page, under the original and the changed
 * date-picker: its drawn width as the page opens, and again once every closed
 * <details> on the page has been opened. Audit tooling. */
const { chromium } = require('@playwright/test'); const fs = require('node:fs');
const B = 'http://127.0.0.1:8376'; const PAGES = JSON.parse(fs.readFileSync(process.env.PAGES_FILE, 'utf8'));
const MOBILE = process.env.MOBILE === '1';
function read() {
  return Array.from(document.querySelectorAll('.edify-datepick__native')).map((native) => {
    const wrapper = native.closest('.edify-datepick') || native.parentElement;
    const field = wrapper.querySelector('.edify-datepick__field') || wrapper.parentElement.querySelector('.edify-datepick__field') || wrapper;
    const drawn = field.checkVisibility ? field.checkVisibility({ contentVisibilityAuto: true }) : true;
    const box = field.getBoundingClientRect();
    return { name: native.name || native.id || '', drawn, width: drawn ? Math.round(box.width * 10) / 10 : null, height: drawn ? Math.round(box.height) : null, size: field.getAttribute('size') };
  });
}
(async () => {
  const browser = await chromium.launch(); let pages = 0, withFields = 0, fields = 0, widthDiffs = 0, sizeDiffs = 0;
  for (const [account, paths] of Object.entries(PAGES)) {
    const worlds = {};
    for (const world of ['final', 'original']) {
      const context = await browser.newContext({ viewport: MOBILE ? { width: 390, height: 844 } : { width: 1440, height: 900 }, isMobile: MOBILE, hasTouch: MOBILE, serviceWorkers: 'block' });
      if (world === 'original') await context.route((u) => u.pathname.includes('/static/js/date-picker'), (route) => route.fulfill({ status: 200, contentType: 'application/javascript', body: fs.readFileSync(process.env.DP) }));
      const page = await context.newPage();
      await page.goto(B + '/login'); await page.fill('input[name=email]', account); await page.fill('input[name=password]', 'edify');
      await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
      worlds[world] = {};
      for (const p of paths) {
        await page.goto(B + p, { waitUntil: 'load', timeout: 240000 }); await page.waitForTimeout(2500);
        const asOpened = await page.evaluate(read);
        await page.evaluate(() => { document.querySelectorAll('details').forEach((d) => { if (!d.classList.contains('edify-rail-more')) d.open = true; }); });
        await page.waitForTimeout(1200);
        worlds[world][p] = { asOpened, revealed: await page.evaluate(read) };
      }
      await context.close();
    }
    for (const p of paths) {
      pages += 1; const a = worlds.final[p]; const b = worlds.original[p];
      if (!a.revealed.length && !b.revealed.length) continue;
      withFields += 1; fields += a.revealed.length;
      for (const state of ['asOpened', 'revealed']) {
        if (a[state].length !== b[state].length) { console.log(`COUNT ${account.split('@')[0]} ${p} ${state}: ${a[state].length} vs ${b[state].length} fields`); widthDiffs += 1; continue; }
        const wide = a[state].filter((f, i) => f.drawn !== b[state][i].drawn || f.width !== b[state][i].width || f.height !== b[state][i].height);
        const sized = a[state].filter((f, i) => f.size !== b[state][i].size);
        if (state === 'revealed') sizeDiffs += sized.length;
        if (wide.length) { widthDiffs += wide.length; const i = a[state].indexOf(wide[0]); console.log(`WIDTH ${account.split('@')[0].padEnd(12)} ${p.padEnd(28)} ${state}: ${wide.length} of ${a[state].length} fields drawn differently, e.g. ${JSON.stringify(a[state][i])} vs original ${JSON.stringify(b[state][i])}`); }
      }
    }
  }
  console.log(`${pages} pages${MOBILE ? ' (phone)' : ''}, ${withFields} with date fields, ${fields} fields: ${widthDiffs} drawn at a different width or height; ${sizeDiffs} whose size attribute differs once revealed`);
  await browser.close(); process.exit(widthDiffs ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
