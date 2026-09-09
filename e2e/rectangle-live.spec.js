const {test,expect}=require('@playwright/test');
const {signIn}=require('./helpers/auth');
const fs=require('fs'),path=require('path');
const roles=[['CCEO','cceo',['/dashboard','/planning','/schools','/core-schools','/clusters']],['Program Lead','pl1',['/dashboard','/team-planning-oversight/']],['Country Director','cd',['/dashboard','/budget']],['RVP','rvp',['/dashboard']],['ImpactAssessment','ia',['/ia/dashboard/']],['Accountant','accountant',['/accounts','/accounts/partner-payments/']],['HumanResources','hr',['/dashboard','/personal-time-off/','/leave/approvals/','/hr-today']],['ProjectCoordinator','coordinator',['/dashboard','/projects']],['PartnerAdmin','partner-admin',['/partner/today']],['PartnerFieldOfficer','partner',['/partner/today']],['BusinessTransformationOfficer','business-transformation',['/dashboard']],['MfiPartnerAdmin','mfi-admin',['/dashboard']],['MfiLoanOfficer','mfi-officer',['/dashboard']],['Admin','admin',['/dashboard','/team-targets','/analytics','/hr-today','/leave/approvals/','/admin-panel/users','/staff','/partners','/projects','/loans']]];
test.use({video:'off',trace:'off',serviceWorkers:'block'});
for(const [role,user,routes] of roles)test('populated landscape pages: '+role,async({page})=>{
 test.setTimeout(240000);const results=[];
 const visitRoutes=process.env.RECTANGLE_LIVE_ROUTES ? process.env.RECTANGLE_LIVE_ROUTES.split(',') : [...routes];
 await signIn(page,user+'@edify.org','edify',{acceptRequiredAgreements:false});
 for(let routeIndex=0;routeIndex<visitRoutes.length;routeIndex++){
  const url=visitRoutes[routeIndex];
  const response=await page.goto(url);expect(response.status(),url).toBeLessThan(400);
  expect(new URL(page.url()).pathname,url).not.toMatch(/^\/(?:admin\/login|login|documents|policy-agreement)(?:\/|$)/);
  await expect(page.locator('main')).toBeVisible();
  if(['/schools','/clusters','/projects','/partners','/staff','/loans'].includes(url)){
   const detail=await page.locator('main a[href]').evaluateAll(links=>links.map(a=>a.getAttribute('href')).find(h=>/^\/(schools|clusters|projects|partners|staff|loans)\/(?:[0-9]+|c[a-z0-9]{8,})\/?$/.test(h)));
   if(detail&&!visitRoutes.includes(detail))visitRoutes.push(detail);
  }
  for(const [width,height] of (['/team-targets','/hr-today','/leave/approvals/','/analytics'].includes(url) ? [[390,844],[768,1024],[1280,720],[1920,1080]] : [[1280,720],[1920,1080]])){
   await page.setViewportSize({width,height});
   await page.waitForFunction(()=>[...document.querySelectorAll('.apexcharts-canvas')].every(e=>e.getBoundingClientRect().width<=e.parentElement.getBoundingClientRect().width+2),null,{timeout:2000}).catch(()=>{});
   for(const theme of ['light','dark','theme-blue']){
   await page.evaluate(t=>{const root=document.documentElement;root.classList.remove('light','dark','theme-dark','theme-blue');root.classList.add(t==='light'?'light':'dark');if(t!=='light')root.classList.add(t==='dark'?'theme-dark':'theme-blue');root.dataset.theme=t==='theme-blue'?'blue':t},theme);
   const data=await page.evaluate(()=>({url:location.pathname,width:innerWidth,height:innerHeight,pageWidth:document.documentElement.scrollWidth,workspaceOverflow:document.querySelector('main').scrollWidth-document.querySelector('main').clientWidth,title:document.querySelector('h1')?.textContent?.trim(),tables:document.querySelectorAll('table').length,firstTableTop:Math.round(document.querySelector('main table')?.getBoundingClientRect().top||0),emptyQueueHeights:[...document.querySelectorAll('.hr-today-queue--empty')].map(e=>Math.round(e.getBoundingClientRect().height)),leaveQueueHeight:Math.round(document.querySelector('.leave-approval-queue')?.getBoundingClientRect().height||0)}));
   data.theme=theme;results.push(data);expect(data.pageWidth,url).toBeLessThanOrEqual(width+2);expect(data.workspaceOverflow,url).toBeLessThanOrEqual(2);
   if(url==='/team-targets'){
    const filter=page.getByRole('button',{name:'High risk',exact:true});
    await filter.click();await expect(filter).toHaveAttribute('aria-pressed','true');
    const r=await filter.boundingBox();expect(r.x+r.width).toBeLessThanOrEqual(width);
   }
   if(url==='/hr-today')for(const card of await page.locator('.hr-today-queue--empty').all())expect((await card.boundingBox()).height).toBeLessThan(85);
   if(width===1280 && theme==='light')await page.screenshot({path:path.join('test-results/rectangle-live',user+'-'+url.replaceAll('/','_')+'.png')});
   }
  }
 }
 fs.mkdirSync('test-results/rectangle-live',{recursive:true});fs.writeFileSync('test-results/rectangle-live/'+user+(process.env.RECTANGLE_LIVE_ROUTES?'-focused':'')+'.json',JSON.stringify(results,null,2));
});
