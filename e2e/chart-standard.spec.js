const {test,expect}=require('@playwright/test');
const {signIn}=require('./helpers/auth');

test('bar charts preserve units, palette, data and layout through range changes and teardown',async({page})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await signIn(page,'pl1@edify.org','edify',{acceptRequiredAgreements:false});
  await page.goto('/debriefs');
  await page.evaluate(()=>{
    const card=document.createElement('section');card.id='chart-test-card';card.className='card p-4';
    document.querySelector('main').prepend(card);
    const options={chart:{type:'bar'},labels:['Jan','Feb','Mar'],series:[
      {name:'Planned',data:[10,12,14]},{name:'Completed',data:[8,9,10]},
      {name:'Rate',data:[80,75,71]}
    ],yaxis:[{title:{text:'Activities'}},{show:false},{opposite:true,min:0,max:100,title:{text:'Achievement %'}}]};
    window.chartFixture=window.EdifyChartSystem.renderDetached(card,options);
  });
  const card=page.locator('#chart-test-card');
  await expect(card.locator('.apexcharts-bar-series')).toHaveCount(2);
  await expect(card.locator('.apexcharts-line-series,.apexcharts-pie,.apexcharts-radialbar')).toHaveCount(0);
  await expect(card.locator('.edify-chart-data')).toHaveCount(2);
  await card.locator('summary').first().click();
  await expect(card.getByRole('cell',{name:'14',exact:true})).toBeVisible();
  const colors=await card.locator('.apexcharts-bar-area').evaluateAll(nodes=>[...new Set(nodes.map(n=>n.getAttribute('fill')))]);
  expect(colors).toContain('rgba(14,93,163,1)');expect(colors).toContain('rgba(234,88,12,1)');
  for(const width of [1440,390]){
    await page.setViewportSize({width,height:1000});
    for(const theme of ['light','dark','blue']){
      await page.evaluate(theme=>{const e=document.documentElement;e.classList.remove('light','dark','theme-light','theme-dark','theme-blue');e.classList.add(...(theme==='light'?['light']:['dark','theme-'+theme]));e.dataset.theme=theme;},theme);
      await expect(card).toBeVisible();
      expect(await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth)).toBeLessThanOrEqual(1);
    }
  }
  await page.evaluate(()=>{window.chartFixture.destroy();const card=document.getElementById('chart-test-card');window.chartFixture=window.EdifyChartSystem.renderDetached(card,{chart:{type:'bar'},labels:Array.from({length:12},(_,i)=>`Period ${i+1}`),series:[{name:'Visits',data:Array.from({length:12},(_,i)=>i)}]});});
  await expect(card.getByRole('combobox',{name:'Chart range'})).toBeVisible();
  await card.getByRole('combobox').selectOption('1');
  await card.locator('summary').click();
  await expect(card.getByRole('rowheader',{name:'Period 12',exact:true})).toBeVisible();
  await expect(card.locator('[data-edify-chart-stage]')).toHaveCount(1);
  await page.evaluate(()=>window.chartFixture.destroy());
  await expect(card.locator('[data-standard-charts]')).toHaveCount(0);
  for (const route of ['/team-planning-oversight/', '/cluster-oversight/', '/core-schools-oversight/']) {
    const response = await page.goto(route);
    expect(response.status()).toBe(200);
    const plot = page.locator('[data-standard-charts]:visible').first();
    await plot.scrollIntoViewIfNeeded();
    await expect(plot.locator('.apexcharts-bar-series').first()).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth)).toBeLessThanOrEqual(1);
    if (route === '/cluster-oversight/') await page.screenshot({path:'/tmp/cluster-chart-verified.png'});
  }
  expect(errors).toEqual([]);
});
