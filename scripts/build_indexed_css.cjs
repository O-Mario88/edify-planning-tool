/* Compile legacy class-substring selectors into class-indexed selectors.
 * :is(.a,.b) has the same specificity as [class*="…"]. Enumerate candidates
 * strictly from genuine CSS declarations, template class attributes, and frontend JS,
 * rather than scanning arbitrary Python words. Human-editable styles stay in css/;
 * static/build/css/ is generated and must be rebuilt when classes or styles change.
 */
const fs = require('node:fs');
const path = require('node:path');
const { transform } = require('lightningcss');

const root = path.resolve(__dirname, '..');
const directory = path.join(root, 'static/css');
const files = [
  'main.css',
  'design-system.css',
  'components.css',
  'pages.css',
  'platform.css',
  'consistency.css',
  'drawers.css',
  'components/mobile-micro-ux.css',
  'components/interactions.css',
  'components/mobile-patterns.css'
];

const candidates = new Set();
const validClassRegex = /^[a-zA-Z_][a-zA-Z0-9_\-]*$/;

// 1. Include classes declared across CSS stylesheets
function cssFiles(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const file = path.join(dir, entry.name);
    return entry.isDirectory() ? cssFiles(file) : (file.endsWith('.css') ? [file] : []);
  });
}

function walk(selector, visit) {
  return selector.map(node => {
    if (node.selectors) node = { ...node, selectors: node.selectors.map(s => walk(s, visit)) };
    return visit(node);
  });
}

for (const filename of cssFiles(directory)) {
  transform({
    filename,
    code: fs.readFileSync(filename),
    visitor: {
      Selector(selector) {
        walk(selector, node => {
          if (node.type === 'class' && validClassRegex.test(node.name)) {
            candidates.add(node.name);
          }
          return node;
        });
      }
    }
  });
}

// 2. Extract genuine classes from HTML template class attributes
function walkHtml(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const file = path.join(dir, entry.name);
    return entry.isDirectory() ? walkHtml(file) : (file.endsWith('.html') ? [file] : []);
  });
}

const classAttrRegex = /(?:class|:class)=['\"]([^'\"]+)['\"]/g;
for (const file of walkHtml(path.join(root, 'templates'))) {
  const content = fs.readFileSync(file, 'utf8');
  let match;
  while ((match = classAttrRegex.exec(content)) !== null) {
    const tokens = match[1].replace(/[{}:?,()'\"]/g, ' ').split(/\s+/);
    for (const token of tokens) {
      if (token && validClassRegex.test(token) && !token.startsWith('{%') && !token.startsWith('{{')) {
        candidates.add(token);
      }
    }
  }
}

// 3. Extract classes from frontend JavaScript classList calls
function walkJs(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const file = path.join(dir, entry.name);
    return entry.isDirectory() ? walkJs(file) : (file.endsWith('.js') ? [file] : []);
  });
}

const classListRegex = /(?:classList\.(?:add|toggle|remove|contains)|\.className\s*[\+\=]=)\s*\(?['\"]([^'\"]+)['\"]/g;
for (const file of walkJs(path.join(root, 'static/js'))) {
  const content = fs.readFileSync(file, 'utf8');
  let match;
  while ((match = classListRegex.exec(content)) !== null) {
    match[1].split(/\s+/).forEach(token => {
      if (token && validClassRegex.test(token)) candidates.add(token);
    });
  }
}

// 4. Dynamic badge/color strings from apps/ Python files
function walkPy(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(entry => {
    const file = path.join(dir, entry.name);
    return entry.isDirectory() ? walkPy(file) : (file.endsWith('.py') ? [file] : []);
  });
}

const pyStringRegex = /['\"]([a-zA-Z0-9_\-]+)['\"]/g;
const knownPrefixes = ['bg-', 'text-', 'border-', 'pill-', 'badge-', 'btn-', 'sp-', 'spa-', 'spp-', 'mp-', 'ia-', 'ad-', 'kpi-', 'card-'];
for (const file of walkPy(path.join(root, 'apps'))) {
  const content = fs.readFileSync(file, 'utf8');
  let match;
  while ((match = pyStringRegex.exec(content)) !== null) {
    const token = match[1];
    if (knownPrefixes.some(prefix => token.startsWith(prefix)) && validClassRegex.test(token)) {
      candidates.add(token);
    }
  }
}

// 5. FullCalendar and ApexCharts runtime class names
for (const view of ['dayGridMonth', 'timeGridWeek', 'listMonth']) {
  candidates.add(`fc-${view}-button`);
  candidates.add(`fc-${view}-view`);
}
for (const position of ['top', 'right', 'bottom', 'left']) {
  candidates.add(`apx-legend-position-${position}`);
}

const names = [...candidates].sort();
const matches = new Map();
const output = path.join(root, 'static/build/css');
fs.mkdirSync(output, { recursive: true });

for (const file of files) {
  const result = transform({
    filename: file,
    code: fs.readFileSync(path.join(directory, file)),
    minify: true,
    visitor: {
      Url(url) {
        if (/^(?:[a-z][a-z0-9+.-]*:|\/|#)/i.test(url.url)) return url;
        return {
          ...url,
          url: path.posix.relative(
            path.posix.dirname('build/css/' + file),
            path.posix.join(path.posix.dirname('css/' + file), url.url)
          )
        };
      },
      Selector(selector) {
        return walk(selector, node => {
          const op = node.operation;
          if (
            node.type === 'attribute' &&
            node.name === 'class' &&
            op?.operator === 'includes' &&
            op.caseSensitivity === 'case-sensitive' &&
            op.value &&
            !/\s/.test(op.value)
          ) {
            return { type: 'class', name: op.value };
          }
          if (
            node.type !== 'attribute' ||
            node.name !== 'class' ||
            op?.operator !== 'substring' ||
            op.caseSensitivity !== 'case-sensitive' ||
            !op.value ||
            /\s/.test(op.value)
          ) {
            return node;
          }
          if (!matches.has(op.value)) {
            matches.set(op.value, names.filter(name => name.includes(op.value)));
          }
          const values = matches.get(op.value);
          if (!values.length) return { type: 'class', name: '__edify_unused_css_pattern' };
          return {
            type: 'pseudo-class',
            kind: 'is',
            selectors: values.map(name => [{ type: 'class', name }])
          };
        });
      }
    }
  });

  fs.mkdirSync(path.dirname(path.join(output, file)), { recursive: true });
  fs.writeFileSync(path.join(output, file), result.code);
}

fs.writeFileSync(path.join(output, 'selectors.json'), JSON.stringify(Object.fromEntries(matches)) + '\n');
console.log(`Indexed ${matches.size} class patterns across ${files.length} shared stylesheets with ${names.length} genuine CSS classes.`);
