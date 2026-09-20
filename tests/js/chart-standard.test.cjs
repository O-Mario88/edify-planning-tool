const {test} = require('node:test');
const assert = require('node:assert/strict');
const {panels, options, palette} = require('../../static/js/chart-standard.js');
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
test('large comparisons preserve every value in at-most-four-series panels',()=>{
 const input={series:Array.from({length:6},(_,i)=>({name:`S${i}`,data:Array.from({length:12},(_,j)=>i*100+j)})),labels:Array.from({length:12},(_,i)=>`M${i}`)};
 const result=panels(input);assert.equal(result.length,4);
 assert.equal(result.reduce((sum,p)=>sum+p.series.reduce((n,s)=>n+s.data.length,0),0),72);
 for(const p of result){const o=options(p);assert.equal(o.chart.type,'bar');assert.equal(o.plotOptions.bar.borderRadius,0);assert.ok(o.colors.length<=4);}
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
