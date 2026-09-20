const {test,expect}=require('@playwright/test');
const {signIn}=require('./helpers/auth');
test('desktop controls retain CSS dimensions across Windows-like display densities',async({browser})=>{
 test.setTimeout(180000);
 let storageState;
 for(const [width,scale] of [[1280,1],[1920,1.5],[2560,2]]){
  const context=await browser.newContext({viewport:{width,height:900},deviceScaleFactor:scale,...(storageState?{storageState}:{})});
  const page=await context.newPage();
  if(!storageState){await signIn(page,'pl1@edify.org','edify',{acceptRequiredAgreements:false});storageState=await context.storageState();}
  await page.goto('/debriefs');
  await page.evaluate(()=>{const field=document.createElement('input');field.id='density-check';field.type='text';document.body.append(field);});
  const dimensions=await page.locator('#density-check').evaluate(el=>({font:getComputedStyle(el).fontSize,height:el.getBoundingClientRect().height,zoom:getComputedStyle(document.body).zoom}));
  expect(dimensions.font).toBe('14px');expect(dimensions.height).toBe(38);expect(dimensions.zoom).toBe('1');
  await context.close();
 }
});
