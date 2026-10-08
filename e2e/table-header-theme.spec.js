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
   // A quiet band in the table-header tone with ink text since 2026-10-02 (it was solid navy with white text).
   await expect(page.locator('header')).toHaveCSS('background-color','rgb(220, 230, 236)');
   await expect(page.locator('h2')).toHaveCSS('color','rgb(23, 35, 43)');
   // Column names are the cells' ink, bold, in Title Case, on a line (owner, 2026-10-08); they were blue capitals.
   const th=page.locator('th').first(),td=page.locator('td').first();
   // rgb(35, 56, 68) is --edify-text-muted, what a record table's cells are drawn in.
   await expect(th).toHaveCSS('color','rgb(35, 56, 68)');
   await expect(th).toHaveCSS('text-transform','capitalize');
   await expect(th).toHaveCSS('font-weight','700');
   await expect(th).toHaveCSS('border-bottom-width','2px');
   // What a heading holds is the heading: a sort control is not a link's blue.
   await expect(page.locator('th button')).toHaveCSS('color','rgb(35, 56, 68)');
   // Three steps, largest first: the table's name, the column names, the cells
   // ("just slightly bigger not large ... the table name ... should be larger").
   const px=l=>l.evaluate(e=>parseFloat(getComputedStyle(e).fontSize));
   const [name,column,cell]=[await px(page.locator('h2')),await px(th),await px(td)];
   expect(name).toBeGreaterThan(column);expect(column).toBeGreaterThan(cell);
   expect(column-cell).toBeLessThanOrEqual(1.5);
   await expect(page.locator('h2')).toHaveCSS('font-weight','700');
   const background=await page.locator('th').first().evaluate(e=>getComputedStyle(e).backgroundColor);
   expect(background).toBe(await page.locator('td').first().evaluate(e=>getComputedStyle(e).backgroundColor));
  }
  await expect(page.locator('h1')).not.toHaveClass(/edify-table-titlebar/);
  // The classes base.html writes for each theme: the band then takes that theme's own table-header tone.
  for(const theme of ['dark theme-dark','dark theme-blue']){
   await page.evaluate(t=>document.documentElement.className=t,theme);
   await expect(page.locator('header')).not.toHaveCSS('background-color','rgb(220, 230, 236)');
  }
 }finally{await server.close()}
});
test('Accountant legacy map links open operations without map controls',async({page})=>{
 await signIn(page,'accountant@edify.org','edify',{acceptRequiredAgreements:false});
 await page.goto('/accounts?view=map');
 await expect(page.locator('#fund-filters-card')).toBeVisible();
 await expect(page.locator('[data-accountant-map-view], [data-dashboard-views]')).toHaveCount(0);
});
