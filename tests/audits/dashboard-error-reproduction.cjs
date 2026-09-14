// Isolated event-contract probe of the actual dashboard cache script.
// No browser, requests, or application data are used.
const fs = require('node:fs');
const vm = require('node:vm');
const listeners = {};
let attached = true;
const panel = {remove(){attached=false;}};
const host = {querySelector:()=>attached?panel:null, matches:()=>true};
const document = {
  readyState:'complete',
  querySelector(selector){
    if(selector==='[data-dashboard-live]')return null;
    if(selector==='[data-dashboard-view-shell]')return host;
    if(selector==='[data-dashboard-views] .edify-section-nav__link.is-active')
      return {getAttribute:()=>'/dashboard?view=overview'};
    return null;
  },
  addEventListener(name,fn){listeners[name]=fn;},
};
const window = {location:{origin:'http://audit.test',href:'http://audit.test/dashboard?view=overview'},addEventListener(){}};
vm.runInNewContext(fs.readFileSync('static/js/view-panels.js','utf8'),{document,window,URL});
// HTMX emits beforeSwap even for a 500; shouldSwap is false for that response.
listeners['htmx:beforeSwap']({detail:{target:host,shouldSwap:false,isError:true,xhr:{status:500}}});
console.log(JSON.stringify({responseStatus:500,shouldSwap:false,expectedPanelAttached:true,
                           actualPanelAttached:attached,passed:attached}));
process.exitCode = attached ? 0 : 1;
