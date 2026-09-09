const {test,expect}=require('@playwright/test');
const {signIn}=require('./helpers/auth');
test.use({video:'off',trace:'off'});
const runtimeErrors=new WeakMap();
test.beforeEach(async({page})=>{const errors=[];runtimeErrors.set(page,errors);page.on('pageerror',e=>errors.push(e.message));});
test.afterEach(async({page},info)=>{
 if(info.title.startsWith('empty-state')||info.title.startsWith('search survives'))expect(runtimeErrors.get(page)).toEqual([]);
});

test('empty-state icons and priority cards remain contained and actions open',async({page},info)=>{
 await signIn(page,'cceo@edify.org','edify',{acceptRequiredAgreements:false});
 for(const route of ['/projects?fy=2026','/my-targets?fy=2026','/debriefs?fy=2026']){
  await page.goto(route);
  const actions = route.startsWith('/my-targets') ? await page.locator('.priority-portfolio__items a').evaluateAll(es=>[...new Set(es.map(e=>e.getAttribute('href')))]) : [];
  for(const width of [390,768,1366]){
   await page.setViewportSize({width,height:900});
   for(const theme of ['theme-light','theme-dark dark','theme-blue dark']){
    await page.evaluate(t=>document.documentElement.className=t,theme);
    expect(await page.locator('.edify-empty-state__mark').evaluateAll(es=>es.map(e=>e.textContent.trim()).filter(Boolean))).toEqual([]);
    expect(await page.locator('.edify-badge').evaluateAll(es=>es.filter(e=>e.getBoundingClientRect().width&&e.scrollWidth>e.clientWidth+2).map(e=>e.textContent))).toEqual([]);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2)).toBe(true);
   }
   if(width===1366)await page.screenshot({path:info.outputPath(route.split('?')[0].slice(1)+'.png'),fullPage:true});
  }
  if(route.startsWith('/my-targets')){
   await page.locator('#myTargetTrend').scrollIntoViewIfNeeded();
   await expect(page.locator('#myTargetTrend .apexcharts-svg')).toBeVisible();
   await page.locator('[aria-labelledby=priority-portfolio-title]').screenshot({path:info.outputPath('priority-portfolio.png')});
   await expect(page.locator('.priority-portfolio__group')).toHaveCount(4);
   expect(actions.length).toBeGreaterThan(0);
   for(const group of await page.locator('.priority-portfolio__group').all()){
    const count=Number(await group.locator('.edify-badge').first().textContent());
    expect(await group.locator('.priority-portfolio__items > li').count()).toBe(count);
   }
   for(const url of actions){
    const response=await page.goto(url);expect(response.status(),url).toBeLessThan(400);
    await expect(page.locator('main')).toBeVisible();
   }
  }
 }
});

test('pending uploads works without external assets and preserves retry order',async({page,context},info)=>{
 await page.route('**/static/**',r=>r.abort());
 await page.goto('/offline');
 await expect(page.locator('[data-offline-title]')).toHaveText('Pending uploads');
 await expect(page.locator('[data-offline-title]')).toHaveCSS('font-size','20px');
 const requests=[];let available=false;
 await page.route(/\/activities\/anomaly-/,async route=>{
  requests.push(route.request().url());
  await route.fulfill({status:available?200:503,body:'Temporary failure'});
 });
 await page.evaluate(async()=>{
  const db=await new Promise((resolve,reject)=>{const r=indexedDB.open('edify-outbox',1);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)});
  await new Promise((resolve,reject)=>{
   const tx=db.transaction('requests','readwrite'),store=tx.objectStore('requests');
   for(let i=1;i<=3;i++)store.put({path:'/activities/anomaly-'+i+'/start/action',label:'Start activity',subject:'Offline fixture '+i,createdAt:Date.now(),fields:[],status:i===3?'attention':'queued',message:i===3?'Please review this entry':''});
   tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);
  });db.close();await EdifyFieldOutbox.refresh();
 });
 await expect(page.locator('[data-field-outbox-list] > li')).toHaveCount(3);
 await page.evaluate(()=>EdifyFieldOutbox.replay());expect(requests).toHaveLength(1);
 await expect(page.locator('[data-field-outbox-list] > li')).toHaveCount(3);
 available=true;
 await page.evaluate(()=>EdifyFieldOutbox.replay());
 expect(requests.map(u=>new URL(u).pathname)).toEqual(['/activities/anomaly-1/start/action','/activities/anomaly-1/start/action','/activities/anomaly-2/start/action']);
 await expect(page.locator('[data-field-outbox-list] > li')).toHaveCount(1);
 await page.getByRole('button',{name:'Discard',exact:true}).click();
 await expect(page.locator('[data-field-outbox-empty]')).toBeVisible();
 await context.setOffline(true);
 await expect(page.locator('[data-offline-title]')).toHaveText('You are offline');
 await context.setOffline(false);
 await expect(page.locator('[data-offline-title]')).toHaveText('Pending uploads');
 await page.setViewportSize({width:390,height:844});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:info.outputPath('pending-uploads-no-assets.png')});
});

test('installed fallback retains its layout and local queue when navigation fails',async({page,context,browserName})=>{
 test.skip(browserName!=='chromium','Service-worker navigation is exercised in Chromium.');
 await page.goto('/offline');
 await page.evaluate(async()=>{await navigator.serviceWorker.register('/sw.js');await navigator.serviceWorker.ready;});
 await page.waitForFunction(()=>navigator.serviceWorker.controller);
 await context.setOffline(true);
 await page.goto('/debriefs?offline-probe=1');
 await expect(page.locator('[data-offline-title]')).toHaveText('You are offline');
 expect(await page.locator('[data-offline-title]').evaluate(el=>parseFloat(getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(16);
 expect(await page.evaluate(()=>typeof EdifyFieldOutbox.refresh)).toBe('function');
 await expect(page.locator('[data-field-outbox-empty]')).toBeVisible();
 await context.setOffline(false);
 await page.getByRole('button',{name:'Retry',exact:true}).click();
 await expect(page.locator('[data-offline-page]')).toHaveCount(0);
});

test('search survives filter changes and debrief advanced controls remain usable',async({page})=>{
 await signIn(page,'cceo@edify.org','edify',{acceptRequiredAgreements:false});
 await page.setViewportSize({width:1366,height:900});
 for(const route of ['/debriefs','/projects/planning','/planning','/clusters']){
  await page.goto(route);
  const search=page.locator('.edify-topbar__search input[type=search]');
  const linked=await search.evaluate(input=>{
   const owner=input.closest('form[hx-include]');
   return owner?.getAttribute('hx-include')?.split(',').map(s=>s.trim()).find(s=>document.querySelector(s)?.tagName==='FORM')||null;
  });
  expect(linked,route).toBeTruthy();
  await search.fill('anomaly-query');
  await search.press('Enter');
  await expect(page).toHaveURL(/q=anomaly-query/);
  await page.waitForFunction(()=>!document.querySelector('.htmx-request'));
  const filter=page.locator(linked+' select:visible:not([name=fy])').first();
  const value=await filter.evaluate(e=>[...e.options].find(o=>o.value!==e.value&&!o.disabled)?.value);
  expect(value,route).toBeDefined();
  const name=await filter.getAttribute('name');
  await Promise.all([page.waitForResponse(r=>r.request().method()==='GET'&&new URL(r.url()).pathname===new URL(page.url()).pathname&&new URL(r.url()).searchParams.get(name)===value),filter.selectOption(value)]);
  await page.waitForFunction(()=>!document.querySelector('.htmx-request'));
  expect(new URL(page.url()).searchParams.get('q'),route).toBe('anomaly-query');
  await expect(search).toHaveValue('anomaly-query');
 }
 await page.goto('/debriefs');
 await page.getByRole('button',{name:'More filters',exact:true}).click();
 await expect(page.locator('dialog[open]')).toBeVisible();
 await page.getByLabel('Risk level',{exact:true}).selectOption('critical');
 await page.getByRole('button',{name:'Apply filters',exact:true}).click();
 await expect(page.locator('dialog[open]')).toHaveCount(0);
 await expect(page).toHaveURL(/risk_level=critical/);
 await page.getByRole('link',{name:'New Field Debrief',exact:true}).click();
 await expect(page.locator('textarea[name=what_went_well]')).toBeVisible();
});

test.describe('Cross-tab replay',()=>{
 test.use({serviceWorkers:'block'});
 test('two tabs send each saved action only once',async({page,context})=>{
 await context.addInitScript(()=>Object.defineProperty(navigator,'onLine',{configurable:true,get:()=>false}));
 await page.goto('/offline');
 const other=await context.newPage();await other.goto('/offline');
 let release;
 const held=new Promise(resolve=>{release=resolve});
 let sends=0;
 await context.route(/\/activities\/anomaly-concurrency\//,async route=>{
  sends++;await held;await route.fulfill({status:200,body:'Saved'});
 });
 await page.evaluate(async()=>{
  const db=await new Promise(resolve=>{const r=indexedDB.open('edify-outbox',1);r.onsuccess=()=>resolve(r.result)});
  await new Promise(resolve=>{const tx=db.transaction('requests','readwrite');tx.objectStore('requests').put({path:'/activities/anomaly-concurrency/start/action',label:'Start',subject:'Concurrency fixture',createdAt:Date.now(),fields:[],status:'queued'});tx.oncomplete=resolve});db.close();
 });
 for(const tab of [page,other])await tab.evaluate(()=>Object.defineProperty(navigator,'onLine',{configurable:true,get:()=>true}));
 const first=page.evaluate(()=>EdifyFieldOutbox.replay());
 await expect.poll(()=>sends).toBe(1);
 const second=other.evaluate(()=>EdifyFieldOutbox.replay());
 try{
  await expect.poll(()=>other.evaluate(()=>navigator.locks.query().then(state=>state.pending.some(lock=>lock.name==='edify-field-outbox-replay')))).toBe(true);
  expect(sends).toBe(1);
 }finally{release();await Promise.all([first,second]);}
 expect(sends).toBe(1);
 for(const tab of [page,other])await expect(tab.locator('[data-field-outbox-empty]')).toBeVisible();
 await other.close();
});

});
