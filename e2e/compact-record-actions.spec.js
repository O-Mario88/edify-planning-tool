const {test,expect}=require('@playwright/test');
const {snapshotServer}=require('./helpers/snapshot-server');
const {signIn}=require('./helpers/auth');
const fs=require('fs'),path=require('path');
test.use({video:'off',trace:'off',serviceWorkers:'block'});
// Record actions close at 1.75rem (28px) since the 2026-09-19 table button
// refinement (consistency.css, compact record actions).
test('compact record actions across platform pages',async({page},info)=>{
 test.setTimeout(360000);
 const root=path.resolve(__dirname,'..'),dir=path.join(root,'test-results/kpi-platform-crawl');
 test.skip(!fs.existsSync(dir), 'Requires test-results/kpi-platform-crawl');
 const files=fs.existsSync(dir)?fs.readdirSync(dir).filter(f=>/^Admin-.*\.html$/.test(f)):[];
 const server=await snapshotServer(root),issues=[];let checked=0;
 try{for(const file of files){
  const html=fs.readFileSync(path.join(dir,file),'utf8');if(!html.includes('<table')&&!html.includes('school-record-action')&&!html.includes('data-row-actions'))continue;
  server.setHtml(html);await page.goto(server.origin+'/page',{waitUntil:'domcontentloaded'});
  await page.addStyleTag({content:'*,*::before,*::after{transition:none!important;animation:none!important}'});
  for(const width of [390,768,1290]){
   await page.setViewportSize({width,height:900});
   for(const theme of ['theme-light','theme-dark','theme-blue']){
    await page.evaluate(t=>{document.documentElement.classList.remove('theme-light','theme-dark','theme-blue');document.documentElement.classList.add(t);document.documentElement.classList.toggle('dark',t!=='theme-light')},theme);
    const errors=await page.evaluate(()=>{
     const errors=[];
     for(const e of document.querySelectorAll(':is(.school-record-row,.school-list-card,.cluster-card) .school-record-action, table .edify-table-action')){
      if(e.closest('[role="menu"], .row-menu, [popover]')||e.matches('[role="menuitem"]'))continue;
      const r=e.getBoundingClientRect();if(!r.width||!r.height)continue;
      if(Math.abs(r.height-28)>1)errors.push(e.tagName+' '+e.className+' height='+r.height);
      if(e.scrollHeight>e.clientHeight+2)errors.push(e.className+' clipped content '+e.scrollHeight+'/'+e.clientHeight);
     }
     return [...new Set(errors)].slice(0,8);
    });checked++;if(errors.length)issues.push({file,width,theme,errors});
   }
  }
 }
 await info.attach('compact-action-coverage',{body:JSON.stringify({checked,issues},null,2),contentType:'application/json'});
 expect(checked).toBeGreaterThan(100);expect(issues).toEqual([]);
 }finally{await server.close()}
});

// School Directory rows, Core School rows and cluster cards carry one Actions
// menu since 2026-09-26 (owner: "switch to Action button with options to
// schedule and assign"). The trigger is the record's one control: it must
// stay on one line (the tablet wrap the owner reported) and never clip.
test('school scheduling action still opens its drawer',async({page})=>{
 await signIn(page,'cceo@edify.org','edify',{acceptRequiredAgreements:false});
 test.setTimeout(120000);
 for(const route of ['/schools','/core-schools','/clusters']){
  await page.goto(route);
  const triggers=page.locator(':is(.school-record-row,.school-list-card,.cluster-card) .row-menu__trigger');
  await expect(triggers.first()).toBeVisible();
  for(const width of [390,768,1290]){
   await page.setViewportSize({width,height:900});
   for(const theme of ['theme-light','theme-dark','theme-blue']){
    await page.evaluate(t=>{document.documentElement.classList.remove('theme-light','theme-dark','theme-blue');document.documentElement.classList.add(t);document.documentElement.classList.toggle('dark',t!=='theme-light')},theme);
    const issues=await triggers.evaluateAll(items=>items.filter(e=>{const r=e.getBoundingClientRect();const floor=parseFloat(getComputedStyle(e).minHeight)||0;return r.width&&r.height&&(r.height>floor+1||e.scrollHeight>e.clientHeight+2||e.scrollWidth>e.clientWidth+2)}).map(e=>e.className+' height='+e.getBoundingClientRect().height));
    expect(issues,route+' '+width+' '+theme).toEqual([]);
   }
  }
 }
 await page.goto('/core-schools');
 const item='[role="menuitem"][hx-get*="schedule-activity"]';
 const row=page.locator('.core-school-row').filter({has:page.locator(item)}).first();
 const trigger=row.locator('.row-menu__trigger');
 await expect(trigger).toBeVisible();
 await trigger.focus();
 await trigger.press('Enter');
 // Opening moves focus to the first entry, which is Schedule.
 const action=row.locator(item);
 await expect(action).toBeFocused();
 await action.press('Enter');
 await expect(page.locator('#drawer-container').first()).toContainText('Schedule');
});
