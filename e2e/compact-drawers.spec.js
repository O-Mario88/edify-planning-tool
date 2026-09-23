const {test,expect}=require('@playwright/test');
const {signIn}=require('./helpers/auth');
test.use({video:'off',trace:'off',serviceWorkers:'block'});
test('scheduling, assignment and cluster creation stay contained: a sheet on a phone, a centred card wider',async({page})=>{
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
  if(flow.nested){await surface.locator(flow.nested).first().click();surface=page.locator('.drawer-surface.active');await expect(surface.locator('form')).toBeVisible();}
  await page.addStyleTag({content:'*,*::before,*::after{transition:none!important;animation:none!important}'});
  for(const [width,height] of [[390,844],[768,900],[1280,720],[1366,768],[1920,1080]]){
   await page.setViewportSize({width,height});
   const r=await surface.boundingBox();
   // A phone gets a sheet from the bottom edge (2026-09-23); every wider
   // screen keeps the centred card. The nested Core visit drawer is a
   // base_drawer now too, so it is a sheet on a phone like the rest.
   const sheet=width<768;
   if(sheet){
    // Edge to edge and flush with the bottom, within emulation rounding.
    expect(Math.abs(r.x)).toBeLessThan(1);expect(Math.abs(r.width-width)).toBeLessThan(2);
    expect(Math.abs(r.y+r.height-height)).toBeLessThanOrEqual(3);expect(r.y).toBeGreaterThanOrEqual(8);
   }else{
    expect(r.x).toBeGreaterThanOrEqual(8);expect(r.y).toBeGreaterThanOrEqual(8);
    expect(Math.abs(r.x+r.width/2-width/2)).toBeLessThan(2);
    expect(Math.abs(r.y+r.height/2-height/2)).toBeLessThan(2);
    expect(r.height).toBeLessThanOrEqual(height-16);
   }
   if(width>=768)expect(r.width).toBeLessThanOrEqual(800);
   expect(await surface.evaluate(e=>e.scrollWidth-e.clientWidth)).toBeLessThanOrEqual(2);
   const submit=surface.locator('button[type="submit"]').last();
   if(await submit.count() && await submit.isVisible()){
    await submit.scrollIntoViewIfNeeded();const action=await submit.boundingBox();
    expect(action.y).toBeGreaterThanOrEqual(0);
    expect(action.y+action.height).toBeLessThanOrEqual(height);
   }
  }
  await page.setViewportSize({width:1290,height:900});
  await page.screenshot({path:'/tmp/drawer-'+(flow.nested?'visit':flow.url.includes('clusters')?'cluster':flow.selector.includes('assign')?'assign':'schedule')+'.png'});
  await surface.locator('.drawer-close-btn').click();
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
 for(const [width,height] of [[1280,720],[1366,768],[1440,900],[1920,1080]]){
  await page.setViewportSize({width,height});
  const r=await panel.boundingBox();expect(r.width).toBeLessThanOrEqual(560);
  expect(Math.abs(r.x+r.width/2-width/2)).toBeLessThan(2);
  expect(Math.abs(r.y+r.height/2-height/2)).toBeLessThan(2);
  expect(r.y).toBeGreaterThanOrEqual(8);
  expect(r.y+r.height).toBeLessThanOrEqual(height-8);
  expect(await panel.evaluate(e=>e.scrollWidth-e.clientWidth)).toBeLessThanOrEqual(2);
 }
});
