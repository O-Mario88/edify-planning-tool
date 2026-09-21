const {test,expect}=require('@playwright/test');
const {signIn}=require('./helpers/auth');
const {mapInView}=require('./helpers/map');
test.use({video:'off',trace:'off',serviceWorkers:'block'});
// The map is a full-width sheet that FITS THE WINDOW. "Make it fit exactly so
// that the users don't have to scroll" (owner, 2026-09-16) still holds; since
// 2026-09-20 the sheet is the width of its card at up to 600px tall rather
// than the square of 2026-09-17, and its height gives way to the room left
// under the page and card headers on a laptop.
const SHEET_H=600;
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
  // Never taller than the sheet, nor wider than the card holding it.
  expect(r.height,label).toBeLessThanOrEqual(SHEET_H+2);
  expect(r.width,label).toBeLessThanOrEqual(canvas.width+2);
  // It still uses the height it is given rather than collapsing to a stamp.
  expect(r.height,label).toBeGreaterThan(280);
  expect(r.x,label).toBeGreaterThanOrEqual(0);expect(r.x+r.width,label).toBeLessThanOrEqual(width);
  await expect(svg).toHaveAttribute('preserveAspectRatio','xMidYMid meet');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),label).toBe(true);
  if(width===1366)await page.screenshot({path:'/tmp/landscape-map-laptop.png'});
 }
});
