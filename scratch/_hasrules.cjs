/* List every selector whose :has() sits on an ancestor rather than on the element being styled.
 * Such a rule makes the browser restyle that ancestor's whole subtree whenever anything inside it changes. */
const fs = require('node:fs'); const path = require('node:path'); const { transform } = require('lightningcss');
const root = path.resolve(__dirname, '..');
const files = ['build/css/main.css', 'build/css/design-system.css', 'build/css/components.css', 'css/components/sidebar.css', 'css/components/mobile-shell.css', 'build/css/components/mobile-patterns.css', 'build/css/pages.css', 'build/css/drawers.css', 'css/app.css', 'build/css/platform.css', 'build/css/consistency.css', 'build/css/components/mobile-micro-ux.css', 'css/components/platform-status.css', 'css/form-refinement.css', 'build/css/components/responsive-system.css', 'build/css/components/interactions.css'];
const str = (sel) => sel.map((n) => { if (n.type === 'combinator') return n.value === 'descendant' ? ' ' : n.value === 'child' ? ' > ' : n.value === 'next-sibling' ? ' + ' : ' ~ '; if (n.type === 'class') return '.' + n.name; if (n.type === 'id') return '#' + n.name; if (n.type === 'type') return n.name; if (n.type === 'universal') return '*'; if (n.type === 'attribute') return `[${n.name}${n.operation ? '…' : ''}]`; if (n.type === 'pseudo-class') return ':' + n.kind + (n.selectors ? '(' + n.selectors.slice(0, 3).map(str).join(', ') + (n.selectors.length > 3 ? `, …+${n.selectors.length - 3}` : '') + ')' : ''); if (n.type === 'pseudo-element') return '::' + n.kind; if (n.type === 'nesting') return '&'; return '?'; }).join('');
const hasIn = (nodes) => nodes.some((n) => n.type === 'pseudo-class' && (n.kind === 'has' || (n.selectors && n.selectors.some((s) => hasIn(s)))));
const rows = [];
for (const file of files) { const full = path.join(root, 'static', file); if (!fs.existsSync(full)) continue;
  transform({ filename: file, code: fs.readFileSync(full), visitor: { Selector(sel) {
    const compounds = [[]]; for (const n of sel) { if (n.type === 'combinator') compounds.push([]); else compounds[compounds.length - 1].push(n); }
    const idx = compounds.map((c, i) => hasIn(c) ? i : -1).filter((i) => i >= 0);
    if (!idx.length) return; const nonSubject = idx.some((i) => i < compounds.length - 1);
    rows.push({ file: file.split('/').pop(), nonSubject, first: str(compounds[0]).slice(0, 60), sel: str(sel) }); } } }); }
const ns = rows.filter((r) => r.nonSubject); console.log(`selectors using :has(): ${rows.length}; with :has() on an ancestor (subtree invalidation): ${ns.length}`);
const byFile = {}; for (const r of ns) byFile[r.file] = (byFile[r.file] || 0) + 1; console.log(JSON.stringify(byFile));
const high = ns.filter((r) => /^(main|body|html|:root|\.edify-workspace|\.app-shell|#main-content|:is\(main|\*|:where\(\*)/.test(r.first) || /^(main|body)/.test(r.sel));
console.log(`\nof those, anchored on a page-level ancestor (${high.length}):`);
for (const r of high.slice(0, 60)) console.log(`  [${r.file}] ${r.sel.slice(0, 230)}`);
console.log(`\nother ancestor-:has() selectors (first 40 of ${ns.length - high.length}):`);
for (const r of ns.filter((r) => !high.includes(r)).slice(0, 40)) console.log(`  [${r.file}] ${r.sel.slice(0, 200)}`);
