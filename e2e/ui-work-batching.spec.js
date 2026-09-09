const {test,expect}=require('@playwright/test');
const {snapshotServer}=require('./helpers/snapshot-server');
const path=require('node:path');
test.use({video:'off',trace:'off'});
test('nested fragment insertion enhances each subtree once',async({page})=>{
 const server=await snapshotServer(path.resolve(__dirname,'..'));
 try {
  server.setHtml('<html><body><main></main><script src="/static/js/micro-ux.js"></script></body></html>');
  await page.goto(server.origin+'/page');
  await page.evaluate(()=>{
   window.childScans=0;
   const original=Element.prototype.querySelectorAll;
   Element.prototype.querySelectorAll=function(selector){if(this.classList.contains('nested-probe')&&selector==='table')window.childScans++;return original.call(this,selector);};
   const outer=document.createElement('section');document.querySelector('main').append(outer);
   for(let i=0;i<30;i++){
    const child=document.createElement('div');child.className='nested-probe';outer.append(child);
    child.innerHTML=`<label for="field-${i}">Field ${i}</label><input id="field-${i}" value="filled"><button hx-get="/open">Open ${i}</button>`;
   }
  });
  await expect(page.locator('button[type="button"]')).toHaveCount(30);
  expect(await page.evaluate(()=>window.childScans)).toBe(0);
  await expect(page.locator('input').first()).toHaveAttribute('data-edify-filled','');
 }finally{await server.close();}
});
