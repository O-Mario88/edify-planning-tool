const {test,expect}=require('@playwright/test');
const {signIn}=require('./helpers/auth');
const {mapInView}=require('./helpers/map');
test.use({video:'off',trace:'off',serviceWorkers:'block'});
// The map is a portrait sheet that FITS THE WINDOW (owner, 2026-09-16: "the
// map is too large ... make it fit exactly so that the users don't have to
// scroll"). It keeps its 30:42 proportions and is never wider than 30cm or
// than the card, but its height is now bounded by the room left under the
// page and card headers — it used to be a fixed 30cm x 42cm box, which is
// 1134 x 1587px and so taller than any laptop. 1cm is 96/2.54 CSS pixels.
const CM=96/2.54, SHEET_W=30*CM, RATIO=42/30;
test('the map fits the window on landscape laptop and desktop windows',async({page})=>{
 test.setTimeout(120000);
 await signIn(page,'cceo@edify.org','edify',{acceptRequiredAgreements:false});
 await page.goto('/dashboard?view=map');
 const svg=page.locator('.sr-map-viewport > svg');await expect(svg).toBeVisible();
 for(const [width,height] of [[1366,768],[1440,900],[1920,1080],[1280,720],[1024,768]]){
  await page.setViewportSize({width,height});
  const map=await mapInView(page);
  const label=`${width}x${height}`;
  expect(map.top,label).toBeGreaterThanOrEqual(map.topbarBottom);
  // The whole sheet is on screen: no scrolling to read the bottom of it.
  expect(map.bottom,label).toBeLessThanOrEqual(height);
  const canvas=await page.locator('.sr-map-canvas').boundingBox();
  const r=await svg.boundingBox();
  // Portrait proportions are kept, so the country is never stretched.
  expect(Math.abs(r.height-r.width*RATIO),label).toBeLessThanOrEqual(2);
  // Never wider than the sheet's cap, nor than the card holding it.
  expect(r.width,label).toBeLessThanOrEqual(Math.min(SHEET_W,canvas.width)+2);
  // It still uses the height it is given rather than collapsing to a stamp.
  expect(r.height,label).toBeGreaterThan(280);
  expect(r.x,label).toBeGreaterThanOrEqual(0);expect(r.x+r.width,label).toBeLessThanOrEqual(width);
  await expect(svg).toHaveAttribute('preserveAspectRatio','xMidYMid meet');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),label).toBe(true);
  if(width===1366)await page.screenshot({path:'/tmp/landscape-map-laptop.png'});
 }
});
