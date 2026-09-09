const {test,expect}=require('@playwright/test');
const {signIn}=require('./helpers/auth');
test.use({video:'off',trace:'off',serviceWorkers:'block'});
test('complete map fits landscape laptop and desktop viewports',async({page})=>{
 test.setTimeout(120000);
 await signIn(page,'cceo@edify.org','edify',{acceptRequiredAgreements:false});
 await page.goto('/dashboard?view=map');
 const svg=page.locator('.sr-map-viewport > svg');await expect(svg).toBeVisible();
 for(const [width,height] of [[1366,768],[1440,900],[1920,1080],[1280,720],[1024,768]]){
  await page.setViewportSize({width,height});
  await expect.poll(async()=>svg.evaluate(e=>Math.round(e.getBoundingClientRect().bottom))).toBeLessThanOrEqual(height);
  const r=await svg.boundingBox();expect(r.x).toBeGreaterThanOrEqual(0);expect(r.x+r.width).toBeLessThanOrEqual(width);
  await expect(svg).toHaveAttribute('preserveAspectRatio','xMidYMid meet');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  if(width===1366)await page.screenshot({path:'/tmp/landscape-map-laptop.png'});
 }
});
