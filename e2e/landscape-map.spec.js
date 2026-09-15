const {test,expect}=require('@playwright/test');
const {signIn}=require('./helpers/auth');
const {mapInView}=require('./helpers/map');
test.use({video:'off',trace:'off',serviceWorkers:'block'});
// The map is a fixed 30cm x 42cm portrait sheet for every role (owner,
// 2026-09-15), centred in its card; a card narrower than 30cm shrinks it in
// proportion. 1cm is 96/2.54 CSS pixels.
const CM=96/2.54, SHEET_W=30*CM, SHEET_H=42*CM;
test('the map is a 30cm x 42cm sheet on landscape laptop and desktop windows',async({page})=>{
 test.setTimeout(120000);
 await signIn(page,'cceo@edify.org','edify',{acceptRequiredAgreements:false});
 await page.goto('/dashboard?view=map');
 const svg=page.locator('.sr-map-viewport > svg');await expect(svg).toBeVisible();
 for(const [width,height] of [[1366,768],[1440,900],[1920,1080],[1280,720],[1024,768]]){
  await page.setViewportSize({width,height});
  const map=await mapInView(page);expect(map.top).toBeGreaterThanOrEqual(map.topbarBottom);
  // As wide as the sheet, or as wide as the card allows, and 42/30 as tall as it is wide.
  const canvas=await page.locator('.sr-map-canvas').boundingBox();
  const r=await svg.boundingBox();
  const expectedW=Math.min(SHEET_W,canvas.width);
  expect(Math.abs(r.width-expectedW)).toBeLessThanOrEqual(2);
  expect(Math.abs(r.height-expectedW*SHEET_H/SHEET_W)).toBeLessThanOrEqual(2);
  expect(r.x).toBeGreaterThanOrEqual(0);expect(r.x+r.width).toBeLessThanOrEqual(width);
  await expect(svg).toHaveAttribute('preserveAspectRatio','xMidYMid meet');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  if(width===1366)await page.screenshot({path:'/tmp/landscape-map-laptop.png'});
 }
});
