const {test, expect} = require('@playwright/test');
const {signIn} = require('./helpers/auth');
const {mapInView} = require('./helpers/map');
test.use({video:'off',trace:'off',serviceWorkers:'block'});
test('desktop labels survive laptop heights and district drilldown', async({page}) => {
  const errors=[]; page.on('pageerror', e=>errors.push(e.message));
  await signIn(page,'cceo@edify.org','edify',{acceptRequiredAgreements:false});
  await page.goto('/dashboard?view=map');
  const svg=page.locator('.sr-map-viewport > svg');
  await expect(svg).toBeVisible();
  for (const [width,height] of [[1280,720],[1366,768],[1440,900],[1920,1080],[2560,1440]]) {
    await page.setViewportSize({width,height});
    await expect.poll(()=>page.locator('#sr-cam .sr-dl').evaluateAll(nodes=>nodes.filter(n=>getComputedStyle(n).display!=='none' && Number(getComputedStyle(n).opacity)>0).length)).toBeGreaterThan(15);
    // An opaque label can still disappear when a rem token is parsed as px.
    // Measure the actual screen font size, including SVG placement scaling.
    await expect.poll(()=>page.locator('#sr-cam .sr-dl').first().evaluate(node=>{
      const matrix=node.getScreenCTM();
      return parseFloat(getComputedStyle(node).fontSize)*Math.hypot(matrix.a,matrix.b);
    })).toBeGreaterThanOrEqual(7);
    // Square (owner, 2026-09-17: "The map should be square much as it will fill the desktop page.
    // i dont mind the dead space on the sides"). It was a 30cm x 42cm portrait sheet, which wasted a
    // band the width of the card above and below a square drawing: the SVG viewBox is 0 0 620 620.
    await mapInView(page);
    await expect.poll(async () => { const r=await svg.boundingBox(); return r ? r.height/r.width : 0; }).toBeGreaterThan(0.9);
    await expect.poll(async () => { const r=await svg.boundingBox(); return r ? r.height/r.width : 99; }).toBeLessThan(1.1);
    if (height === 1440) {
      await expect.poll(async () => (await svg.boundingBox())?.height || 0).toBeGreaterThan(560);
    }
  }
  await page.setViewportSize({width:1366,height:768});
  // Every district keeps its name on the national overview. A name with no clear space inside its boundary takes
  // the least crowded spot rather than vanishing (owner, 2026-09-11: the labels had disappeared), so names of small
  // neighbouring districts may touch at laptop size; none is hidden. Placement runs in idle slices and restarts on every resize,
  // so after the sweep above it settles in seconds, not frames.
  const districts=await page.locator('#sr-cam path[data-district]').evaluateAll(paths=>new Set(paths.map(p=>p.dataset.district)).size);
  await expect.poll(()=>page.locator('#sr-cam .sr-dl').evaluateAll(nodes=>nodes.filter(n=>n.dataset.labelPlacement && n.dataset.labelPlacement!=='hidden' && getComputedStyle(n).display!=='none' && Number(getComputedStyle(n).opacity)>0).length),{timeout:30000}).toBe(districts);
  await page.screenshot({path:'/tmp/edify-map-labels-laptop.png'});
  await page.locator('#sr-cam path[data-district="Wakiso"]').first().press('Enter');
  await expect(page.locator('#sr-cam .sr-scl').first()).toBeVisible({timeout:25000});
  expect(await page.locator('#sr-cam .sr-scl').evaluateAll(nodes=>nodes.filter(n=>getComputedStyle(n).display!=='none' && Number(getComputedStyle(n).opacity)>0).length)).toBeGreaterThan(0);
  await expect.poll(()=>page.locator('#sr-cam .sr-dl').evaluateAll(nodes=>nodes.filter(n=>Number(getComputedStyle(n).opacity)>0).length)).toBe(0);
  await page.screenshot({path:'/tmp/edify-map-subcounty-laptop.png'});
  expect(errors).toEqual([]);
});
