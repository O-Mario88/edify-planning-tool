const {test} = require('node:test');
const assert = require('node:assert/strict');
const {panels, options, palette, pageSize, barShare, initialPage} = require('../../static/js/chart-standard.js');
test('mixed counts and rates become separate panels without losing prior-year counts', () => {
  const input = {chart:{type:'line'},series:[{name:'Planned',data:[2,3]},{name:'Done',data:[1,2]},{name:'Rate',data:[50,67]},{name:'Prior',data:[1,1]}],labels:['Jan','Feb'],yaxis:[{title:{text:'Activities'}},{show:false},{opposite:true,max:100},{show:false}]};
  const result=panels(input);
  assert.equal(result.length,2);
  assert.deepEqual(result[0].series.map(s=>s.name),['Planned','Done','Prior']);
  assert.equal(result[1].series[0].name,'Rate');
  assert.equal(options(result[1]).chart.type,'area');
  assert.equal(options(result[1]).dataLabels.formatter(50),'50%');
  assert.equal(input.chart.type,'line');
});
test('missing and negative values remain distinguishable from zero',()=>{
 const p=panels({series:[{name:'Change',data:[null,-2,0,3]}],labels:['A','B','C','D']})[0];
 assert.deepEqual(p.series[0].data,[null,-2,0,3]);
 assert.equal(options(p).yaxis.min,-2);
 assert.equal(options(p).dataLabels.formatter(null),'Not measured');
});
test('donuts become blue category bars and gauges retain percentage scale',()=>{
 const p=panels({chart:{type:'donut'},series:[2,3],labels:['A','B']})[0];
 assert.deepEqual(p.series[0].data,[2,3]); assert.equal(p.horizontal,true);
 assert.deepEqual(options(p).colors,[palette[0]]);
 assert.equal(options(p).yaxis.labels.formatter('A'),'A');
 const gauge=options(panels({chart:{type:'radialBar'},series:[25],labels:['Utilized']})[0]);
 assert.equal(gauge.yaxis.max,100); assert.equal(gauge.dataLabels.formatter(25),'25%');
});
test('scatter conversion preserves duplicate observations and signed outcomes',()=>{
 const p=panels({chart:{type:'scatter'},series:[{name:'Core',data:[[2,1],[2,-1],[4,null]]}]} )[0];
 assert.deepEqual(p.series[0].data,[1,-1,null]); assert.equal(new Set(p.categories).size,3);
});
test('large comparisons preserve every value in at-most-eight-series panels',()=>{
 const input={series:Array.from({length:10},(_,i)=>({name:`S${i}`,data:Array.from({length:12},(_,j)=>i*100+j)})),labels:Array.from({length:12},(_,i)=>`M${i}`)};
 const result=panels(input);
 assert.equal(result.reduce((sum,p)=>sum+p.series.reduce((n,s)=>n+s.data.length,0),0),120);
 for(const p of result){const o=options(p);assert.equal(o.chart.type,'bar');assert.equal(o.plotOptions.bar.borderRadius,0);assert.ok(o.colors.length<=8);assert.ok(p.series.length<=8);}
});
test('a person keeps their colour on every page and in every panel',()=>{
 // Six team members over twelve months: six series is a six-category page,
 // so the year spans two pages — and Ruth is the fourth hue on both.
 const people=['Lead','Deo','Mary','Ruth','Paul','Simon'];
 const input={series:people.map((name,i)=>({name,data:Array.from({length:12},(_,j)=>i+j)})),labels:Array.from({length:12},(_,i)=>`M${i+1}`)};
 const result=panels(input);
 assert.equal(result.length,2);
 assert.equal(result[0].title,'M1 – M6'); assert.equal(result[1].title,'M7 – M12');
 for(const p of result){assert.equal(options(p).colors[3],palette[3]);assert.equal(p.series[3].name,'Ruth');}
 // A single measure and a mixed-axis rate panel still start from blue.
 assert.equal(options(panels({series:[{name:'Only',data:[1]}],labels:['A']})[0]).colors[0],palette[0]);
});
test('pages hold fewer categories as the series count grows, so bars stay readable',()=>{
 assert.equal(pageSize(false,1),12); assert.equal(pageSize(false,4),8); assert.equal(pageSize(false,6),6); assert.equal(pageSize(true,8),10);
 // With a measured width the page is the widest natural span whose bars clear 10px:
 // six people on a 1120px card hold the year; on a 410px dashboard column, four months.
 assert.equal(pageSize(false,6,1120),12); assert.equal(pageSize(false,6,410),4); assert.equal(pageSize(false,8,320),3);
 const year={series:Array.from({length:6},(_,i)=>({name:`P${i}`,data:Array.from({length:12},(_,j)=>j>8?1:0)})),labels:Array.from({length:12},(_,i)=>`M${i+1}`)};
 assert.equal(panels(year,1120).length,1);
 const narrow=panels(year,410); assert.equal(narrow.length,3); assert.equal(initialPage(narrow),2);
 assert.equal(initialPage(panels({plotOptions:{bar:{horizontal:true}},series:[{name:'A',data:Array(14).fill(1)}],labels:Array.from({length:14},(_,i)=>`R${i}`)},1120)),0);
 const wide={series:[{name:'A',data:Array.from({length:12},()=>1)}],labels:Array.from({length:12},(_,i)=>`M${i}`)};
 assert.equal(panels(wide).length,1);
});
test('bar thickness is capped rather than filling the band',()=>{
 const panel={series:[{name:'A',data:[1]}],categories:['One','Two'],horizontal:false};
 // Two bands of ~464px each on a 1000px plot: a 22px bar is a small share.
 assert.equal(barShare(panel,1000),'18%');
 // Eight people in four bands on a phone: the cap cannot be met, so the band's ceiling holds.
 assert.equal(barShare({series:Array.from({length:8},()=>({data:[1]})),categories:['a','b','c','d']},320),'60%');
 assert.equal(barShare(panel,0),'60%');
 const o=options(panel,1000);
 assert.equal(o.chart.height,220); assert.equal(o.grid.strokeDashArray,0); assert.equal(o.legend.show,false);
 assert.equal(options({...panel,series:[{name:'A',data:[1]},{name:'B',data:[2]}]},1000).legend.position,'top');
});
test('value labels stay silent when their bar has no room for them',()=>{
 const o=options({series:[{name:'A',data:[12]}],categories:['One'],horizontal:false},600);
 assert.equal(o.dataLabels.formatter(12,{w:{globals:{gridWidth:600,gridHeight:200,labels:['One'],series:[[12]]}}}),'12');
 assert.equal(o.dataLabels.formatter(12,{w:{globals:{gridWidth:200,gridHeight:200,labels:Array(10).fill('x'),series:Array(8).fill([1])}}}),'');
});
test('a missing value says so without the unit, and only where the words have room',()=>{
 const rate=options(panels({series:[{name:'Rate',data:[null,40]}],labels:['A','B'],yaxis:{title:{text:'Completed (%)'}}})[0]);
 assert.equal(rate.dataLabels.formatter(40),'40%');
 assert.equal(rate.dataLabels.formatter(null),'Not measured');
 const one={w:{globals:{gridWidth:600,gridHeight:200,labels:['A','B'],series:[[null,40]]}}};
 assert.equal(rate.dataLabels.formatter(null,one),'Not measured');
 // Six people over one month: side-by-side bars leave the words no room.
 const six={w:{globals:{gridWidth:600,gridHeight:200,labels:['Oct'],series:Array(6).fill([null])}}};
 assert.equal(rate.dataLabels.formatter(null,six),'');
 assert.equal(rate.dataLabels.formatter(0,six),'0%');
 const narrow={w:{globals:{gridWidth:600,gridHeight:200,labels:Array(12).fill('x'),series:[[null]]}}};
 assert.equal(rate.dataLabels.formatter(null,narrow),'');
});
test('heatmaps retain each district and intervention without zero-filling missing scores',()=>{
 const result=panels({chart:{type:'heatmap'},series:[{name:'District A',data:[{x:'Literacy',y:2},{x:'Leadership',y:null}]}]});
 assert.deepEqual(result[0].categories,['Literacy','Leadership']);assert.deepEqual(result[0].series[0].data,[2,null]);
});

test('trend reference uses a zero baseline without fabricating initial or missing measurements',()=>{
 const input={chart:{type:'line'},series:[{name:'Visits',data:[5,null,12]}],labels:['Jan','Feb','Mar']};
 const o=options(panels(input)[0]);
 assert.equal(o.chart.type,'area');assert.equal(o.yaxis.min,0);
 assert.deepEqual(o.series[0].data,[5,null,12]);
 assert.equal(o.stroke.curve,'monotoneCubic');assert.equal(o.yaxis.min,0);assert.equal(o.xaxis.labels.hideOverlappingLabels,false);assert.equal(o.markers.size,3);
 assert.equal(o.dataLabels.enabled,false);assert.equal(o.grid.xaxis.lines.show,true);
});
test('count axes never print fractional ticks',()=>{
 const o=options({series:[{name:'A',data:[1,3]}],categories:['x','y'],horizontal:false},600);
 assert.equal(o.yaxis.labels.formatter(1.5),''); assert.equal(o.yaxis.labels.formatter(2),'2');
 const rate=options({series:[{name:'R',data:[12.5]}],categories:['x'],horizontal:false,axis:{opposite:true}},600);
 assert.equal(rate.yaxis.labels.formatter(12.5),'12.5%');
});

// A chart asked for before the chart library has run (owner's nightly Browser
// Matrix, 2026-10-08): it is drawn when the library has, not given up.
test('a chart asked for before the library has run is drawn once it has', () => {
  const {whenLibraryRuns, late} = require('../../static/js/chart-standard.js');
  const before = {document: globalThis.document, ApexCharts: globalThis.ApexCharts};
  // Every listener the script tag was given; `loaded` is its load event.
  const listeners = [];
  const tag = {addEventListener: (type, fn) => { if (type === 'load') listeners.push(fn); }};
  const loaded = () => listeners.splice(0).forEach((fn) => fn());
  try {
    // A page that does not load the library: nothing to wait for.
    globalThis.document = {querySelector: () => null};
    assert.equal(whenLibraryRuns(() => assert.fail('drawn without a library')), false);
    assert.equal(late({}, {isConnected: true}, {}), null);

    // The library is on its way: the caller holds a handle, and the chart is
    // drawn, once, when the script has loaded.
    globalThis.document = {querySelector: () => tag};
    const drawn = [];
    const system = {renderDetached: (el, opts) => { drawn.push(opts); return {destroy: () => drawn.push('destroyed')}; }};
    const handle = late(system, {isConnected: true}, {name: 'trend'});
    assert.equal(typeof handle.destroy, 'function');
    assert.deepEqual(drawn, []);
    globalThis.ApexCharts = function ApexCharts() {};
    loaded();
    assert.deepEqual(drawn, [{name: 'trend'}]);
    handle.destroy();
    assert.deepEqual(drawn, [{name: 'trend'}, 'destroyed']);

    // Destroyed while it waited, or its card gone: never drawn.
    delete globalThis.ApexCharts;
    const dropped = late(system, {isConnected: true}, {name: 'dropped'});
    dropped.destroy();
    const gone = late(system, {isConnected: false}, {name: 'gone'});
    globalThis.ApexCharts = function ApexCharts() {};
    loaded();
    assert.equal(drawn.length, 2);
    assert.ok(gone);

    // Already run: drawn at once.
    let now = 0;
    assert.equal(whenLibraryRuns(() => { now += 1; }), true);
    assert.equal(now, 1);
  } finally {
    globalThis.document = before.document;
    if (before.ApexCharts === undefined) delete globalThis.ApexCharts; else globalThis.ApexCharts = before.ApexCharts;
  }
});
// Owner, 2026-10-09, with a reference chart: "use the graph format (Horizontal
// Cut out bar graph) above for all horizontal bar graphs".
test('a horizontal chart of one or two series is cut-out bars; anything else keeps the library', () => {
  const {cutsOut, cutOutScale, needsLibrary} = require('../../static/js/chart-standard.js');
  const years = {chart: {type: 'bar'}, plotOptions: {bar: {horizontal: true}},
    series: [{name: 'FY 2024/25', data: [4.9, 5]}, {name: 'FY 2025/26', data: [5.9, 4.2]}],
    xaxis: {categories: ['Leadership', 'Enrolment']}, yaxis: {min: 0, max: 10, title: {text: 'SSA score (0–10)'}}};
  const panel = panels(years)[0];
  assert.equal(cutsOut(panel), true);
  // The scale is the axis the chart names, in five steps.
  assert.deepEqual(cutOutScale(panel), {max: 10, step: 2});
  // No library on the page is no reason to leave the card empty.
  assert.equal(needsLibrary(years), false);
  // With no scale named, a round one at or above the longest bar.
  assert.deepEqual(cutOutScale({series: [{data: [37.7, 14.4]}], axis: {}}), {max: 40, step: 10});
  assert.deepEqual(cutOutScale({series: [{data: [83]}], axis: {}}), {max: 100, step: 25});

  // Vertical bars, three series and a value below zero are not this form.
  assert.equal(cutsOut(panels({...years, plotOptions: {}})[0]), false);
  const three = {...years, series: [...years.series, {name: 'Target', data: [7, 7]}]};
  assert.equal(cutsOut(panels(three)[0]), false);
  assert.equal(needsLibrary(three), true);
  const signed = {...years, series: [{name: 'Change', data: [1, -0.8]}]};
  assert.equal(cutsOut(panels(signed)[0]), false);
  // Nothing measured draws the "no data" line, which needs no library either.
  const empty = {...years, series: [{name: 'FY 2025/26', data: [null, null]}]};
  assert.equal(cutsOut(panels(empty)[0]), false);
  assert.equal(needsLibrary(empty), false);
  // A chart a page built for the library itself still waits for it.
  assert.equal(needsLibrary({...years, _edifyStandard: true}), true);
});
// Owner, 2026-10-09: "fix all the line graph with starting point 0 and fix
// the labels the line should be wave like".
test('a trend keeps every label: long names break between words, each edge has room, one long word tilts', () => {
  const names = ['Christlike Behaviour', 'Exposure to the Word of God', 'Financial Health', 'Leadership',
    'Government Requirements', 'Learning Environment', "Teacher's Environment", 'Enrolment'];
  const panel = panels({chart: {type: 'line'}, series: [{name: 'FY2026', data: [5, 6, 5, 6, 5, 6, 5, 6]}], xaxis: {categories: names}})[0];
  const wide = options(panel, 1100);
  assert.equal(wide.xaxis.labels.hideOverlappingLabels, false);
  // 27 letters do not fit an eighth of 1100px: the name is two lines, level.
  assert.deepEqual(wide.xaxis.categories[1], ['Exposure to the', 'Word of God']);
  assert.equal(wide.xaxis.categories[3], 'Leadership');
  assert.equal(wide.xaxis.labels.rotateAlways, false);
  // The card grows by the extra line, so the plot keeps its height.
  assert.equal(wide.chart.height, 220 + 14);
  // Half of the first and of the last label fits inside the card.
  assert.ok(wide.grid.padding.left >= 40 && wide.grid.padding.right >= 35);
  // The panel's own names are untouched: the data table prints them whole.
  assert.equal(panel.categories[1], 'Exposure to the Word of God');

  const months = panels({chart: {type: 'line'}, series: [{name: 'Visits', data: [0, 4, 9]}], labels: ['Oct', 'Nov', 'Dec']})[0];
  const level = options(months, 700);
  assert.deepEqual(level.xaxis.categories, ['Oct', 'Nov', 'Dec']);
  assert.equal(level.chart.height, 220);
  // A single word wider than its share cannot break: those labels tilt.
  const long = panels({chart: {type: 'line'}, series: [{name: 'Visits', data: Array(12).fill(1)}], labels: Array(12).fill('September')})[0];
  assert.equal(options(long, 360).xaxis.labels.rotateAlways, true);
  // Bars are untouched: their labels sit under a band, not on its edge.
  const bars = options(panels({chart: {type: 'bar'}, series: [{name: 'Visits', data: [1, 2]}], labels: ['Oct', 'Nov']})[0], 700);
  assert.equal(bars.grid.padding.left, 4);
  assert.equal(bars.xaxis.labels.hideOverlappingLabels, true);
});
