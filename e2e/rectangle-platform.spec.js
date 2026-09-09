const {test,expect}=require('@playwright/test');
const {snapshotServer}=require('./helpers/snapshot-server');
const fs=require('fs'),path=require('path');
const root=path.resolve(__dirname,'..'),dir=path.join(root,'test-results/kpi-platform-crawl');
const output=path.join(root,'test-results/rectangle-audit');fs.mkdirSync(output,{recursive:true});
const roles=fs.existsSync(dir)?fs.readdirSync(dir).filter(f=>f.endsWith('.json')).map(f=>f.slice(0,-5)):[];
test.use({video:'off',trace:'off',serviceWorkers:'block'});
for(const role of roles)test('rectangular desktop layouts: '+role,async({page})=>{
 const records=JSON.parse(fs.readFileSync(path.join(dir,role+'.json'),'utf8')).filter(r=>r.status===200);
 const canonical=new Map();
 for(const record of records){
  const file=(role+'-'+record.url).replace(/[^a-zA-Z0-9_-]/g,'_')+'.html';
  if(fs.existsSync(path.join(dir,file))&&!canonical.has(record.url.replace(/\/$/,'')))canonical.set(record.url.replace(/\/$/,''),file);
 }
 const files=[...canonical.values()];
 const aliases=records.filter(r=>fs.existsSync(path.join(dir,(role+'-'+r.url).replace(/[^a-zA-Z0-9_-]/g,'_')+'.html'))).length-files.length;
 test.setTimeout(Math.max(240000,files.length*12000));
 const server=await snapshotServer(root);const issues=[],observations=[];let checks=0,completed=0;
 try{
  for(const file of files){
   server.setHtml(fs.readFileSync(path.join(dir,file),'utf8'));
   await page.goto(server.origin+'/page',{waitUntil:'domcontentloaded'});
   await page.addStyleTag({content:'*,*::before,*::after{transition:none!important;animation:none!important}'});
   for(const [width,height] of [[1280,720],[1366,768],[1920,1080]]){
    await page.setViewportSize({width,height});
    // Chart engines redraw asynchronously after resizing. Judge the settled
    // layout, while still reporting any persistent overflow.
    await page.waitForFunction(()=>[...document.querySelectorAll('.apexcharts-canvas')].every(e=>e.getBoundingClientRect().width<=e.parentElement.getBoundingClientRect().width+2),null,{timeout:2000}).catch(()=>{});
    for(const theme of (process.env.RECTANGLE_ALL_THEMES ? ['light','dark','theme-blue'] : ['light'])){
     await page.evaluate(t=>{const root=document.documentElement;root.classList.remove('light','dark','theme-light','theme-dark','theme-blue');root.classList.add(t==='light'?'light':'dark');if(t!=='light')root.classList.add(t==='dark'?'theme-dark':'theme-blue');root.dataset.theme=t==='theme-blue'?'blue':t},theme);
     const result=await page.evaluate(()=>{
      const errors=[],notes=[];const main=document.querySelector('main');
      if(document.documentElement.scrollWidth>innerWidth+2)errors.push('document overflow '+document.documentElement.scrollWidth+'/'+innerWidth);
      if(!main)return {errors,notes};
      if(main.scrollWidth>main.clientWidth+2)errors.push('workspace overflow '+main.scrollWidth+'/'+main.clientWidth);
      const visible=e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&getComputedStyle(e).visibility!=='hidden'&&!e.closest('[inert]')};
      const name=e=>(e.getAttribute('aria-label')||e.textContent||e.getAttribute('name')||e.className).trim().replace(/\s+/g,' ').slice(0,90);
      for(const e of main.querySelectorAll('.context-metrics__sentence,.platform-filter-bar,.edify-page-header,[role="tablist"]')){
       if(!visible(e))continue;const r=e.getBoundingClientRect();
       if(r.left< -2||r.right>innerWidth+2)errors.push('outside workspace: '+name(e));
      }
      for(const field of main.querySelectorAll('.edify-filter-field')){
       if(!visible(field))continue;const r=field.getBoundingClientRect();
       for(const c of field.querySelectorAll('input:not([type=hidden]),select')){
        if(!visible(c))continue;const b=c.getBoundingClientRect();if(b.left<r.left-2||b.right>r.right+2)errors.push('filter escapes field: '+(c.name||name(c)));
       }
      }
      for(const e of main.querySelectorAll('button, input:not([type=hidden]), select, a.btn')){
       if(!visible(e)||e.closest('table,[role="menu"],.row-menu,[popover],[role="tablist"]'))continue;
       const r=e.getBoundingClientRect();if(r.bottom<0||r.top>innerHeight)continue;
       let parent=e.parentElement;
       while(parent&&parent!==main){
        const s=getComputedStyle(parent),b=parent.getBoundingClientRect();
        if((s.overflowX==='hidden'||s.overflowX==='clip')&&(r.left<b.left-2||r.right>b.right+2)){errors.push('clipped control: '+name(e));break;}
        parent=parent.parentElement;
       }
      }
      const first=Array.from(main.querySelectorAll('table,.school-record-row,.cluster-card,canvas,.sr-map-viewport')).find(visible);
      if(first&&first.getBoundingClientRect().top>innerHeight*.9)notes.push('primary content starts below first screen: '+Math.round(first.getBoundingClientRect().top));
      return {errors:[...new Set(errors)],notes};
     });
     checks++;if(result.errors.length)issues.push({file,width,height,theme,errors:result.errors});
     if(theme==='light'&&result.notes.length)observations.push({file,width,height,notes:result.notes});
     if(theme==='light'&&width===1280&&(result.notes.length||result.errors.length))await page.screenshot({path:path.join(output,file+'.png')});
    }
   }
   completed++;
   fs.writeFileSync(path.join(output,role+'.json'),JSON.stringify({role,pages:files.length,aliases,completed,checks,issues,observations},null,2));
  }
  expect(issues).toEqual([]);
 }finally{await server.close()}
});
