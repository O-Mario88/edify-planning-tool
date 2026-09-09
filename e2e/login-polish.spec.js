const {test,expect}=require('@playwright/test');
test.use({video:'off',trace:'off'});
test('login surfaces, padding and icon-free fields stay consistent across viewports',async({page},info)=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('/login?next=/projects/planning');
 await page.addStyleTag({content:'*,*::before,*::after{animation:none!important;transition:none!important}'});
 for(const [width,height] of [[360,740],[390,844],[768,1024],[1280,720],[1366,768],[1920,1080]]){
  await page.setViewportSize({width,height});
  const data=await page.evaluate(()=>{
   const q=s=>document.querySelector(s),card=q('.login-card').getBoundingClientRect(),field=q('#email').getBoundingClientRect();
   return {overflow:document.documentElement.scrollWidth-innerWidth,cardBottom:card.bottom,inset:field.left-card.left,padding:parseFloat(getComputedStyle(q('.login-card__inner')).paddingTop),logoTop:q('.login-brand__header').getBoundingClientRect().top,impact:getComputedStyle(q('.impact-card')).backgroundImage,kpi:getComputedStyle(q('.context-metrics__sentence')).backgroundImage};
  });
  expect(data.overflow).toBeLessThanOrEqual(1);expect(data.inset).toBeGreaterThanOrEqual(24);expect(data.padding).toBeGreaterThanOrEqual(28);
  expect(data.kpi).toBe(data.impact);
  if(width>1120){expect(data.logoTop).toBeGreaterThanOrEqual(32);expect(data.cardBottom).toBeLessThanOrEqual(height-16);}
  await expect(page.locator('.login-field__control > svg')).toHaveCount(0);
  await page.screenshot({path:`test-results/login-polish/${info.project.name}-${width}.png`,fullPage:true});
 }
 await page.getByRole('button',{name:'Show password',exact:true}).click();
 await expect(page.locator('#current-password')).toHaveAttribute('type','text');await expect(page.locator('[data-eye-closed]')).toBeVisible();
 await page.getByRole('button',{name:'Hide password',exact:true}).click();await expect(page.locator('#current-password')).toHaveAttribute('type','password');
 await page.getByLabel('Remember me').check();await expect(page.getByLabel('Remember me')).toBeChecked();
 expect(errors).toEqual([]);
});
test('polished form retains successful sign-in',async({page})=>{
 await page.goto('/login?next=/projects/planning');
 await page.getByLabel('Email address').fill('admin@edify.org');await page.locator('#current-password').fill('edify');
 await page.getByRole('button',{name:'Access workspace',exact:true}).click();
 await expect(page).toHaveURL(/\/dashboard/);await expect(page.locator('main')).toBeVisible();
});
