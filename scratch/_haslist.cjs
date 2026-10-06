/* Every selector with :has() outside its subject compound, with the subject it
 * ends in (what the browser files in the shared :has() invalidation set). */
const fs = require('node:fs'); const path = require('node:path'); const { transform } = require('lightningcss');
const ROOT = process.env.CSSROOT; const files = [];
(function walk(d) { for (const f of fs.readdirSync(d, { withFileTypes: true })) { const p = path.join(d, f.name); if (f.isDirectory()) walk(p); else if (f.name.endsWith('.css')) files.push(p); } })(ROOT);
const hasIn = (nodes) => nodes.some((n) => n.type === 'pseudo-class' && (n.kind === 'has' || (Array.isArray(n.selectors) && n.selectors.some(hasIn))));
const text = (sel) => transform({ filename: 'x.css', code: Buffer.from('a{color:red}'), minify: true, visitor: { Selector: () => sel } }).code.toString().replace(/\{.*$/s, '');
const rows = [];
for (const file of files) {
  transform({ filename: file, code: fs.readFileSync(file), visitor: { Selector(selector) {
    if (!hasIn(selector)) return selector;
    const compounds = [[]]; for (const node of selector) { if (node.type === 'combinator') compounds.push([]); else compounds[compounds.length - 1].push(node); }
    const subject = compounds[compounds.length - 1]; const nonSubject = compounds.slice(0, -1).some(hasIn);
    if (nonSubject) rows.push({ file: path.relative(ROOT, file), selector: text(selector), subject: text(subject) });
    return selector; } } });
}
const bySubject = {}; for (const r of rows) (bySubject[r.subject] = bySubject[r.subject] || []).push(r);
console.log(`${rows.length} selectors with :has() outside the subject, ${Object.keys(bySubject).length} distinct subjects`);
for (const [subject, list] of Object.entries(bySubject).sort((a, b) => b[1].length - a[1].length)) { console.log(`\n[${list.length}] subject: ${subject.slice(0, 150)}`); for (const r of list.slice(0, Number(process.env.EACH || 2))) console.log(`      ${r.file}: ${r.selector.slice(0, 230)}`); }
