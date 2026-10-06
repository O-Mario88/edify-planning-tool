const { transform } = require('lightningcss');
const css = `
main :is(label, .a, nav a, div.b:is(.c, .d), [role="dialog"], #x, :hover, :is(.e, .f)):not(:is(h1, .t)) > *::before { color: red }
.k:where(.z):nth-child(2n+1 of .q) ~ a:not(.sr-only, .x) + b:has(> c) { color: blue }
@media (min-width: 10px) { .m :is(.n, .o) { color: green } }
.p { & .q { color: pink } }
`;
const seen = [];
const res = transform({ filename: 'x.css', code: Buffer.from(css), minify: true, visitor: { Selector(sel) { seen.push(JSON.stringify(sel)); return sel; } } });
for (const s of seen) console.log(s.slice(0, 1500), '\n');
console.log(res.code.toString());
// can a Selector visitor return several selectors?
const res2 = transform({ filename: 'y.css', code: Buffer.from('.a :is(.b, x, .c) { color: red }'), minify: true, visitor: { Selector(sel) { const i = sel.findIndex((n) => n.type === 'pseudo-class' && n.kind === 'is'); if (i < 0) return sel; return sel[i].selectors.map((alt) => sel.slice(0, i).concat([{ type: 'pseudo-class', kind: 'where', selectors: [alt] }, { type: 'pseudo-class', kind: 'is', selectors: [[{ type: 'universal' }], [{ type: 'class', name: '_' }]] }], sel.slice(i + 1))); } } });
console.log(res2.code.toString());
