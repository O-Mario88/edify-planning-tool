const fs = require('node:fs'); const { chromium } = require('@playwright/test');
const B = 'http://127.0.0.1:8376'; const OV = process.env.PATCH;
(async () => { const b = await chromium.launch(); const ctx = await b.newContext({viewport:{width:1440,height:900}});
if (OV) await ctx.route((u) => u.pathname.includes('/static/') && u.pathname.includes('date-picker'), (r) => r.fulfill({ status: 200, contentType: 'application/javascript', body: fs.readFileSync(OV) }));
const p = await ctx.newPage(); const errs = []; p.on('pageerror', (e) => errs.push(String(e).slice(0, 200))); p.on('console', (m) => { if (m.type() === 'error') errs.push(m.text().slice(0, 200)); });
await p.goto(B + '/login'); await p.fill('input[name=email]','cd@edify.org'); await p.fill('input[name=password]','edify'); await Promise.all([p.waitForNavigation(), p.press('input[name=password]','Enter')]);
await p.goto(B + '/strategic-priorities',{waitUntil:'load',timeout:180000}); await p.waitForTimeout(2500);
const info = await p.evaluate(() => { const e = document.querySelector('input[data-edify-datepick-field]'); const chain = []; for (let n = e; n && n !== document.body; n = n.parentElement) { const s = getComputedStyle(n); chain.push(n.tagName + (n.id ? '#' + n.id : '') + '.' + String(n.className).split(' ').slice(0, 2).join('.') + ' d=' + s.display + ' cv=' + s.contentVisibility + (n.hasAttribute('open') ? ' [open]' : '') + (n.hasAttribute('x-show') ? ' [x-show]' : '') + (n.hasAttribute('hidden') ? ' [hidden]' : '')); } return { chain: chain.slice(0, 14), fittedAtLoad: Array.from(document.querySelectorAll('input[data-edify-datepick-field]')).filter((d) => d.style.width || d.size !== 13).length }; });
console.log(JSON.stringify(info, null, 1));
// reveal every field the way a reader would: scroll its row into view and open closed disclosures/dialogs around it
const state = await p.evaluate(async () => { const out = {}; const fields = Array.from(document.querySelectorAll('input[data-edify-datepick-field]'));
  const frame = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  for (const d of fields) { const chain = []; for (let n = d.parentElement; n; n = n.parentElement) if (n.tagName === 'DETAILS') chain.unshift(n);
    for (const n of chain) { n.open = true; await frame(); }
    d.scrollIntoView({ block: 'center' }); await frame(); await frame();
    const native = d.closest('.edify-datepick').previousElementSibling; const r = d.getBoundingClientRect();
    out[native.name + '|' + (native.id || '') + '|' + Object.keys(out).length] = [d.size, d.style.width, Math.round(r.width * 10) / 10, Math.round(r.height * 10) / 10, d.checkVisibility(), d.value]; }
  return out; });
fs.writeFileSync(process.env.OUT, JSON.stringify(state, null, 1)); const v = Object.values(state);
console.log('fields', v.length, 'visible when revealed', v.filter((x) => x[4]).length, 'sample', JSON.stringify(v.slice(0, 3)), 'errors', errs.length, errs.slice(0, 3));
await b.close(); })().catch(e => { console.error(e); process.exit(1); });
