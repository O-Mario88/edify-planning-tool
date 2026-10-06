/* Candidate rewrites of the rules that still widen a restyle, tried in the
 * live page: each named step replaces matching rules' selectors in place
 * (same declarations, same position), then one element is inserted and what
 * it restyles is counted and explained (the shared :has() invalidation set).
 * Steps are cumulative. Audit tooling.
 *   EMAIL=cceo1@edify.org PATHS=/my-plan MOBILE=1 | VIEWPORT=1100x800  STEPS=A,B,C,E,D  A_VARIANT=1|2 */
const { chromium } = require('@playwright/test');
const B = process.env.BASE || 'http://127.0.0.1:8376';
const STEPS = (process.env.STEPS || 'A,B,C,E,D').split(',');
function apply(step, variant) {
  const SUBMIT = '[data-edify-has-submit]';
  const edits = {
    // The last div or nav of a block under main that holds an h1: asked of that last child and of its earlier siblings.
    A: (sel) => { const from = 'main > div > :where(header, div):has(h1) > :where(div, nav):last-child'; if (sel.trim() !== from) return null;
      return variant === '2' ? 'main > div > :where(header, div) > :where(div, nav):last-child:where(main > div > :where(header, div) > *):is(:has(h1), :is(h1, :has(h1)) ~ *)' : 'main > div > :where(header, div) > :where(div, nav):last-child:is(:has(h1), :is(h1, :has(h1)) ~ *)'; },
    // Four or more children: the first child is at least fourth from the end.
    B: (sel) => (sel.includes('.school-record-row__actions:has(> :nth-child(4)) > * svg') ? sel.replace('.school-record-row__actions:has(> :nth-child(4)) > * svg', '.school-record-row__actions > :where(:first-child:nth-last-child(n+4), :first-child:nth-last-child(n+4) ~ *):is(*, ._) svg') : null),
    // The search box says it has a submit button (the template writes it).
    C: (sel) => (/(search|\.edify-topbar__search(\.is-open)?):has\(\.edify-search-submit\) (input\[type="search"\]|form)/.test(sel) ? sel.replace(':has(.edify-search-submit)', SUBMIT) : null),
    // Exactly two children: the title is the first of two or the second of two.
    E: (sel) => { const from = '.edify-head-row--action.edify-head-row--action:has(> :nth-child(2):last-child) > .edify-head-row__title.edify-head-row__title'; return sel.includes(from) ? sel.replace(from, '.edify-head-row--action.edify-head-row--action > .edify-head-row__title.edify-head-row__title:is(:first-child:nth-last-child(2), :nth-child(2):last-child)') : null; },
    // A caption followed by a paragraph or heading somewhere among the surface's children: asked of the caption that is styled.
    D: (sel) => { let out = sel; for (const box of ['.rounded-surface', '.rounded-control']) { const from = `${box}:has(> .edify-text-caption + :is(p, h3, h4)) > .edify-text-caption.uppercase`; out = out.split(from).join(`${box} > .edify-text-caption.uppercase:is(:has(+ :is(p, h3, h4)), :has(~ .edify-text-caption + :is(p, h3, h4)), .edify-text-caption:has(+ :is(p, h3, h4)) ~ *)`); } return out === sel ? null : out; },
  };
  if (step === 'C') for (const search of document.querySelectorAll('search')) search.toggleAttribute('data-edify-has-submit', Boolean(search.querySelector('.edify-search-submit')));
  const edit = edits[step]; let changed = 0; const mismatched = [];
  const visit = (rules, parent) => { for (let i = rules.length - 1; i >= 0; i--) { const rule = rules[i]; if (rule.selectorText === undefined) { if (rule.cssRules) visit(rule.cssRules, rule); continue; }
    if (rule.cssRules && rule.cssRules.length) visit(rule.cssRules, rule);
    const next = edit(rule.selectorText); if (!next) continue;
    // The same elements, on this page at least (the proof is elsewhere).
    let before = null; let after = null; try { before = Array.from(document.querySelectorAll(rule.selectorText)); after = Array.from(document.querySelectorAll(next)); } catch (error) { mismatched.push('could not query: ' + String(error).slice(0, 80)); }
    if (before && (before.length !== after.length || before.some((el, n) => el !== after[n]))) mismatched.push(`${before.length} -> ${after.length}: ${rule.selectorText.slice(0, 90)}`);
    const body = rule.cssText.slice(rule.cssText.indexOf('{')); parent.deleteRule(i); parent.insertRule(next + ' ' + body, i); changed += 1; } };
  for (const sheet of document.styleSheets) { try { visit(sheet.cssRules, sheet); } catch (error) { /* another origin */ } }
  return { changed, mismatched };
}
function probe(label) {
  const flush = () => { getComputedStyle(document.body).color; void document.body.offsetWidth; };
  const host = Array.from(document.querySelectorAll('main table tbody td')).pop() || document.querySelector('main');
  flush(); performance.mark(label + ':start'); const span = document.createElement('span'); span.className = 'audit-probe-node'; host.appendChild(span); flush(); performance.mark(label + ':end'); span.remove(); flush();
}
(async () => { const browser = await chromium.launch(); const MOBILE = process.env.MOBILE === '1'; const VP = process.env.VIEWPORT ? process.env.VIEWPORT.split('x').map(Number) : MOBILE ? [390, 844] : [1440, 900];
  const page = await (await browser.newContext({ viewport: { width: VP[0], height: VP[1] }, isMobile: MOBILE, hasTouch: MOBILE, serviceWorkers: 'block' })).newPage();
  await page.goto(B + '/login'); await page.fill('input[name=email]', process.env.EMAIL); await page.fill('input[name=password]', 'edify'); await Promise.all([page.waitForNavigation(), page.press('input[name=password]', 'Enter')]);
  for (const pathname of process.env.PATHS.split(',')) { await page.goto(B + pathname, { waitUntil: 'load', timeout: 180000 }); await page.waitForTimeout(4000);
    const total = await page.evaluate(() => document.getElementsByTagName('*').length); const notes = {};
    await browser.startTracing(page, { categories: ['devtools.timeline', 'blink.user_timing', 'disabled-by-default-devtools.timeline.invalidationTracking'] });
    await page.evaluate(probe, 'as built');
    for (const step of STEPS) { notes[step] = await page.evaluate(`(${apply.toString()})(${JSON.stringify(step)}, ${JSON.stringify(process.env[step + '_VARIANT'] || '1')})`); await page.evaluate(probe, 'with ' + step); }
    const events = JSON.parse((await browser.stopTracing()).toString()).traceEvents;
    const marks = events.filter((e) => e.cat && e.cat.includes('blink.user_timing') && /:(start|end)$/.test(e.name)).sort((a, b) => a.ts - b.ts);
    console.log(`${process.env.EMAIL.split('@')[0]} ${pathname} ${VP.join('x')}${MOBILE ? ' phone' : ''}: ${total} elements`);
    for (let i = 0; i < marks.length; i++) { const m = marks[i]; if (!m.name.endsWith(':start')) continue; const label = m.name.slice(0, -6); const end = marks.slice(i + 1).find((x) => x.name === label + ':end'); if (!end) continue;
      const within = events.filter((e) => e.ts >= m.ts && e.ts <= end.ts); const styles = within.filter((e) => e.name === 'UpdateLayoutTree' && e.ph === 'X'); const n = styles.reduce((sum, e) => sum + ((e.args && e.args.elementCount) || 0), 0); const ms = styles.reduce((sum, e) => sum + (e.dur || 0), 0) / 1000;
      const sets = {}; for (const e of within) { if (e.name !== 'StyleInvalidatorInvalidationTracking' || !e.args || !e.args.data) continue; for (const set of e.args.data.invalidationList || []) sets[set.id] = set; }
      const broad = Object.values(sets).filter((set) => set.tagNames || set.attributes || set.classes).map((set) => `tags [${(set.tagNames || []).join(' ')}] attributes [${(set.attributes || []).join(' ')}] ${(set.classes || []).length} classes`).join(' | ');
      if (process.env.ANCHORS && label === 'with ' + STEPS[STEPS.length - 1]) { const who = {}; for (const e of within) { if (e.name === 'ScheduleStyleInvalidationTracking' && e.args && e.args.data) { const k = 'scheduled (' + (e.args.data.changedPseudo || e.args.data.changedClass || e.args.data.changedAttribute || '?') + ') on ' + e.args.data.nodeName; who[k] = (who[k] || 0) + 1; } if (e.name === 'StyleRecalcInvalidationTracking' && e.args && e.args.data) { const k = 'restyled: ' + e.args.data.reason + ' <' + e.args.data.nodeName + '>'; who[k] = (who[k] || 0) + 1; } } for (const [k, n] of Object.entries(who).sort((x, y) => y[1] - x[1]).slice(0, Number(process.env.ANCHORS))) console.log('          ' + String(n).padStart(3) + ' ' + k.slice(0, 190)); }
      const step = label.replace('with ', ''); const note = notes[step]; console.log(`   ${String(n).padStart(5)} restyled in ${ms.toFixed(1)} ms  ${label}${note ? ` (${note.changed} rules${note.mismatched.length ? '; MISMATCH ' + note.mismatched.join(' ; ') : ''})` : ''}  ${broad}`); } }
  await browser.close(); })().catch((e) => { console.error(e); process.exit(1); });
