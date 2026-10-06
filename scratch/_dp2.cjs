/* Each date field (wrapper, native input, visible input) under the original and the changed date-picker: rows closed, then opened. */
const { chromium } = require('@playwright/test'); const fs = require('node:fs');
const B = 'http://127.0.0.1:8376';
function read() {
  const sig = (e) => Array.from(e.attributes).map((a) => a.name + '=' + a.value).sort().join(' | ') + ' @' + Math.round(e.getBoundingClientRect().width);
  return Array.from(document.querySelectorAll('.edify-datepick__native')).map((native) => {
    const wrapper = native.closest('.edify-datepick') || native.parentElement;
    const field = wrapper.querySelector('.edify-datepick__field') || wrapper.parentElement.querySelector('.edify-datepick__field');
    return [sig(wrapper), sig(native), field ? sig(field) : 'no field'];
  });
}
(async () => {
  const browser = await chromium.launch(); const out = {};
  for (const world of ['final', 'original']) {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, serviceWorkers: 'block' });
    if (world === 'original') await context.route((u) => u.pathname.includes('/static/js/date-picker'), (route) => route.fulfill({ status: 200, contentType: 'application/javascript', body: fs.readFileSync(process.env.DP) }));
    const page = await context.newPage();
    await page.goto(B + '/login'); await page.fill('input[name=email]', 'cd@edify.org'); await page.fill('input[name=password]', 'edify');
    await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
    await page.goto(B + '/strategic-priorities', { waitUntil: 'load' }); await page.waitForTimeout(4000);
    const closed = await page.evaluate(read);
    await page.evaluate(() => { document.querySelectorAll('main details').forEach((d) => { d.open = true; }); });
    await page.waitForTimeout(1500);
    out[world] = { closed, open: await page.evaluate(read) };
    await context.close();
  }
  for (const state of ['closed', 'open']) {
    const a = out.final[state]; const b = out.original[state]; let differing = 0; const kinds = {};
    a.forEach((trio, i) => trio.forEach((sig, k) => {
      if (sig === b[i][k]) return;
      differing += 1;
      const x = new Set(sig.split(' | ')); const y = new Set(b[i][k].split(' | '));
      const key = ['wrapper', 'native', 'field'][k] + ': final only [' + [...x].filter((v) => !y.has(v)).join('; ').slice(0, 110) + '] original only [' + [...y].filter((v) => !x.has(v)).join('; ').slice(0, 110) + ']';
      kinds[key] = (kinds[key] || 0) + 1;
    }));
    console.log(`${a.length} date fields, rows ${state}: ${differing} of ${a.length * 3} element signatures differ`);
    for (const [k, n] of Object.entries(kinds).slice(0, 8)) console.log(`   ${n}x ${k}`);
  }
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
