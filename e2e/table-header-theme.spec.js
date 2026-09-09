const {test,expect}=require('@playwright/test');
const {snapshotServer}=require('./helpers/snapshot-server');
const {signIn}=require('./helpers/auth');
const path=require('path');
test.use({video:'off',trace:'off',serviceWorkers:'block'});
test('table title bands and column ink respect theme and viewport',async({page})=>{
 const server=await snapshotServer(path.resolve(__dirname,'..'));
 try{
  server.setHtml('<html class="light"><head><link rel="stylesheet" href="/static/css/design-system.css"><link rel="stylesheet" href="/static/css/consistency.css"><script defer src="/static/js/micro-ux.js"></script></head><body><main><h1>Page heading</h1><section><header><h2>Payment queue</h2></header><div><table><thead><tr><th>Reference</th><th><button>Sort status</button></th></tr></thead><tbody><tr><td>ABC</td><td>Pending</td></tr></tbody></table></div></section></main></body></html>');
  await page.goto(server.origin+'/page');
  await expect(page.locator('header')).toHaveClass(/edify-table-titlebar/);
  for(const width of [390,768,1290]){
   await page.setViewportSize({width,height:900});
   await expect(page.locator('header')).toHaveCSS('background-color','rgb(40, 91, 150)');
   await expect(page.locator('h2')).toHaveCSS('color','rgb(255, 255, 255)');
   await expect(page.locator('th').first()).toHaveCSS('color','rgb(40, 91, 150)');
   const background=await page.locator('th').first().evaluate(e=>getComputedStyle(e).backgroundColor);
   expect(background).toBe(await page.locator('td').first().evaluate(e=>getComputedStyle(e).backgroundColor));
  }
  await expect(page.locator('h1')).not.toHaveClass(/edify-table-titlebar/);
  for(const theme of ['dark','theme-blue']){
   await page.evaluate(t=>document.documentElement.className=t,theme);
   await expect(page.locator('header')).not.toHaveCSS('background-color','rgb(40, 91, 150)');
  }
 }finally{await server.close()}
});
test('Accountant legacy map links open operations without map controls',async({page})=>{
 await signIn(page,'accountant@edify.org','edify',{acceptRequiredAgreements:false});
 await page.goto('/accounts?view=map');
 await expect(page.locator('#fund-filters-card')).toBeVisible();
 await expect(page.locator('[data-accountant-map-view], [data-dashboard-views]')).toHaveCount(0);
});
