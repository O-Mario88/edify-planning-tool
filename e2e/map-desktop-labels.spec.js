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
    // Full width at up to 600px tall since 2026-09-20 (the square of 2026-09-17 gave way to
    // the card's width); the drawing keeps its viewBox of 0 0 620 620 and is never a stamp.
    await mapInView(page);
    await expect.poll(async () => (await svg.boundingBox())?.height || 0).toBeGreaterThan(280);
    await expect.poll(async () => (await svg.boundingBox())?.height || 0).toBeLessThanOrEqual(602);
  }
  await page.setViewportSize({width:1366,height:768});
  // No two names touch on the national overview (owner, 2026-10-02). From 2026-09-11 every district kept its name
  // there and the crowded ones sat on top of each other; a name now needs a place of its own, and one with none is
  // hidden (the tooltip, the table and the sub-region zoom still name it). More than half keep theirs on a laptop. Placement runs
  // in idle slices and restarts on every resize, so after the sweep above it settles in seconds, not frames.
  const districts=await page.locator('#sr-cam path[data-district]').evaluateAll(paths=>new Set(paths.map(p=>p.dataset.district)).size);
  // A name's own box on screen, the one the placement keeps apart (getBBox, in _regional_performance_script.html),
  // not getBoundingClientRect: Firefox adds an SVG element's stroke to that, and every name has a halo of .2em,
  // so names the page had placed clear of each other measured as touching there (12 pairs) and nowhere else.
  const drawn=()=>page.locator('#sr-cam .sr-dl').evaluateAll(nodes=>nodes.filter(n=>n.dataset.labelPlacement && n.dataset.labelPlacement!=='hidden' && getComputedStyle(n).display!=='none' && Number(getComputedStyle(n).opacity)>0).map(n=>{
    const b=n.getBBox(),m=n.getScreenCTM(),xs=[],ys=[];
    for(const [x,y] of [[b.x,b.y],[b.x+b.width,b.y],[b.x,b.y+b.height],[b.x+b.width,b.y+b.height]]){xs.push(m.a*x+m.c*y+m.e);ys.push(m.b*x+m.d*y+m.f);}
    return [Math.min(...xs),Math.min(...ys),Math.max(...xs),Math.max(...ys)];
  }));
  await expect.poll(async()=>(await page.locator('#sr-cam .sr-dl').evaluateAll(nodes=>nodes.filter(n=>n.dataset.labelPlacement).length)),{timeout:30000}).toBe(districts);
  const boxes=await drawn();
  expect(boxes.length).toBeGreaterThan(districts*0.5);
  let touching=0;
  for(let i=0;i<boxes.length;i+=1)for(let j=i+1;j<boxes.length;j+=1){const a=boxes[i],b=boxes[j];if(a[0]<b[2]-1&&b[0]<a[2]-1&&a[1]<b[3]-1&&b[1]<a[3]-1)touching+=1}
  expect(touching).toBe(0);
  await page.screenshot({path:'/tmp/edify-map-labels-laptop.png'});
  await page.locator('#sr-cam path[data-district="Wakiso"]').first().press('Enter');
  await expect(page.locator('#sr-cam .sr-scl').first()).toBeVisible({timeout:25000});
  expect(await page.locator('#sr-cam .sr-scl').evaluateAll(nodes=>nodes.filter(n=>getComputedStyle(n).display!=='none' && Number(getComputedStyle(n).opacity)>0).length)).toBeGreaterThan(0);
  await expect.poll(()=>page.locator('#sr-cam .sr-dl').evaluateAll(nodes=>nodes.filter(n=>Number(getComputedStyle(n).opacity)>0).length)).toBe(0);
  await page.screenshot({path:'/tmp/edify-map-subcounty-laptop.png'});
  expect(errors).toEqual([]);
});
