const {test,expect}=require('@playwright/test');
const {signIn}=require('./helpers/auth');
const {watchPageErrors}=require('./helpers/page-errors');
test.use({video:'off',trace:'off',serviceWorkers:'block'});
// At a phone width the rail keeps the tabs that fit and folds the rest into
// "More" (micro-ux.js stamps data-edify-rail-index once it has fitted the
// rail). A folded tab is chosen the way a reader chooses it: More, then the tab.
async function chooseTab(page,label){
 const tab=page.locator('a[data-edify-tab]').filter({hasText:label}).first();
 await expect(tab).toHaveAttribute('data-edify-rail-index',/\d/);
 if(await tab.evaluate(a=>a.classList.contains('edify-rail-more__item')))await tab.locator('xpath=ancestor::details[1]/summary').click();
 await tab.click();
}
// The Analytics entry is retired (owner, 2026-10-19): /analytics opens each
// reader's own analysis home, which must be as sound as the page it replaced.
for(const [email,home,priorities='/priorities'] of [
 ['cceo@edify.org',/^\/cluster-oversight\/$/],['pl1@edify.org',/^\/staff\/[^/]+$/],
 ['cd@edify.org',/^\/country-profile$/],['rvp@edify.org',/^\/country-profile$/],
 ['ia@edify.org',/^\/country-profile$/],['hr@edify.org',/^\/dashboard$/],
 // The Accountant has no priority surface: /priorities refuses them and their agreement stays at /my-performance (2026-09-11).
 ['accountant@edify.org',/^\/budget$/,'/my-performance'],['coordinator@edify.org',/^\/projects\/analytics$/],['admin@edify.org',/^\/country-profile$/]
]) test(`${email} priorities and their analysis home are responsive and coherent`,async({page},info)=>{
 test.setTimeout(180000);const errors=watchPageErrors(page);
 await signIn(page,email,'edify',{acceptRequiredAgreements:false});
 const dashboard=await page.goto('/dashboard');expect(dashboard.status()).toBeLessThan(400);
 if(priorities!=='/priorities'){await page.goto('/priorities?fy=2026');expect(new URL(page.url()).pathname).not.toBe('/priorities');}
 const response=await page.goto(priorities+'?fy=2026');expect(response.status()).toBe(200);
 await expect(page.locator('[data-edify-tab][aria-current=page]')).toHaveText('Distributed Priorities');
 for(const label of ['Core Values','Spiritual Formation','Professional Development']){
  // The tab, not the sidebar: HR's sidebar entry for /cpd-learning is also "Professional Development" since 2026-10-01.
  await chooseTab(page,label);
  await expect(page.locator('[data-edify-tab][aria-current=page]')).toHaveText(label);
 }
 await chooseTab(page,'Distributed Priorities');
 // The tab is a link: let its page load before resizing. Firefox can hang resizing a page mid-navigation.
 await expect(page.locator('[data-edify-tab][aria-current=page]')).toHaveText('Distributed Priorities');await page.waitForLoadState('load');
 for(const [width,height] of [[390,844],[768,1024],[1366,768]]){
  await page.setViewportSize({width,height});
  for(const theme of ['theme-light','theme-dark dark','theme-blue dark']){
   await page.evaluate(t=>document.documentElement.className=t,theme);
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2)).toBe(true);
  }
 }
 const old=await page.request.get('/analytics',{maxRedirects:0});expect(old.status()).toBe(302);
 const destination=old.headers()['location'];expect(new URL(destination,page.url()).pathname).toMatch(home);
 const result=await page.goto(destination);expect(result.status()).toBe(200);
 for(const [width,height] of [[390,844],[768,1024],[1366,768]]){
  await page.setViewportSize({width,height});
  for(const theme of ['theme-light','theme-dark dark','theme-blue dark']){
   await page.evaluate(t=>document.documentElement.className=t,theme);
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2)).toBe(true);
  }
 }
 await page.screenshot({path:info.outputPath('analysis-home.png')});
 expect(errors).toEqual([]);
});
