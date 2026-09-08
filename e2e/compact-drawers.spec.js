const {test,expect}=require('@playwright/test');
const {signIn}=require('./helpers/auth');
test.use({video:'off',trace:'off',serviceWorkers:'block'});
test('scheduling, assignment and cluster creation stay centred and contained',async({page})=>{
 test.setTimeout(180000);
 await signIn(page,'cceo@edify.org','edify',{acceptRequiredAgreements:false});
 for(const flow of [
  {url:'/core-schools',selector:'.school-record-action[hx-get*="schedule-activity"]'},
  {url:'/core-schools',selector:'.school-record-action[hx-get*="schedule-activity"]',nested:'[hx-get*="schedule-visit?"]'},
  {url:'/core-schools',selector:'.school-record-action[hx-get*="assign-partner"]'},
  {url:'/clusters',selector:'[hx-get="/clusters/create-drawer"]'}
 ]){
  await page.goto(flow.url);await page.locator(flow.selector).first().click();
  let surface=page.locator('.drawer-surface.active');await expect(surface).toBeVisible();
  if(flow.nested){await surface.locator(flow.nested).first().click();surface=page.locator('.edify-popup-dialog__surface');await expect(surface.locator('form')).toBeVisible();}
  await page.addStyleTag({content:'*,*::before,*::after{transition:none!important;animation:none!important}'});
  for(const width of [390,768,1290,1920]){
   await page.setViewportSize({width,height:900});
   const r=await surface.boundingBox();
   expect(r.x).toBeGreaterThanOrEqual(8);expect(r.y).toBeGreaterThanOrEqual(8);
   expect(Math.abs(r.x+r.width/2-width/2)).toBeLessThan(2);
   expect(Math.abs(r.y+r.height/2-450)).toBeLessThan(2);
   expect(r.height).toBeLessThanOrEqual(880);
   if(width>=768)expect(r.width).toBeLessThanOrEqual(800);
   expect(await surface.evaluate(e=>e.scrollWidth-e.clientWidth)).toBeLessThanOrEqual(2);
  }
  await page.setViewportSize({width:1290,height:900});
  await page.screenshot({path:'/tmp/drawer-'+(flow.nested?'visit':flow.url.includes('clusters')?'cluster':flow.selector.includes('assign')?'assign':'schedule')+'.png'});
  await surface.locator(flow.nested?'[aria-label="Close schedule Core Visit dialog"]':'.drawer-close-btn').click();
  await expect(surface).toHaveCount(0);
 }
});
test('leave drawer is centred on desktop',async({page})=>{
 await signIn(page,'cceo@edify.org','edify',{acceptRequiredAgreements:false});
 await page.setViewportSize({width:1440,height:900});
 await page.goto('/personal-time-off/');
 await page.getByRole('button',{name:'Request leave',exact:true}).first().click();
 const panel=page.locator('.pto-drawer-panel');await expect(panel).toBeVisible();
 await page.addStyleTag({content:'*{animation:none!important;transition:none!important}'});
 const r=await panel.boundingBox();expect(r.width).toBeLessThanOrEqual(560);
 expect(Math.abs(r.x+r.width/2-720)).toBeLessThan(2);
 expect(r.y).toBeGreaterThanOrEqual(30);
});
