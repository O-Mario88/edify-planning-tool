const {test,expect}=require('@playwright/test');
const {signIn}=require('./helpers/auth');
test('outlined drawer fields and reference trend render on desktop and mobile',async({page})=>{
 test.setTimeout(180000);
 await signIn(page,'pl1@edify.org','edify',{acceptRequiredAgreements:false});
 await page.goto('/debriefs');
 const response=await page.request.get('/analytics/schedule-report');
 expect(response.ok()).toBeTruthy();
 await page.evaluate(html=>{const host=document.getElementById('drawer-container');const parsed=new DOMParser().parseFromString(html,'text/html');const root=parsed.body.firstElementChild;root.querySelector('.drawer-body').innerHTML='<form class="space-y-5"><div><label for="ref-name">Full name <span class="text-red-600">*</span></label><input id="ref-name" type="text" class="w-full px-3 mt-2" placeholder="Enter full name"></div><div><label for="ref-address">Address</label><textarea id="ref-address" class="w-full mt-2" placeholder="Enter address"></textarea></div></form>';host.replaceChildren(root);window.htmx.process(host);},await response.text());
 const field=page.locator('#drawer-container input:not([type=hidden]):not([type=checkbox]):not([type=radio]), #drawer-container select').first();
 await expect(field).toBeVisible();
 expect(await field.evaluate(el=>getComputedStyle(el).borderRadius)).toBe('9px');
 await field.focus();
 expect(await field.evaluate(el=>getComputedStyle(el).outlineStyle)).toBe('solid');
 await page.screenshot({path:'test-results/refined-drawer-desktop.png'});
 await page.setViewportSize({width:390,height:844});
 expect(await field.evaluate(el=>getComputedStyle(el).fontSize)).toBe('16px');
 await page.screenshot({path:'test-results/refined-drawer-mobile.png'});
 await page.evaluate(()=>{
  document.getElementById('drawer-container').replaceChildren();
  const host=document.createElement('div');host.id='reference-trend';host.style.cssText='position:fixed;inset:80px 10px auto;background:white;z-index:99999;padding:12px';document.body.append(host);
  const panel=window.EdifyBarStandard.panels({chart:{type:'line'},series:[{name:'Current',data:[5,15,21,16]},{name:'Previous',data:[2,23,15,22]}],labels:['Apr','May','Jun','Jul']})[0];
  new ApexCharts(host,window.EdifyBarStandard.options(panel)).render();
 });
 await expect(page.locator('#reference-trend .apexcharts-area-series')).toBeVisible();
 await page.screenshot({path:'test-results/refined-trend-mobile.png'});
});
