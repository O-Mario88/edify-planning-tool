const { test, expect } = require('@playwright/test');
const {snapshotServer}=require('./helpers/snapshot-server');
const fs=require('node:fs'), path=require('node:path');
const root=path.resolve(__dirname,'..'), directory=path.join(root,'test-results/kpi-platform-crawl');
const pagePattern=new RegExp(process.env.CALM_PAGE_PATTERN||'.*');
const coverageDir=path.join(root,'test-results/calm-coverage',process.env.CALM_AUDIT_RUN||'all');
const roles=fs.readdirSync(directory).filter(f=>f.endsWith('.json')).map(f=>f.slice(0,-5));
test.use({video:'off',trace:'off',serviceWorkers:'block'});test.describe.configure({mode:'parallel'});
for(const role of roles)test(`all rendered pages: ${role}`,async({page},info)=>{
 const files=fs.readdirSync(directory).filter(f=>f.startsWith(role+'-')&&f.endsWith('.html')&&pagePattern.test(f));
 test.setTimeout(Math.max(240000,files.length*18000));let html;const issues=[];
 const server=await snapshotServer(root);
 try {
 let completed=0;
 for(const file of files){
  html=fs.readFileSync(path.join(directory,file),'utf8');
  server.setHtml(html);
  await page.goto(server.origin+'/page',{waitUntil:'domcontentloaded'});
  await page.addStyleTag({content:'*,*::before,*::after{transition:none!important;animation:none!important}'});
  for(const width of [390,768,1600]){
   await page.setViewportSize({width,height:900});
   for(const theme of ['theme-light','theme-dark','theme-blue']){
    await page.evaluate(t=>{document.documentElement.classList.remove('theme-light','theme-dark','theme-blue');document.documentElement.classList.add(t);document.documentElement.classList.toggle('dark',t!=='theme-light')},theme);
    const failures=await page.evaluate(()=>{
      const errors=[], main=document.querySelector('main');
      if(document.documentElement.scrollWidth>innerWidth+2)errors.push('page overflow: '+document.documentElement.scrollWidth);
      if(!main)return errors;
      const visible=e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&getComputedStyle(e).visibility!=='hidden'};
      for(const el of main.querySelectorAll('h1,h2,h3,td,button,p')){
        if(!visible(el)||!el.textContent.trim())continue;
        const s=getComputedStyle(el);
        if(!s.fontFamily.includes('Geist'))errors.push('font '+s.fontFamily+' on '+el.tagName);
        if(parseFloat(s.fontSize)<12)errors.push('text below floor '+s.fontSize+' '+el.textContent.trim().slice(0,30));
      }
      for(const el of main.querySelectorAll('.context-metrics__sentence')){
        if(!visible(el))continue;const r=el.getBoundingClientRect();if(r.right>innerWidth+2||r.left< -2)errors.push('KPI outside viewport');
      }
      if(main.classList.contains('edify-workspace')&&!main.hasAttribute('data-workspace-design'))errors.push('missing shared workspace contract');
      return [...new Set(errors)];
    });
    if(failures.length)issues.push({file,width,theme,failures});
   }
  }
  completed++;
  if(completed%10===0){
   fs.mkdirSync(coverageDir,{recursive:true});
   fs.writeFileSync(path.join(coverageDir,role+'-progress.json'),JSON.stringify({role,completed,total:files.length,issues},null,2));
  }
 }
 fs.mkdirSync(coverageDir,{recursive:true});
 fs.writeFileSync(path.join(coverageDir,role+'.json'),JSON.stringify({role,pages:files.length,layouts:files.length*9,issues},null,2));
 expect(issues).toEqual([]);
 await info.attach('coverage',{body:JSON.stringify({role,pages:files.length,layouts:files.length*9}),contentType:'application/json'});
 } finally { await server.close(); }
});
