const {test,expect}=require('@playwright/test');
const {signIn}=require('./helpers/auth');
test.use({video:'off',trace:'off',serviceWorkers:'block'});
test('blue login and compact Planning and leave strips at every device size',async({page},info)=>{
 test.setTimeout(180000);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/login');
 for(const width of [390,768,1048,1290,1600]){
  await page.setViewportSize({width,height:900});
  const strip=page.locator('.login-brand .context-metrics__sentence');
  await expect(strip).toBeVisible();
  await expect(strip).toHaveCSS('background-image','linear-gradient(110deg, rgb(7, 52, 84), rgb(16, 63, 98))');
  await expect(page.locator('.login-brand .context-metrics__fact')).toHaveCount(4);
  if(width>1120)await expect(page.locator('.impact-card__title')).toHaveCSS('color','rgb(255, 255, 255)');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.screenshot({path:info.outputPath('login-'+width+'.png'),fullPage:true});
 }
 await signIn(page,'accountant@edify.org','edify',{acceptRequiredAgreements:false});
 for(const route of ['/planning','/personal-time-off/']){
  await page.goto(route);
  await expect(page.locator('main')).toBeVisible();
  if(route==='/planning'){
   await expect(page.locator('#planning-intelligence-panel')).toHaveCount(0);
   await expect(page.locator('main .context-metrics__fact')).toHaveCount(9);
   await expect(page.locator('main .context-metrics__label').filter({hasText:'Not grouped in cluster'})).toHaveCount(1);
  }else{
   await expect(page.locator('.pto-page > .context-metrics .context-metrics__fact')).toHaveCount(6);
   await expect(page.locator('.pto-balance-tile,.pto-hero-balance,.pto-signal-grid')).toHaveCount(0);
   await expect(page.getByRole('button',{name:'Request leave',exact:true}).first()).toBeVisible();
  }
  for(const width of [390,768,1048,1600]){
   await page.setViewportSize({width,height:900});
   for(const theme of ['theme-light','theme-dark','theme-blue']){
    await page.evaluate(t=>{document.documentElement.classList.remove('theme-light','theme-dark','theme-blue');document.documentElement.classList.add(t);document.documentElement.classList.toggle('dark',t!=='theme-light')},theme);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),route+' '+width+' '+theme).toBe(true);
    if(theme==='theme-light')await expect(page.locator('body')).toHaveCSS('background-color','rgb(232, 238, 245)');
    for(const strip of await page.locator('main .context-metrics__sentence').all()){
     const box=await strip.boundingBox();expect(box.width).toBeLessThanOrEqual(width);
     await expect(strip).toHaveCSS('background-color',theme==='theme-light'?'rgb(255, 255, 255)':theme==='theme-dark'?'rgb(18, 34, 52)':'rgba(0, 0, 0, 0)');
    }
    if(theme==='theme-light')await page.screenshot({path:info.outputPath(route.replaceAll('/','')+'-'+width+'-'+theme+'.png'),fullPage:true});
   }
  }
  if(route.includes('personal')){
   await page.getByRole('button',{name:'Request leave',exact:true}).first().click();
   await expect(page.locator('.pto-drawer-panel')).toBeVisible();
  }
 }
 expect(errors).toEqual([]);
});
