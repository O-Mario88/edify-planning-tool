const {test,expect}=require('@playwright/test');
const {signIn}=require('./helpers/auth');
test.use({video:'off',trace:'off',serviceWorkers:'block'});
for(const [email,analytics] of [
 ['cceo@edify.org','/analytics'],['pl1@edify.org','/analytics/program-lead'],
 ['cd@edify.org','/analytics/country-director'],['rvp@edify.org','/analytics'],
 ['ia@edify.org','/analytics'],['hr@edify.org','/analytics'],
 ['accountant@edify.org','/analytics'],['coordinator@edify.org','/analytics'],['admin@edify.org','/analytics']
]) test(`${email} priorities and analytics are responsive and coherent`,async({page},info)=>{
 test.setTimeout(180000);const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await signIn(page,email,'edify',{acceptRequiredAgreements:false});
 const dashboard=await page.goto('/dashboard');expect(dashboard.status()).toBeLessThan(400);
 const response=await page.goto('/priorities?fy=2026');expect(response.status()).toBe(200);
 await expect(page.locator('[data-edify-tab][aria-current=page]')).toHaveText('Distributed Priorities');
 for(const label of ['Core Values','Spiritual Formation','Professional Development']){
  await page.getByRole('link',{name:label,exact:true}).click();
  await expect(page.locator('[data-edify-tab][aria-current=page]')).toHaveText(label);
 }
 await page.getByRole('link',{name:'Distributed Priorities',exact:true}).click();
 for(const [width,height] of [[390,844],[768,1024],[1366,768]]){
  await page.setViewportSize({width,height});
  for(const theme of ['theme-light','theme-dark dark','theme-blue dark']){
   await page.evaluate(t=>document.documentElement.className=t,theme);
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2)).toBe(true);
  }
 }
 const result=await page.goto(analytics);expect(result.status()).toBe(200);
 const quarter=page.locator('#pl-analytics-filters select[name=quarter], #cd-analytics-filters select[name=quarter]');
 if(await quarter.count()){
  const refreshed=page.waitForResponse(r=>r.url().includes('quarter=Q1') && r.request().resourceType()==='xhr');
  await quarter.first().selectOption('Q1');
  expect((await refreshed).status()).toBe(200);
  await expect(page).toHaveURL(/quarter=Q1/);
 }
 await expect(page.locator('.analytics-executive-pulse')).toHaveCount(1);
 await expect(page.locator('.analytics-executive-pulse > [data-context-metrics]')).toHaveCount(1);
 for(const [width,height] of [[390,844],[768,1024],[1366,768]]){
  await page.setViewportSize({width,height});
  for(const theme of ['theme-light','theme-dark dark','theme-blue dark']){
   await page.evaluate(t=>document.documentElement.className=t,theme);
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2)).toBe(true);
  }
 }
 await page.screenshot({path:info.outputPath('analytics.png')});
 expect(errors).toEqual([]);
});
