const {test,expect}=require('@playwright/test');
const {signIn}=require('./helpers/auth');
const fs=require('fs');
test.use({video:'off',trace:'off',serviceWorkers:'block'});
test('project workspaces remain compact and usable across screens and themes',async({page})=>{
 test.setTimeout(180000);
 await signIn(page,'admin@edify.org','edify',{acceptRequiredAgreements:false});
 const routes=['/projects/planning','/projects/my-plan','/projects/analytics','/projects'];
 const results=[];
 for(let i=0;i<routes.length;i++){
  const route=routes[i];await page.goto(route);
  await page.addStyleTag({content:'*,*::before,*::after{transition:none!important;animation:none!important}'});
  if(route==='/projects'){
   const detail=await page.locator('main a[href]').evaluateAll(es=>es.map(e=>e.getAttribute('href')).find(h=>/^\/projects\/(?:\d+|c[a-z0-9]{8,})\/?$/.test(h)));
   if(detail)routes.push(detail);
  }
  for(const [width,height] of [[390,844],[768,1024],[1280,720],[1366,768],[1920,1080]]){
   await page.setViewportSize({width,height});
   for(const theme of ['light','dark','blue']){
    await page.evaluate(t=>{const r=document.documentElement;r.classList.remove('light','dark','theme-dark','theme-blue');r.classList.add(t==='light'?'light':'dark');if(t!=='light')r.classList.add('theme-'+t);r.dataset.theme=t},theme);
    await expect.poll(()=>page.evaluate(()=>document.querySelector('main').scrollWidth-document.querySelector('main').clientWidth)).toBeLessThanOrEqual(2);
    const measure=await page.evaluate(()=>({pageWidth:document.documentElement.scrollWidth,firstTable:document.querySelector('main table')?.getBoundingClientRect().top,filters:[...document.querySelectorAll('main form[id$="filters"]')].map(e=>({id:e.id,height:e.getBoundingClientRect().height}))}));
    expect(measure.pageWidth,route).toBeLessThanOrEqual(width+2);
    if(width===1366 && route==='/projects/planning')expect(measure.firstTable).toBeLessThan(620);
    if(width===1366 && route==='/projects/my-plan')expect(measure.filters[0].height).toBeLessThan(100);
    results.push({route,width,height,theme,...measure});
    if(theme==='light'&&[390,768,1366].includes(width))await page.screenshot({path:`test-results/project-layout/${route.replaceAll('/','_')}-${width}.png`});
    if(width===1366&&theme!=='light')await page.screenshot({path:`test-results/project-layout/${route.replaceAll('/','_')}-${width}-${theme}.png`});
   }
  }
 }
 fs.mkdirSync('test-results/project-layout',{recursive:true});fs.writeFileSync('test-results/project-layout/coverage.json',JSON.stringify(results,null,2));
});
test('project filters, queue tabs, and closed action menus survive interaction',async({page})=>{
 await page.setViewportSize({width:1366,height:768});
 await signIn(page,'admin@edify.org','edify',{acceptRequiredAgreements:false});
 await page.goto('/projects');
 const menu=page.locator('.row-menu').first();await expect(menu).toBeHidden();
 await page.getByRole('button',{name:'Project actions',exact:true}).first().click();await expect(menu).toBeVisible();
 await page.getByRole('heading',{name:'Projects',exact:true}).first().click();await expect(menu).toBeHidden();
 const detail=await page.locator('.row-menu a').first().getAttribute('href');await page.goto(detail);
 for(const id of ['assign-project-staff-title','add-project-school-title']){const panel=page.locator('details[aria-labelledby="'+id+'"]');await expect(panel.locator('form')).toBeHidden();await panel.locator('summary').first().click();await expect(panel.locator('form')).toBeVisible();}
 await page.goto('/projects/planning');
 await page.locator('.spp-readiness summary').click();await expect(page.locator('.spp-band').first()).toBeVisible();
 await page.locator('.spp-more-filters summary').click();await expect(page.locator('.spp-more-filters')).toHaveAttribute('open','');
 const project=page.locator('#spp-filters select[name="project"]');
 const value=await project.locator('option').nth(1).getAttribute('value');
 await project.selectOption(value);await expect(page).toHaveURL(new RegExp('project='+value));
 await page.getByRole('button',{name:/Ready for Support/}).click();await expect(page).toHaveURL(/tab=ready/);
 await expect(page.locator('#spp-filters select[name="project"]')).toHaveValue(value);
 await page.goto('/projects/my-plan');
 if(await page.locator('.sp-more-filters').count()){await page.locator('.sp-more-filters summary').click();await expect(page.locator('.sp-more-filters')).toHaveAttribute('open','');}
 await page.getByRole('tab',{name:'Month',exact:true}).click();await expect(page).toHaveURL(/period=month/);
 await expect(page.locator('#sp-plan-filters')).toBeVisible();
 await page.getByRole('button',{name:'Filters',exact:true}).click();await expect(page.locator('#sp-plan-filters')).toBeHidden();
 await page.getByRole('button',{name:'Filters',exact:true}).click();await expect(page.locator('#sp-plan-filters')).toBeVisible();
});
test('overfull tables preserve action widths instead of forcing an impossible fit',async({page})=>{
 const {snapshotServer}=require('./helpers/snapshot-server');
 const server=await snapshotServer(process.cwd());
 try{
  server.setHtml(`<!doctype html><html class="light"><head><link rel="stylesheet" href="/static/css/design-system.css"><link rel="stylesheet" href="/static/css/components.css"><link rel="stylesheet" href="/static/css/consistency.css"><script defer src="/static/js/micro-ux.js"></script></head><body><main><div style="width:180px;overflow:auto"><table style="min-width:700px"><thead><tr><th>First</th><th>Second</th><th>Third</th></tr></thead><tbody><tr><td><button style="min-width:150px">Review request</button></td><td><button style="min-width:150px">Open assignment</button></td><td><button style="min-width:150px">View payment</button></td></tr></tbody></table></div></main></body></html>`);
  await page.setViewportSize({width:1366,height:768});await page.goto(server.origin+'/page');
  await expect(page.locator('table')).toHaveAttribute('data-edify-table-ready','true');
  await expect(page.locator('table')).not.toHaveClass(/edify-table--truncate/);
  const boxes=await page.locator('tbody button').evaluateAll(es=>es.map(e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,width:r.width}}));
  for(let i=1;i<boxes.length;i++)expect(boxes[i].left).toBeGreaterThanOrEqual(boxes[i-1].right);
  expect(await page.locator('.edify-table-scroll-region').evaluate(e=>e.scrollWidth>e.clientWidth)).toBe(true);
 }finally{await server.close()}
});
