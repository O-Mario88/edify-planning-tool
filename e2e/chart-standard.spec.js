const {test,expect}=require('@playwright/test');
const {signIn}=require('./helpers/auth');
const {watchPageErrors}=require('./helpers/page-errors');

test('bar charts preserve units, palette, data and layout through range changes and teardown',async({page})=>{
  const errors=watchPageErrors(page);
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
  // Every bar chart is the cut-out since 2026-10-18 (upright columns here):
  // the counts and the rate are two panels, drawn without the chart library.
  await expect(card.locator('.edify-cutcol')).toHaveCount(2);
  await expect(card.locator('.edify-cutcol').first().locator('.edify-cutcol__bar')).toHaveCount(6);
  await expect(card.locator('.edify-cutcol').nth(1).locator('.edify-cutcol__bar')).toHaveCount(3);
  await expect(card.locator('.apexcharts-canvas')).toHaveCount(0);
  await expect(card.locator('.edify-chart-data')).toHaveCount(2);
  await card.locator('summary').first().click();
  await expect(card.getByRole('cell',{name:'14',exact:true})).toBeVisible();
  // Any number of series in shades of one hue: Planned and Completed are two
  // shades of the first series colour, named in the legend.
  const fills=await card.locator('.edify-cutcol').first().locator('.edify-cutout__key').evaluateAll(keys=>keys.map(k=>k.style.getPropertyValue('--cutout-fill')));
  expect(fills).toHaveLength(2);expect(new Set(fills).size).toBe(2);
  for(const fill of fills)expect(fill).toContain('--edify-series-1');
  for(const width of [1440,390]){
    await page.setViewportSize({width,height:1000});
    for(const theme of ['light','dark','blue']){
      await page.evaluate(theme=>{const e=document.documentElement;e.classList.remove('light','dark','theme-light','theme-dark','theme-blue');e.classList.add(...(theme==='light'?['light']:['dark','theme-'+theme]));e.dataset.theme=theme;},theme);
      await expect(card).toBeVisible();
      expect(await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth)).toBeLessThanOrEqual(1);
    }
  }
  await page.evaluate(()=>{window.chartFixture.destroy();const card=document.getElementById('chart-test-card');window.chartFixture=window.EdifyChartSystem.renderDetached(card,{chart:{type:'bar'},labels:Array.from({length:14},(_,i)=>`Period ${i+1}`),series:[{name:'Visits',data:Array.from({length:14},(_,i)=>i)}]});});
  await expect(card.getByRole('combobox',{name:'Chart range'})).toBeVisible();
  await card.getByRole('combobox').selectOption('1');
  await card.locator('summary').click();
  await expect(card.getByRole('rowheader',{name:'Period 14',exact:true})).toBeVisible();
  // A range change replaces the page's chart; it never stacks a second one.
  await expect(card.locator('.edify-cutcol')).toHaveCount(1);
  await page.evaluate(()=>window.chartFixture.destroy());
  await expect(card.locator('[data-standard-charts]')).toHaveCount(0);
  // Cluster Oversight dropped its chart on 2026-09-23 for the member-by-member
  // clusters, trainings and meetings, and Core School Oversight its package
  // chart on 2026-10-17 when it became the Core schools analysed (tables and
  // figures with their denominators); the chart-bearing oversight page remains.
  // The year the demo seed's work is dated in: in a year with nothing
  // planned every bar is zero high, and a series of them has no box.
  for (const route of ['/team-planning-oversight/?fy=2026']) {
    const response = await page.goto(route);
    expect(response.status()).toBe(200);
    const plot = page.locator('[data-standard-charts]:visible').first();
    await plot.scrollIntoViewIfNeeded();
    await expect(plot.locator('.edify-cutcol__bar, .edify-cutout__bar').first()).toBeVisible();
    expect(await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth)).toBeLessThanOrEqual(1);
  }
  expect(errors).toEqual([]);
});
