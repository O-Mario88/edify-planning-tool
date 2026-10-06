const { chromium } = require('@playwright/test');
const B = 'http://127.0.0.1:8376';
const INIT = `window.__rw={cls:{},attr:{},added:0,removed:0,moved:0,text:0};document.addEventListener('DOMContentLoaded',()=>{const old=new WeakMap();
new MutationObserver(rs=>{for(const r of rs){if(r.type==='attributes'){const n=r.target;if(r.attributeName==='class'){const before=new Set((r.oldValue||'').split(/\\s+/));for(const c of n.classList)if(!before.has(c))window.__rw.cls[c]=(window.__rw.cls[c]||0)+1;}else window.__rw.attr[r.attributeName]=(window.__rw.attr[r.attributeName]||0)+1;}else if(r.type==='childList'){window.__rw.added+=r.addedNodes.length;window.__rw.removed+=r.removedNodes.length;}else window.__rw.text++;}}).observe(document.documentElement,{subtree:true,childList:true,attributes:true,attributeOldValue:true,characterData:true});});`;
(async () => { const b = await chromium.launch();
for (const [email, paths] of [['cceo1@edify.org', ['/dashboard','/planning','/my-plan','/schools']], ['pl1@edify.org', ['/dashboard']], ['cd@edify.org', ['/dashboard']]]) {
  const ctx = await b.newContext({viewport:{width:1440,height:900}}); await ctx.addInitScript(INIT); const p = await ctx.newPage();
  await p.goto(B + '/login'); await p.fill('input[name=email]', email); await p.fill('input[name=password]','edify'); await Promise.all([p.waitForNavigation(), p.press('input[name=password]','Enter')]);
  for (const path of paths) { await p.goto(B + path, { waitUntil: 'load', timeout: 180000 }); await p.waitForTimeout(3000);
    const r = await p.evaluate(() => { const w = window.__rw; const top = (o, n) => Object.entries(o).sort((a, b) => b[1] - a[1]).slice(0, n); return { classAdds: Object.values(w.cls).reduce((s, v) => s + v, 0), distinctClasses: Object.keys(w.cls).length, topClasses: top(w.cls, 14), attrWrites: Object.values(w.attr).reduce((s, v) => s + v, 0), topAttrs: top(w.attr, 10), nodesAdded: w.added, nodesRemoved: w.removed, elements: document.getElementsByTagName('*').length }; });
    console.log(email.split('@')[0], path, JSON.stringify(r)); }
  await ctx.close(); }
await b.close(); })().catch(e => { console.error(e); process.exit(1); });
