const {test, expect} = require('@playwright/test');
const {signIn} = require('./helpers/auth');
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
    await expect.poll(()=>svg.evaluate(e=>Math.round(e.getBoundingClientRect().bottom))).toBeLessThanOrEqual(height);
    if(height===1440) expect((await svg.boundingBox()).height).toBeGreaterThan(560);
  }
  await page.setViewportSize({width:1366,height:768});
  await expect.poll(()=>page.locator('#sr-cam .sr-dl').evaluateAll(nodes=>nodes.every(n=>n.dataset.labelPlacement))).toBe(true);
  const overlaps=await page.locator('#sr-cam .sr-dl').evaluateAll(nodes=>{
    const boxes=nodes.filter(n=>getComputedStyle(n).display!=='none' && Number(getComputedStyle(n).opacity)>0).map(n=>n.getBoundingClientRect());
    return boxes.flatMap((a,i)=>boxes.slice(i+1).filter(b=>a.left<b.right && a.right>b.left && a.top<b.bottom && a.bottom>b.top)).length;
  });
  expect(overlaps).toBe(0);
  await page.screenshot({path:'/tmp/edify-map-labels-laptop.png'});
  await page.locator('#sr-cam path[data-district="Wakiso"]').first().press('Enter');
  await expect(page.locator('#sr-cam .sr-scl').first()).toBeVisible({timeout:25000});
  expect(await page.locator('#sr-cam .sr-scl').evaluateAll(nodes=>nodes.filter(n=>getComputedStyle(n).display!=='none' && Number(getComputedStyle(n).opacity)>0).length)).toBeGreaterThan(0);
  await expect.poll(()=>page.locator('#sr-cam .sr-dl').evaluateAll(nodes=>nodes.filter(n=>Number(getComputedStyle(n).opacity)>0).length)).toBe(0);
  await page.screenshot({path:'/tmp/edify-map-subcounty-laptop.png'});
  expect(errors).toEqual([]);
});
