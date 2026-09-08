const {test,expect}=require('@playwright/test');
const {signIn}=require('./helpers/auth');
test.use({video:'off',serviceWorkers:'block'});
test('populated oversight and finance remain compact, readable and interactive',async({page},info)=>{
 test.setTimeout(180000);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await signIn(page,'accountant@edify.org','edify',{acceptRequiredAgreements:false});
 for(const route of ['/team-planning-oversight/','/accounts','/analytics']){
  await page.goto(route);await expect(page.locator('main[data-workspace-design=calm]')).toBeVisible();
  await page.addStyleTag({content:'*,*::before,*::after{transition:none!important;animation:none!important}'});
  for(const width of [390,768,1048,1600]){
   await page.setViewportSize({width,height:900});
   await page.mouse.move(0,0);
   for(const theme of ['theme-light','theme-dark','theme-blue']){
    await page.evaluate(t=>{document.documentElement.classList.remove('theme-light','theme-dark','theme-blue');document.documentElement.classList.add(t);document.documentElement.classList.toggle('dark',t!=='theme-light')},theme);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2)).toBe(true);
    await expect(page.locator('body')).toHaveCSS('background-image','none');
    if(route.includes('team-planning')){
     const filterBackground=await page.locator('.oversight-filters > summary').evaluate(e=>getComputedStyle(e).backgroundColor);
     await expect(page.getByRole('link',{name:'Export CSV',exact:true})).toHaveCSS('background-color',filterBackground);
    }
    for(const header of await page.locator('main .edify-page-header:visible').all())await expect(header).toHaveCSS('box-shadow','none');
   }
   if(route.includes('team-planning')&&width===1048){
    const top=await page.locator('tbody tr').first().evaluate(el=>el.getBoundingClientRect().top+document.querySelector('main').scrollTop);
    expect(top).toBeLessThan(500);
    expect(['right','end']).toContain(await page.getByRole('columnheader',{name:'Cost',exact:true}).first().evaluate(e=>getComputedStyle(e).textAlign));
   }
   if(route.includes('team-planning')&&(width===390||width===1048)){
    const filters=page.locator('.oversight-filters');
    await filters.locator('summary').click();
    await expect(filters.locator('form')).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2)).toBe(true);
    await filters.locator('summary').click();
   }
   if(width===390||width===1048)await page.screenshot({path:info.outputPath(route.replaceAll('/','_')+width+'.png')});
  }
 }
 const context=page.locator('.analytics-context-disclosure');
 await context.locator('summary').click();
 await expect(context).toHaveAttribute('open','');
 await expect(context.locator('.analytics-decision-frame')).toBeVisible();
 await context.locator('summary').click();
 await page.goto('/accounts');
 await page.getByRole('button',{name:'Paul N.',exact:true}).first().click();
 await expect(page.getByRole('heading',{name:'Paul N. — Weekly Fund Plan',exact:true})).toBeVisible();
 expect(errors).toEqual([]);
});

test('offline fallback remains readable without external styles',async({page})=>{
 await page.route('**/static/css/**',route=>route.abort());
 await page.goto('/offline');
 await expect(page.locator('[data-offline-page]')).toBeVisible();
 await expect(page.locator('[data-offline-title]')).toHaveCSS('font-size','20px');
 await expect(page.getByRole('button',{name:'Retry',exact:true})).toHaveCSS('color','rgb(255, 255, 255)');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('populated field workspaces and a school record share the compact system',async({page,browserName},info)=>{
 test.skip(browserName!=='chromium','Field-workflow depth is checked once; shared components run in all engines.');
 test.setTimeout(180000);
 await signIn(page,'cceo@edify.org','edify',{acceptRequiredAgreements:false});
 await page.goto('/schools');
 const schoolPath=await page.locator('.school-record-row__title a[href^="/schools/"]').first().getAttribute('href');
 expect(schoolPath).toMatch(/^\/schools\/[^/?]+$/);
 for(const route of ['/schools',schoolPath,'/planning','/calendar','/profile']){
  await page.goto(route);await expect(page.locator('main[data-workspace-design=calm]')).toBeVisible();
  await page.addStyleTag({content:'*,*::before,*::after{transition:none!important;animation:none!important}'});
  for(const width of [390,768,1600]){
   await page.setViewportSize({width,height:900});
   await page.mouse.move(0,0);
   for(const theme of ['theme-light','theme-dark','theme-blue']){
    await page.evaluate(t=>{document.documentElement.classList.remove('theme-light','theme-dark','theme-blue');document.documentElement.classList.add(t);document.documentElement.classList.toggle('dark',t!=='theme-light')},theme);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2),route+' '+width+' '+theme).toBe(true);
   }
  }
  if(route===schoolPath)await page.screenshot({path:info.outputPath('school-record.png')});
 }
});
