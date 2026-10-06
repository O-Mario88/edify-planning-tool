const { chromium } = require('@playwright/test');
const B = 'http://127.0.0.1:8376';
(async () => { const b = await chromium.launch();
for (const [email, paths] of [['cceo1@edify.org', ['/dashboard','/planning','/my-plan','/schools']], ['cd@edify.org', ['/dashboard','/analytics']]]) {
  const p = await (await b.newContext({viewport:{width:1440,height:900}})).newPage();
  await p.goto(B + '/login'); await p.fill('input[name=email]', email); await p.fill('input[name=password]','edify'); await Promise.all([p.waitForNavigation(), p.press('input[name=password]','Enter')]);
  for (const path of paths) {
    await p.coverage.startCSSCoverage({ resetOnNavigation: true }); await p.coverage.startJSCoverage({ resetOnNavigation: true, reportAnonymousScripts: false });
    await p.goto(B + path, { waitUntil: 'load', timeout: 180000 }); await p.waitForTimeout(2500);
    const css = await p.coverage.stopCSSCoverage(); const js = await p.coverage.stopJSCoverage();
    const used = (e) => e.ranges ? e.ranges.reduce((s, r) => s + r.end - r.start, 0) : 0;
    let ct = 0, cu = 0; const per = [];
    for (const e of css) { if (!e.url.includes('/static/')) continue; ct += e.text.length; cu += used(e); per.push([e.url.split('/').pop().split('?')[0].replace(/\.[0-9a-f]{12}\./,'.'), Math.round(e.text.length/1024), Math.round(100*used(e)/e.text.length)]); }
    let jt = 0, ju = 0; const jper = [];
    for (const e of js) { if (!e.url.includes('/static/')) continue; const total = e.source ? e.source.length : 0; let u = 0; for (const f of e.functions) for (const r of f.ranges) if (r.count > 0 && f.ranges.length) { /* coarse */ }
      // block coverage: sum of top-level function ranges with count>0 minus nested zero ranges
      const marks = new Uint8Array(total); for (const f of e.functions) for (const r of f.ranges) marks.fill(r.count > 0 ? 1 : 0, r.startOffset, r.endOffset); u = marks.reduce((s, v) => s + v, 0);
      jt += total; ju += u; jper.push([e.url.split('/').pop().split('?')[0].replace(/\.[0-9a-f]{12}\./,'.'), Math.round(total/1024), Math.round(100*u/Math.max(1,total))]); }
    console.log(`${email.split('@')[0]} ${path}: CSS ${Math.round(ct/1024)} KB loaded, ${Math.round(cu/1024)} KB used (${Math.round(100*cu/ct)}%) | JS ${Math.round(jt/1024)} KB loaded, ${Math.round(ju/1024)} KB executed (${Math.round(100*ju/jt)}%)`);
    if (path === '/dashboard') { console.log('   css:', JSON.stringify(per.sort((a,b)=>b[1]-a[1]).slice(0,9))); console.log('   js :', JSON.stringify(jper.sort((a,b)=>b[1]-a[1]).slice(0,9))); }
  }
}
await b.close(); })().catch(e => { console.error(e); process.exit(1); });
