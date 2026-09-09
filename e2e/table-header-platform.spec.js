const {test,expect}=require('@playwright/test');
const {snapshotServer}=require('./helpers/snapshot-server');
const {signIn}=require('./helpers/auth');
const fs=require('fs'),path=require('path');
test.use({video:'off',trace:'off',serviceWorkers:'block'});
test('light table headers across platform pages',async({page},info)=>{
 test.setTimeout(360000);
 const root=path.resolve(__dirname,'..'),dir=path.join(root,'test-results/kpi-platform-crawl');
 test.skip(!fs.existsSync(dir), 'Requires test-results/kpi-platform-crawl');
 const files=fs.existsSync(dir)?fs.readdirSync(dir).filter(f=>/^Admin-.*\.html$/.test(f)):[];
 const server=await snapshotServer(root),issues=[];let checked=0;
 try{for(const file of files){
  const html=fs.readFileSync(path.join(dir,file),'utf8');if(!html.includes('<table')&&!html.includes('school-record-action'))continue;
  server.setHtml(html);await page.goto(server.origin+'/page',{waitUntil:'domcontentloaded'});
  await page.addStyleTag({content:'*,*::before,*::after{transition:none!important;animation:none!important}'});
  for(const width of [1290]){
   await page.setViewportSize({width,height:900});
   for(const theme of ['light']){
    await page.evaluate(t=>{document.documentElement.classList.remove('light','dark','theme-light','theme-dark','theme-blue');document.documentElement.classList.add(t);document.documentElement.classList.toggle('dark',t!=='light')},theme);
    const errors=await page.evaluate(()=>{
     const errors=[];
     for(const e of document.querySelectorAll('table thead th, .edify-table-titlebar')){
      const r=e.getBoundingClientRect();if(!r.width||!r.height)continue;
      const s=getComputedStyle(e);
      if(e.matches('th')&&s.color!=='rgb(40, 91, 150)')errors.push(e.className+' color='+s.color);
      if(e.matches('.edify-table-titlebar')&&s.backgroundColor!=='rgb(40, 91, 150)')errors.push(e.className+' background='+s.backgroundColor);
     }
     return [...new Set(errors)].slice(0,8);
    });checked++;if(errors.length)issues.push({file,width,theme,errors});
   }
  }
 }
 await info.attach('table-header-coverage',{body:JSON.stringify({checked,issues},null,2),contentType:'application/json'});
 expect(checked).toBeGreaterThan(80);expect(issues).toEqual([]);
 }finally{await server.close()}
});

