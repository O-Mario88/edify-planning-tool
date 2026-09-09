const {test,expect}=require('@playwright/test');
const {snapshotServer}=require('./helpers/snapshot-server');
const {signIn}=require('./helpers/auth');
const fs=require('fs'),path=require('path');
test.use({video:'off',trace:'off',serviceWorkers:'block'});
test('plain table content across rendered platform pages',async({page},info)=>{
 test.setTimeout(240000);
 const root=path.resolve(__dirname,'..'),dir=path.join(root,'test-results/kpi-platform-crawl');
 test.skip(!fs.existsSync(dir), 'Requires test-results/kpi-platform-crawl');
 const files=fs.existsSync(dir)?fs.readdirSync(dir).filter(f=>/^Admin-.*\.html$/.test(f)):[];
 const server=await snapshotServer(root),issues=[];let checked=0;
 try{for(const file of files){
  const html=fs.readFileSync(path.join(dir,file),'utf8');if(!html.includes('<table'))continue;
  server.setHtml(html);await page.goto(server.origin+'/page',{waitUntil:'domcontentloaded'});
  await page.addStyleTag({content:'*,*::before,*::after{transition:none!important;animation:none!important}'});
  for(const width of [390,1290]){
   await page.setViewportSize({width,height:900});
   for(const theme of ['theme-light','theme-dark','theme-blue']){
    await page.evaluate(t=>{document.documentElement.classList.remove('theme-light','theme-dark','theme-blue');document.documentElement.classList.add(t);document.documentElement.classList.toggle('dark',t!=='theme-light')},theme);
    const errors=await page.evaluate(()=>{
     const errors=[];
     for(const e of document.querySelectorAll('.edify-table-plain-content')){
      if(!e.getBoundingClientRect().width||!e.getBoundingClientRect().height)continue;
      const s=getComputedStyle(e);
      if([s.borderTopWidth,s.borderRightWidth,s.borderBottomWidth,s.borderLeftWidth].some(v=>parseFloat(v)>0)||s.backgroundColor!=='rgba(0, 0, 0, 0)'||s.backgroundImage!=='none'||s.boxShadow!=='none')errors.push(e.tagName+' '+e.className+' '+s.border+' '+s.backgroundColor);
     }
     return [...new Set(errors)].slice(0,8);
    });checked++;if(errors.length)issues.push({file,width,theme,errors});
   }
  }
 }
 await info.attach('plain-table-coverage',{body:JSON.stringify({checked,issues},null,2),contentType:'application/json'});
 expect(checked).toBeGreaterThan(100);expect(issues).toEqual([]);
 }finally{await server.close()}
});
test('finance queues and coloured approval status',async({page})=>{
 await signIn(page,'accountant@edify.org','edify',{acceptRequiredAgreements:false});
 await page.goto('/accounts/partner-payments/');
 await expect(page.getByRole('heading',{name:'Transport Provider Payments',exact:true})).toHaveCount(0);
 await page.goto('/accounts/approval-history/');
 for(const width of [390,768,1290]){
  await page.setViewportSize({width,height:900});
  for(const theme of ['theme-light','theme-dark','theme-blue']){
   await page.evaluate(t=>{document.documentElement.classList.remove('theme-light','theme-dark','theme-blue');document.documentElement.classList.add(t);document.documentElement.classList.toggle('dark',t!=='theme-light')},theme);
   const status=page.locator('.edify-table-status').first();
   await expect(status).toHaveCSS('background-color','rgba(0, 0, 0, 0)');
   await expect(status).toHaveCSS('border-top-width','0px');
   expect(await status.evaluate(e=>getComputedStyle(e).color)).not.toBe('rgb(0, 0, 0)');
   const action=page.getByRole('link',{name:'Review Request',exact:true}).first();
   await expect(action).toBeVisible();
   expect(await action.evaluate(e=>parseFloat(getComputedStyle(e).borderTopWidth))).toBeGreaterThan(0);
  }
 }
});
test('inserted table content stays plain while buttons and focus remain usable',async({page})=>{
 const root=path.resolve(__dirname,'..'),server=await snapshotServer(root);
 try{
  server.setHtml('<!doctype html><html class="theme-light"><head><link rel="stylesheet" href="/static/css/design-system.css"><link rel="stylesheet" href="/static/css/components.css"><link rel="stylesheet" href="/static/css/consistency.css"><script defer src="/static/js/micro-ux.js"></script></head><body><main id="main-content"><table><tbody id="rows"><tr><td>Initial</td></tr></tbody></table></main></body></html>');
  await page.goto(server.origin+'/page');
  await expect(page.locator('table')).toHaveClass(/edify-plain-table/);
  await page.evaluate(()=>{
   const body=document.querySelector('tbody');
   body.innerHTML='<tr><td><span class="bg-rose-50 border rounded-pill">Returned</span><time style="border:1px solid red;background:red">Today</time><code style="border:1px solid red;background:red">ID-1</code><input aria-label="Reference" value="REF-1" style="border:1px solid red;background:red"><button type="button" class="btn" style="border:1px solid blue;background:blue;color:white"><span>Review</span></button></td></tr>';
   body.dispatchEvent(new CustomEvent('htmx:afterSettle',{bubbles:true}));
  });
  for(const selector of ['span.bg-rose-50','time','code','input']){
   const item=page.locator(selector);await expect(item).toHaveClass(/edify-table-plain-content/);
   await expect(item).toHaveCSS('border-top-width','0px');
   await expect(item).toHaveCSS('background-color','rgba(0, 0, 0, 0)');
  }
  await expect(page.getByRole('button',{name:'Review'})).toHaveCSS('border-top-width','1px');
  await expect(page.locator('button span')).not.toHaveClass(/edify-table-plain-content/);
  await page.getByRole('textbox',{name:'Reference'}).focus();
  await expect(page.getByRole('textbox',{name:'Reference'})).toHaveCSS('outline-width','2px');
 }finally{await server.close()}
});
