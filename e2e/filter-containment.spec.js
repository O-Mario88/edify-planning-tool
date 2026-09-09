const {test,expect}=require('@playwright/test');
const {snapshotServer}=require('./helpers/snapshot-server');
const fs=require('node:fs'),path=require('node:path');
const root=path.resolve(__dirname,'..'),directory=path.join(root,'test-results/kpi-platform-crawl');
test.use({video:'off',trace:'off',serviceWorkers:'block'});
test('filter controls stay inside their fields and never overlap',async({page},info)=>{
 test.setTimeout(240000);
 test.skip(!fs.existsSync(directory), 'Requires test-results/kpi-platform-crawl');
 const files=fs.existsSync(directory)?fs.readdirSync(directory).filter(f=>f.endsWith('.html')&&/^(Admin|CCEO|Accountant|ProjectCoordinator)-/.test(f)&&/(planning|schools|analytics|projects|accounts|budget|clusters|partner|debrief|training|visits)/.test(f)):[];
 const server=await snapshotServer(root),issues=[];let checks=0;
 try{
 for(const file of files){
  server.setHtml(fs.readFileSync(path.join(directory,file),'utf8'));
  await page.goto(server.origin+'/page',{waitUntil:'domcontentloaded'});
  for(const width of [390,768,1048,1290,1600]){
   await page.setViewportSize({width,height:900});
   const failures=await page.evaluate(()=>{
    const errors=[],visible=e=>e.getBoundingClientRect().width>0&&e.getBoundingClientRect().height>0;
    const fields=[...document.querySelectorAll('main .edify-filter-field')].filter(visible);
    for(const field of fields){
     const b=field.getBoundingClientRect();
     for(const control of field.querySelectorAll(':scope > select,:scope > input:not([type=hidden])')){
      if(!visible(control))continue;const r=control.getBoundingClientRect();
      if(r.left<b.left-1||r.right>b.right+1)errors.push('control escapes field: '+(control.name||control.id));
     }
     for(const next of fields){
      if(next===field||next.parentElement!==field.parentElement)continue;
      const r=next.getBoundingClientRect();
      if(Math.min(b.right,r.right)-Math.max(b.left,r.left)>1&&Math.min(b.bottom,r.bottom)-Math.max(b.top,r.top)>1)errors.push('overlapping fields');
     }
    }
    return [...new Set(errors)];
   });
   checks++;if(failures.length)issues.push({file,width,failures});
  }
 }
 await info.attach('filter-coverage',{body:JSON.stringify({pages:files.length,checks,issues},null,2),contentType:'application/json'});
 expect(files.length).toBeGreaterThan(20);expect(issues).toEqual([]);
 }finally{await server.close()}
});

test('Planning filters retain gaps through resizing and HTMX changes',async({page},info)=>{
 const {signIn}=require('./helpers/auth');
 await signIn(page,'accountant@edify.org','edify',{acceptRequiredAgreements:false});
 await page.goto('/planning');
 const form=page.locator('#filters-form');
 await expect(form.locator('.edify-filter-field')).toHaveCount(6);
 for(const width of [390,768,1048,1290,1600]){
  await page.setViewportSize({width,height:900});
  for(const theme of ['theme-light','theme-dark','theme-blue']){
   await page.evaluate(t=>{document.documentElement.classList.remove('theme-light','theme-dark','theme-blue');document.documentElement.classList.add(t);document.documentElement.classList.toggle('dark',t!=='theme-light')},theme);
   const boxes=await form.locator('select').evaluateAll(es=>es.map(e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom}}));
   for(let i=0;i<boxes.length;i++)for(let j=i+1;j<boxes.length;j++){
    const a=boxes[i],b=boxes[j];
    if(Math.min(a.bottom,b.bottom)-Math.max(a.top,b.top)>1)expect(Math.max(b.left-a.right,a.left-b.right)).toBeGreaterThanOrEqual(8);
   }
   expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  }
 }
 await form.locator('[name=quarter]').selectOption('Q2');
 await expect(page).toHaveURL(/quarter=Q2/);
 await expect(form.locator('[name=quarter]')).toHaveValue('Q2');
 await expect(page.locator('#schools-table-container')).toBeVisible();
 await page.screenshot({path:info.outputPath('planning-filters.png')});
});
