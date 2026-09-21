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
test('heatmaps retain each district and intervention without zero-filling missing scores',()=>{
 const result=panels({chart:{type:'heatmap'},series:[{name:'District A',data:[{x:'Literacy',y:2},{x:'Leadership',y:null}]}]});
 assert.deepEqual(result[0].categories,['Literacy','Leadership']);assert.deepEqual(result[0].series[0].data,[2,null]);
});

test('trend reference uses a zero baseline without fabricating initial or missing measurements',()=>{
 const input={chart:{type:'line'},series:[{name:'Visits',data:[5,null,12]}],labels:['Jan','Feb','Mar']};
 const o=options(panels(input)[0]);
 assert.equal(o.chart.type,'area');assert.equal(o.yaxis.min,0);
 assert.deepEqual(o.series[0].data,[5,null,12]);
 assert.equal(o.stroke.curve,'straight');assert.equal(o.markers.size,3);
 assert.equal(o.dataLabels.enabled,false);assert.equal(o.grid.xaxis.lines.show,true);
});
test('count axes never print fractional ticks',()=>{
 const o=options({series:[{name:'A',data:[1,3]}],categories:['x','y'],horizontal:false},600);
 assert.equal(o.yaxis.labels.formatter(1.5),''); assert.equal(o.yaxis.labels.formatter(2),'2');
 const rate=options({series:[{name:'R',data:[12.5]}],categories:['x'],horizontal:false,axis:{opposite:true}},600);
 assert.equal(rate.yaxis.labels.formatter(12.5),'12.5%');
});
