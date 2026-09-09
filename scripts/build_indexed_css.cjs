/* Compile legacy class-substring selectors into class-indexed selectors.
 * :is(.a,.b) has the same specificity as [class*="…"]. Enumerate candidates
 * from the application and CSS, as Tailwind does, rather than scanning every
 * element after unrelated class changes. Human-editable styles stay in css/;
 * static/build/css/ is generated and must be rebuilt when classes or styles change.
 */
const fs = require('node:fs');
const path = require('node:path');
const { Scanner } = require('@tailwindcss/oxide');
const { transform } = require('lightningcss');
const root = path.resolve(__dirname, '..');
const directory = path.join(root, 'static/css');
const files = ['main.css', 'design-system.css', 'components.css', 'pages.css', 'platform.css', 'consistency.css', 'drawers.css', 'components/mobile-micro-ux.css', 'components/interactions.css', 'components/mobile-patterns.css'];
const candidates = new Set(new Scanner({sources: [{base:root, pattern:'{templates,apps,static/js}/**/*.{html,py,js}', negated:false}]}).scan());
// FullCalendar constructs these from configured view names at runtime.
for (const view of ['dayGridMonth', 'timeGridWeek', 'listMonth']) {
  candidates.add(`fc-${view}-button`);
  candidates.add(`fc-${view}-view`);
}
for (const position of ['top', 'right', 'bottom', 'left']) {
  candidates.add(`apx-legend-position-${position}`);
}
function walk(selector, visit) {
  return selector.map(node => {
    if (node.selectors) node = {...node, selectors:node.selectors.map(s => walk(s, visit))};
    return visit(node);
  });
}
// Include feature and vendor classes declared in CSS, including classes added
// dynamically by charts and controls rather than written in a template.
function cssFiles(dir) {
  return fs.readdirSync(dir, {withFileTypes:true}).flatMap(entry => {
    const file = path.join(dir, entry.name);
    return entry.isDirectory() ? cssFiles(file) : (file.endsWith('.css') ? [file] : []);
  });
}
for (const filename of cssFiles(directory)) {
  transform({filename, code:fs.readFileSync(filename), visitor:{Selector(selector) {
    walk(selector, node => {if(node.type==='class') candidates.add(node.name);return node;});
  }}});
}
const names = [...candidates].sort();
const matches = new Map();
const output = path.join(root, 'static/build/css');
fs.mkdirSync(output, {recursive:true});
for (const file of files) {
  const result = transform({filename:file, code:fs.readFileSync(path.join(directory,file)), minify:true, visitor:{Url(url) {
    if (/^(?:[a-z][a-z0-9+.-]*:|\/|#)/i.test(url.url)) return url;
    return {...url, url:path.posix.relative(path.posix.dirname('build/css/'+file), path.posix.join(path.posix.dirname('css/'+file), url.url))};
  }, Selector(selector) {
    return walk(selector, node => {
      const op = node.operation;
      if(node.type!=='attribute'||node.name!=='class'||op?.operator!=='substring'||op.caseSensitivity!=='case-sensitive'||!op.value||/\s/.test(op.value)) return node;
      if(!matches.has(op.value)) matches.set(op.value, names.filter(name=>name.includes(op.value)));
      const values = matches.get(op.value);
      if(!values.length) return {type:'class',name:'__edify_unused_css_pattern'};
      return {type:'pseudo-class',kind:'is',selectors:values.map(name=>[{type:'class',name}])};
    });
  }}});
  fs.mkdirSync(path.dirname(path.join(output,file)),{recursive:true});
  fs.writeFileSync(path.join(output,file),result.code);
}
fs.writeFileSync(path.join(output,'selectors.json'),JSON.stringify(Object.fromEntries(matches))+'\n');
console.log(`Indexed ${matches.size} class patterns across ${files.length} shared stylesheets.`);
