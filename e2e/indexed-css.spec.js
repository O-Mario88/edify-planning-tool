const {test,expect}=require('@playwright/test');
const {signIn}=require('./helpers/auth');
const index=require('../static/build/css/selectors.json');
test.use({video:'off',trace:'off',serviceWorkers:'block'});
test('indexed selectors preserve live layouts and theme styling',async({page})=>{
 test.setTimeout(180000);
 await signIn(page,'admin@edify.org','edify',{acceptRequiredAgreements:false});
 const settle=()=>page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
 const files=['main','design-system','components','pages','platform','consistency','drawers','components/mobile-micro-ux','components/interactions','components/mobile-patterns'];
 for(const route of ['/analytics','/schools','/projects/planning','/dashboard?view=operations','/leave/calendar']){
  await page.goto(route,{waitUntil:'networkidle'});
  // Inline !important wins over component-specific transition rules.
  // Compare settled styles, not different points in a theme cross-fade.
  await page.evaluate(()=>document.querySelectorAll('*').forEach(el=>{
   el.style.setProperty('transition','none','important');
   el.style.setProperty('animation','none','important');
  }));
  const unknown=await page.evaluate(index=>{
   const patterns=Object.entries(index).map(([part,names])=>[part,new Set(names)]);
   const misses=new Set();
   document.querySelectorAll('[class]').forEach(el=>patterns.forEach(([part,names])=>{
    if(el.getAttribute('class').includes(part)&&![...el.classList].some(name=>names.has(name)))misses.add(part+': '+el.getAttribute('class'));
   }));return [...misses];
  },index);
  expect(unknown,route).toEqual([]);
  await page.evaluate(async files=>{
   await Promise.all(files.map(name=>new Promise(resolve=>{
    const compiled=document.querySelector(`link[href*="/build/css/${name}.css"]`);if(!compiled)return resolve();
    const source=document.createElement('link');source.rel='stylesheet';source.href=`/static/css/${name}.css`;source.dataset.sourceCss='';source.media='not all';source.onload=resolve;compiled.after(source);
   })));
  },files);
  for(const theme of ['theme-light','theme-blue dark','theme-dark dark']){
   await page.evaluate(theme=>document.documentElement.className=theme,theme);
   await settle();
   const snapshot=()=>page.evaluate(()=>[...document.querySelectorAll('main h1, main h2, main button, main th, main td, main .context-metrics__sentence')].slice(0,150).map(e=>{
    const s=getComputedStyle(e);return ['color','backgroundColor','fontFamily','fontWeight','fontSize','display','borderRadius','width','height','paddingTop','paddingRight','paddingBottom','paddingLeft','marginTop','marginBottom'].map(p=>s[p]);
   }));
   const compiled=await snapshot();
   await page.evaluate(()=>{document.querySelectorAll('link[href*="/build/css/"]').forEach(e=>e.disabled=true);document.querySelectorAll('[data-source-css]').forEach(e=>e.media='all');});
   await settle();
   expect(await snapshot(),route+' '+theme).toEqual(compiled);
   await page.evaluate(()=>{document.querySelectorAll('[data-source-css]').forEach(e=>e.media='not all');document.querySelectorAll('link[href*="/build/css/"]').forEach(e=>e.disabled=false);});
   await settle();
  }
 }
});

test('calendar view switches preserve generated class coverage', async ({page}) => {
 await signIn(page,'admin@edify.org','edify',{acceptRequiredAgreements:false});
 await page.goto('/leave/calendar',{waitUntil:'networkidle'});
 for (const view of ['timeGridWeek','listMonth','dayGridMonth']) {
  await page.locator(`.fc-${view}-button`).click();
  await expect(page.locator(`.fc-${view}-view`)).toBeVisible();
  const missing = await page.evaluate(index => {
   const patterns = Object.entries(index).map(([part,names]) => [part,new Set(names)]);
   return [...document.querySelectorAll('.fc [class]')].flatMap(el => patterns
    .filter(([part,names]) => el.getAttribute('class').includes(part) && ![...el.classList].some(name => names.has(name)))
    .map(([part]) => `${part}: ${el.className}`));
  },index);
  expect(missing,view).toEqual([]);
 }
});

test('forced-color boundaries override every theme', async ({page,browserName}) => {
 test.skip(browserName !== 'chromium', 'Forced-color emulation is checked in Chromium.');
 await signIn(page,'admin@edify.org','edify',{acceptRequiredAgreements:false});
 await page.goto('/schools');
 await page.emulateMedia({forcedColors:'active'});
 for (const theme of ['theme-light','theme-dark dark','theme-blue dark']) {
  await page.evaluate(theme => document.documentElement.className=theme,theme);
  expect(await page.evaluate(() => {
   const style=getComputedStyle(document.documentElement);
   return ['--edify-card-border','--page-header-border'].map(key=>style.getPropertyValue(key).trim().toLowerCase());
  })).toEqual(['canvastext','canvastext']);
 }
});
