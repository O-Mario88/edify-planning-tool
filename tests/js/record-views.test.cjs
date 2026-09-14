const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
function mount() {
  const listeners = {}, controls = [];
  function node(tag = 'SPAN') {
    const classes = new Set();
    return {tagName:tag, children:[], dataset:{}, attrs:{}, colSpan:1, rowSpan:1,
      classList:{add:k=>classes.add(k),remove:k=>classes.delete(k)},
      setAttribute(k,v){this.attrs[k]=v;}, append(...items){this.children.push(...items);},
      prepend(item){this.children.unshift(item);item.parent=this;},
      remove(){if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this);const i=controls.indexOf(this);if(i>=0)controls.splice(i,1);},
      addEventListener(name,fn){this[name]=fn;},
      querySelectorAll(selector){return selector==='button'?this.children.filter(n=>n.tagName==='BUTTON'):[];},
    };
  }
  const cells = [node('TD'),node('TD'),node('TD')];
  const row = node('TR'); row.cells=cells;
  const head = node('TR'); head.cells=['School','Status','Action'].map(text=>Object.assign(node('TH'),{textContent:text}));
  const tbody = node('TBODY');
  const table = Object.assign(node('TABLE'),{caption:{textContent:'Schools'},tFoot:null});
  const region = {before:n=>controls.push(n)};
  table.matches=()=>true; table.closest=selector=>selector==='#main-content'?{}:region;
  table.querySelectorAll=selector=>({
    ':scope > thead > tr':[head], ':scope > tbody > tr':[row], ':scope > thead, :scope > tbody':[node('THEAD'),tbody],
    '.edify-record-field-label':cells.flatMap(c=>c.children),
  }[selector]||[]);
  tbody.closest=()=>table;
  const document={readyState:'complete',createElement:tag=>node(tag.toUpperCase()),querySelectorAll:()=>[table],addEventListener:(name,fn)=>listeners[name]=fn};
  vm.runInNewContext(fs.readFileSync('static/js/record-views.js','utf8'),{document});
  return {table,cells,controls,refresh:()=>listeners['htmx:load']({detail:{elt:tbody}}),remove:()=>listeners['htmx:beforeCleanupElement']({detail:{elt:table}})};
}
test('refresh keeps the chosen table view without duplicating labels or controls',()=>{
  const h=mount();
  const originalCell=h.cells[0];
  h.controls[0].children.find(n=>n.textContent==='Table').click();
  h.refresh();
  assert.equal(h.table.dataset.recordView,'table');
  assert.equal(h.controls.length,1);
  assert.equal(h.cells[0],originalCell);
  assert.equal(h.cells[0].children.length,1);
  assert.equal(h.controls[0].children.find(n=>n.textContent==='Table').attrs['aria-pressed'],'true');
});
test('removing a table also removes its generated controls',()=>{
  const h=mount();h.remove();
  assert.equal(h.controls.length,0);
  assert.equal(h.cells[0].children.length,0);
});
