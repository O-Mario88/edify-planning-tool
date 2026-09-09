const {test,expect}=require('@playwright/test');
const {signIn}=require('./helpers/auth');
test.use({video:'off',trace:'off'});
test('blue workspace inherits login brand surfaces and typography',async({page},info)=>{
 await page.goto('/login');
 const brand=await page.locator('.impact-card').evaluate(e=>({background:getComputedStyle(e).backgroundImage,font:getComputedStyle(e).fontFamily}));
 await signIn(page,'admin@edify.org','edify',{acceptRequiredAgreements:false});
 for(const route of ['/dashboard','/projects/planning','/personal-time-off/']){
  await page.goto(route);
  await page.evaluate(()=>{document.documentElement.classList.remove('theme-dark','light');document.documentElement.classList.add('theme-blue','dark');});
  for(const width of [390,768,1366]){
   await page.setViewportSize({width,height:900});
   const strip=page.locator('.context-metrics__sentence').first();
   await expect(strip).toBeVisible();
   await expect(strip).toHaveCSS('background-image',brand.background);
   await expect(strip).toHaveCSS('font-family',brand.font);
   expect(await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth)).toBeLessThanOrEqual(1);
  }
  await page.screenshot({path:`test-results/blue-brand/${info.project.name}-${route.replaceAll('/','-')}.png`,fullPage:true});
 }
});
