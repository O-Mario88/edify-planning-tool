const {test,expect}=require('@playwright/test');
const {signIn}=require('./helpers/auth');

test('drawer saves close their source; validation, previews and newer drawers remain open',async({page})=>{
  test.setTimeout(180000);
  await signIn(page,'pl1@edify.org','edify',{acceptRequiredAgreements:false});
  await page.goto('/debriefs');
  const response=await page.request.get('/analytics/schedule-report');
  expect(response.status()).toBe(200);
  const original=await response.text();
  let reply={status:200,body:'<p>Saved</p>'};
  let pending=null;
  await page.route('**/__drawer-test__/**',async route=>{
    if(reply.hold){pending=route;return;}
    if(reply.abort){await route.abort('failed');return;}
    await route.fulfill({contentType:'text/html',...reply});
  });
  async function mount(kind='base'){
    await page.evaluate(({html,kind})=>{
      const fragment=new DOMParser().parseFromString(html,'text/html');
      const host=document.getElementById('drawer-container');
      const root=kind==='base'?fragment.body.firstElementChild:document.createElement('div');
      if(kind!=='base'){
        root.className='edify-popup-dialog';root.setAttribute('x-data','{open:true}');
        root.setAttribute('x-show','open');root.setAttribute('x-on:close-drawer.window','open=false;setTimeout(()=>$el.remove(),300)');
        root.innerHTML='<div class="card p-4" role="dialog" aria-label="Custom drawer"><div class="drawer-body"></div></div>';
      }
      root.dataset.testDrawer=kind;
      root.querySelector('.drawer-body').innerHTML='<form hx-post="/__drawer-test__/save" hx-target="#test-errors"><input name="name" value="Unsaved input"><input name="preview" hx-post="/__drawer-test__/preview" hx-trigger="change" hx-target="#test-errors"><button type="submit">Save test</button><div id="test-errors"></div></form>';
      host.replaceChildren(root);window.htmx.process(host);
    },{html:original,kind});
    await expect(page.locator('[data-test-drawer]').getByRole('button',{name:'Save test'})).toBeVisible();
  }
  const root=()=>page.locator('[data-test-drawer]');
  async function save(){await page.getByRole('button',{name:'Save test',exact:true}).click();}

  // Successful responses, including falsy JSON trigger values and all HTMX phases.
  for(const headers of [{},{'HX-Trigger':'{"close-drawer":null}'},{'HX-Trigger-After-Swap':'close-drawer'},{'HX-Trigger-After-Settle':'{"close-drawer":{}}'}]){
    reply={status:200,body:'<p>Saved</p>',headers};await mount();await save();await expect(root()).toHaveCount(0);
    expect(await page.evaluate(()=>window.__edifyDrawerBackground.isLocked())).toBe(false);
  }
  reply={status:204,body:''};await mount('custom');await save();await expect(root()).toHaveCount(0);

  // 400 is deliberately swapped by the app, but it must not count as a save.
  for(const failure of [{status:400,body:'<p role="alert">Choose a date</p>'},{status:200,body:'<div class="errorlist">Choose a date</div>'},{status:500,body:'Server error'},{abort:true}]){
    reply=failure;await mount();await save();await page.waitForTimeout(500);
    await expect(root().getByRole('button',{name:'Save test'})).toBeVisible();await expect(root().locator('[name=name]')).toHaveValue('Unsaved input');
  }
  reply={status:200,body:'<p>Cost preview</p>'};await mount();
  await root().locator('[name=preview]').fill('123');
  await root().locator('[name=preview]').dispatchEvent('change');await page.waitForTimeout(500);await expect(root().getByRole('button',{name:'Save test'})).toBeVisible();

  // A delayed successful save belongs to the old drawer only.
  reply={hold:true};await save();await expect.poll(()=>Boolean(pending)).toBe(true);
  await mount('replacement');await pending.fulfill({status:200,contentType:'text/html',headers:{'HX-Trigger':'close-drawer','HX-Retarget':'#drawer-container'},body:'<p>Old save response</p>'});
  await page.waitForTimeout(600);await expect(page.locator('[data-test-drawer="replacement"]')).toBeVisible();

  // The base drawer's manual close timer cannot empty its replacement either.
  await mount();await page.evaluate(()=>window.dispatchEvent(new CustomEvent('close-drawer')));await mount('replacement');
  await page.waitForTimeout(600);await expect(page.locator('[data-test-drawer="replacement"]')).toBeVisible();
});
