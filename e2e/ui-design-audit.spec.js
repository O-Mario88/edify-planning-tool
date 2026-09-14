const {test,expect}=require('@playwright/test');
const fs=require('node:fs');const path=require('node:path');
const root=path.resolve(__dirname,'..');const dir=path.join(root,'test-results/kpi-platform-crawl');
const out=path.join(root,'test-results/ui-design-audit');fs.mkdirSync(out,{recursive:true});
const roles=fs.existsSync(dir)?fs.readdirSync(dir).filter(f=>f.endsWith('.json')).map(f=>f.slice(0,-5)):[];
const files=fs.existsSync(dir)?fs.readdirSync(dir).filter(f=>f.endsWith('.html')):[];
const selected=new Set(roles.map(role=>['dashboard','today','accounts'].map(route=>`${role}-_${route}.html`).find(f=>files.includes(f))).filter(Boolean));
for(const file of ['BusinessTransformationOfficer-_business-transformation_overview.html','ImpactAssessment-_ia_dashboard_.html','MfiLoanOfficer-_mfi-portal.html','MfiPartnerAdmin-_loans.html','PartnerAdmin-_my-plan.html','PartnerFieldOfficer-_my-plan.html']) if(files.includes(file)) selected.add(file);
for(const term of ['team-planning','schools.html','projects.html','analytics.html','budget.html','staff','priorities.html','fund-requests','core-schools.html','monthly','profile.html','targets']) {
 const f=files.find(f=>f.includes(term)&&!selected.has(f));if(f)selected.add(f);
}
function violations(results){
 const found=[];
 for(const r of results){
  if(r.pageWidth>r.viewport+1)found.push(`${r.width}px ${r.theme}: page scrolls sideways (${r.pageWidth}px wide)`);
  if(r.unnamed.length)found.push(`${r.width}px ${r.theme}: controls without an accessible name: ${r.unnamed.join(' | ')}`);
  if(!r.headingCount)found.push(`${r.width}px ${r.theme}: no page heading`);
 }
 return [...new Set(found)];
}
test('the audit fails a page that overflows or has an unnamed control',()=>{
 const broken=[{width:390,theme:'theme-light',pageWidth:1200,viewport:390,unnamed:['<button class="icon"></button>'],headingCount:0}];
 const found=violations(broken);
 expect(found.some(v=>v.includes('scrolls sideways'))).toBe(true);
 expect(found.some(v=>v.includes('accessible name'))).toBe(true);
 expect(found.some(v=>v.includes('no page heading'))).toBe(true);
 expect(violations([{width:1440,theme:'theme-dark',pageWidth:1440,viewport:1440,unnamed:[],headingCount:2}])).toEqual([]);
});
test.use({video:'off',trace:'off'});test.describe.configure({mode:'parallel'});
for(const file of selected)test(file,async({page})=>{
 test.setTimeout(90000);const results=[];const html=fs.readFileSync(path.join(dir,file),'utf8');
 await page.route('**/*',route=>{const u=new URL(route.request().url());if(u.hostname!=='audit.test')return route.fulfill({status:204});const f=path.join(root,u.pathname);if(u.pathname.startsWith('/static/')&&fs.existsSync(f)&&fs.statSync(f).isFile())return route.fulfill({path:f});return route.fulfill({body:u.pathname==='/page'?html:'',contentType:'text/html'});});
 await page.goto('http://audit.test/page',{waitUntil:'domcontentloaded'});
 await page.addStyleTag({content:'*,*::before,*::after{transition:none!important;animation:none!important}'});
 for(const width of [390,768,1440]){
  await page.setViewportSize({width,height:900});
  for(const theme of ['theme-light','theme-dark','theme-blue']){
   await page.evaluate(theme=>{document.documentElement.classList.remove('theme-light','theme-dark','theme-blue');document.documentElement.classList.add(theme)},theme);
   const data=await page.evaluate(()=>{
    const main=document.querySelector('main');const visible=e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&getComputedStyle(e).visibility!=='hidden'};
    const sample=e=>{const s=getComputedStyle(e),r=e.getBoundingClientRect();return {text:e.textContent.trim().replace(/\s+/g,' ').slice(0,70),tag:e.tagName,cls:typeof e.className==='string'?e.className.slice(0,100):'',size:s.fontSize,font:s.fontFamily,weight:s.fontWeight,height:Math.round(r.height),width:Math.round(r.width),y:Math.round(r.y),padding:s.padding,radius:s.borderRadius,shadow:s.boxShadow};};
    const get=sel=>[...main.querySelectorAll(sel)].filter(visible);
    const named=e=>{if((e.getAttribute('aria-label')||'').trim()||(e.getAttribute('title')||'').trim())return true;const by=e.getAttribute('aria-labelledby');if(by&&by.split(/\s+/).some(id=>(document.getElementById(id)||{}).textContent))return true;if(['INPUT','SELECT','TEXTAREA'].includes(e.tagName)){if(e.id&&document.querySelector(`label[for="${CSS.escape(e.id)}"]`))return true;if(e.closest('label'))return true;return false;}return e.textContent.trim().length>0||!!e.querySelector('img[alt]:not([alt=""]),svg[aria-label]');};
    const unnamed=get('button,a[href],[role=tab],input:not([type=hidden]),select,textarea').filter(e=>e.getAttribute('aria-hidden')!=='true'&&!named(e)).slice(0,10).map(e=>e.outerHTML.slice(0,120));
    return {unnamed,headingCount:get('h1,h2').length,pageWidth:document.documentElement.scrollWidth,viewport:innerWidth,headings:get('h1,h2,h3').slice(0,12).map(sample),text:get('p,label,td,th').slice(0,80).map(sample),buttons:get('button,a.btn,[role=tab],input:not([type=hidden]),select').slice(0,60).map(sample),rows:get('tr').slice(0,40).map(sample),kpis:get('.context-metrics__sentence').map(sample),fonts:[...new Set(get('*').filter(e=>e.children.length===0&&e.textContent.trim()).map(e=>getComputedStyle(e).fontFamily))],firstTable:get('table')[0]?Math.round(get('table')[0].getBoundingClientRect().y):null};
   });results.push({width,theme,...data});
  }
 }
 fs.writeFileSync(path.join(out,file+'.json'),JSON.stringify(results,null,2));expect(results).toHaveLength(9);
 // The collector asserts what it measures (controls audit G-01, 2026-09-14):
 // a count of samples proved nothing about the page.
 expect(violations(results),file).toEqual([]);
});
