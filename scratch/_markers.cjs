/* The five facts micro-ux.js keeps as attributes must say, at every frame,
 * what the :has() selectors they replaced would say. Checked on every audited
 * page from the moment the page has started up, once per animation frame for
 * a few seconds, and after the page has settled. Audit tooling.
 *   PAGES_FILE=pages.json VIEWPORT=390x844 MOBILE=1 */
const fs = require('node:fs'); const { chromium } = require('@playwright/test');
const B = process.env.BASE || 'http://127.0.0.1:8376'; const PAGES = JSON.parse(fs.readFileSync(process.env.PAGES_FILE, 'utf8'));
const MOBILE = process.env.MOBILE === '1'; const VP = (process.env.VIEWPORT || (MOBILE ? '390x844' : '1440x900')).split('x').map(Number);
const CHECK = `(() => {
  const BOX = ':is(input[type="checkbox"], input[type="radio"], .edify-table-choice)';
  const facts = [
    ['table', ':has(> tbody > tr > :first-child > ' + BOX + ', > tbody > tr > :first-child > label > :is(input[type="checkbox"], input[type="radio"]))', 'data-edify-select-column', false],
    ['.edify-head-row', ':has(> :is(p, div, ul, dl, form))', 'data-edify-head-run', true],
    ['[data-edify-tablist]', ':has(+ a.btn)', 'data-edify-beside-link', false],
    ['search, .edify-topbar__search', ':has(.edify-search-submit)', 'data-edify-has-submit', false],
    ['table > :is(thead, tbody, tfoot) > tr > *', ':first-child:has(> ' + BOX + ')', 'data-edify-box-cell', false],
  ];
  // The rules rewritten on 2026-10-05 (second pass): how many elements each styles on this page, whatever the width.
  const CAP = '.edify-text-caption.uppercase:is(:has(+ :is(p, h3, h4)), :has(~ .edify-text-caption + :is(p, h3, h4)), .edify-text-caption:has(+ :is(p, h3, h4)) ~ *)';
  window.__cover = () => ({
    'header last child': document.querySelectorAll('main > div > :where(header, div) > :where(div, nav):last-child:is(:has(h1), :is(h1, :has(h1)) ~ *)').length,
    'school row icons': document.querySelectorAll(':root main .school-record-row .school-record-row__actions > :where(:first-child:nth-last-child(n+4), :first-child:nth-last-child(n+4) ~ *) svg').length,
    'title beside one action': document.querySelectorAll('main .edify-head-row--action > .edify-head-row__title:is(:first-child:nth-last-child(2), :nth-child(2):last-child)').length,
    'kpi caption': document.querySelectorAll('main :is(.rounded-surface, .rounded-control) > ' + CAP).length,
    'search box field': document.querySelectorAll('search[data-edify-has-submit] input[type="search"], .edify-topbar__search[data-edify-has-submit] form').length,
  });
  window.__facts = { checks: 0, frames: 0, wrong: [], seen: { 'data-edify-select-column': 0, 'data-edify-head-run': 0, 'data-edify-beside-link': 0, 'data-edify-has-submit': 0, 'data-edify-box-cell': 0 }, anchors: 0 };
  const name = (e) => e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.classList.length ? '.' + Array.from(e.classList).slice(0, 3).join('.') : '');
  window.__checkFacts = (when) => { const f = window.__facts; f.frames++; let anchors = 0;
    for (const [anchor, has, attr, inverted] of facts) for (const el of document.querySelectorAll(anchor)) { anchors++; f.checks++; const truth = el.matches(has) !== inverted; const said = el.hasAttribute(attr); if (said) f.seen[attr]++; if (truth !== said && f.wrong.length < 12) f.wrong.push(when + ': ' + name(el) + ' ' + attr + ' is ' + said + ', the selector says ' + truth); }
    f.anchors = anchors; };
  document.addEventListener('DOMContentLoaded', () => { let n = 0; const tick = () => { window.__checkFacts('frame ' + n); if (++n < 240) requestAnimationFrame(tick); }; requestAnimationFrame(tick); });
})();`;
(async () => { const browser = await chromium.launch(); let bad = 0, pages = 0, checks = 0; const seen = {}; const cover = {};
  for (const [account, paths] of Object.entries(PAGES)) { const context = await browser.newContext({ viewport: { width: VP[0], height: VP[1] }, isMobile: MOBILE, hasTouch: MOBILE, serviceWorkers: 'block' });
    await context.addInitScript(CHECK); const page = await context.newPage();
    await page.goto(B + '/login'); await page.fill('input[name=email]', account); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
    for (const p of paths) { pages++; await page.goto(B + p, { waitUntil: 'load', timeout: 240000 }); await page.waitForTimeout(3500);
      const r = await page.evaluate(() => { window.__checkFacts('settled'); return { ...window.__facts, cover: window.__cover() }; }); for (const [k, v] of Object.entries(r.cover)) { cover[k] = cover[k] || { pages: 0, elements: 0 }; if (v) cover[k].pages++; cover[k].elements += v; }
      checks += r.checks; for (const [k, v] of Object.entries(r.seen)) seen[k] = (seen[k] || 0) + (v ? 1 : 0);
      if (r.wrong.length || /\/login/.test(page.url())) { bad++; console.log(`WRONG ${account.split('@')[0].padEnd(22)} ${p.padEnd(30)} ${r.wrong.slice(0, 3).join(' | ').slice(0, 300)}`); } }
    await context.close(); }
  console.log(`${pages} pages at ${VP.join('x')}${MOBILE ? ' (phone)' : ''}: ${pages - bad} agree at every frame, ${bad} disagree; ${checks} checks. Pages where a fact was true at some frame: ${JSON.stringify(seen)}`);
  console.log('   rewritten rules, pages where each styles something / elements styled: ' + Object.entries(cover).map(([k, v]) => `${k} ${v.pages}/${v.elements}`).join('; '));
  await browser.close(); process.exit(bad ? 1 : 0); })().catch((e) => { console.error(e); process.exit(2); });
