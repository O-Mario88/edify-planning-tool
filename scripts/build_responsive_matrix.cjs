#!/usr/bin/env node
// Builds the responsive audit matrix from the evidence the responsive-matrix
// crawl writes (test-results/responsive-matrix/<label>/<role>.json):
//
//   node scripts/build_responsive_matrix.cjs [before-label] [after-label]
//
// Defaults: before="before", after="after". With only one label present the
// matrix shows that run alone. Writes docs/responsive-audit-matrix.json and
// docs/responsive-audit-matrix.md.
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '..');
const [beforeLabel = 'before', afterLabel = 'after'] = process.argv.slice(2);
const evidenceRoot = path.join(root, 'test-results', 'responsive-matrix');
const inventory = JSON.parse(
  fs.readFileSync(path.join(root, 'docs', 'platform-page-inventory.json'), 'utf8')
);

const WRAP_KEYS = ['buttons', 'tabs', 'badges', 'navigation', 'tableHeaders', 'tableCells'];
const REPORT_KEYS = [...WRAP_KEYS, 'silentTruncation', 'tinyText', 'tinyChartText', 'smallTargets'];
const DEFECT_IDS = {
  documentOverflow: 'RSP-01 page overflow',
  mainOverflow: 'RSP-02 workspace overflow',
  unscrolled: 'RSP-03 table without scroll region',
  buttons: 'RSP-04 wrapped button label',
  tabs: 'RSP-05 wrapped tab label',
  badges: 'RSP-06 wrapped status badge',
  navigation: 'RSP-07 wrapped navigation label',
  tableHeaders: 'RSP-08 wrapped table header',
  tableCells: 'RSP-09 wrapped table cell',
  silentTruncation: 'RSP-10 truncated without full text',
  tinyText: 'RSP-11 text below 12px',
  tinyChartText: 'RSP-13 chart or map label below 12px',
  smallTargets: 'RSP-12 target below 24px',
};
const CORRECTIONS = {
  documentOverflow: 'Workspace overflow guard; component min-widths inside scroll regions',
  mainOverflow: 'Workspace overflow guard; component min-widths inside scroll regions',
  unscrolled: 'Shared table scroll region (edify-table-scroll-region)',
  buttons: 'Shared one-line control rule',
  tabs: 'Shared one-line tab rule; scrolling tab rail',
  badges: 'Shared one-line badge rule',
  navigation: 'One-line navigation labels',
  tableHeaders: 'Shared one-line table rule',
  tableCells: 'Shared one-line table rule',
  silentTruncation: 'Title or accessible name on truncated values',
  tinyText: 'Type tokens (12px floor)',
  tinyChartText: 'Shared chart typography (12px floor)',
  smallTargets: 'Control height tokens',
};
const BAND_ORDER = ['mobile', 'tablet', 'desktop'];
const GRADE_RANK = { Pass: 0, Partial: 1, Fail: 2 };

function load(label) {
  const dir = path.join(evidenceRoot, label);
  if (!fs.existsSync(dir)) return null;
  const records = [];
  for (const file of fs.readdirSync(dir).filter(name => name.endsWith('.json'))) {
    const data = JSON.parse(fs.readFileSync(path.join(dir, file), 'utf8'));
    for (const record of data.records) records.push({ ...record, role: data.role });
  }
  return records;
}

function summarise(records) {
  // Keyed by route + role: one row of the matrix per page each role opens.
  const pages = new Map();
  for (const record of records) {
    const key = `${record.route}\u0000${record.role}`;
    if (!pages.has(key)) {
      pages.set(key, { route: record.route, role: record.role, title: record.title, status: record.status, bands: {}, defects: {}, error: record.error });
    }
    const page = pages.get(key);
    if (record.error || !record.band) continue;
    const band = page.bands[record.band] || (page.bands[record.band] = 'Pass');
    if (GRADE_RANK[record.grade] > GRADE_RANK[band]) page.bands[record.band] = record.grade;
    const count = (name, value) => {
      if (!value) return;
      page.defects[name] = page.defects[name] || { count: 0, geometries: new Set(), examples: new Set() };
      page.defects[name].count = Math.max(page.defects[name].count, value.count ?? 1);
      page.defects[name].geometries.add(record.geometry);
      (value.examples || []).forEach(example => page.defects[name].examples.size < 3 && page.defects[name].examples.add(example));
    };
    if (record.documentOverflow) count('documentOverflow', { count: 1 });
    if (record.mainOverflow) count('mainOverflow', { count: 1 });
    if (record.tables?.unscrolled?.length) count('unscrolled', { count: record.tables.unscrolled.length, examples: record.tables.unscrolled });
    for (const key of REPORT_KEYS) if (record[key]?.count) count(key, record[key]);
  }
  return pages;
}

function totals(records) {
  const byGeometry = {};
  const byKey = Object.fromEntries([...REPORT_KEYS, 'documentOverflow', 'mainOverflow', 'unscrolled'].map(key => [key, 0]));
  for (const record of records) {
    if (!record.geometry) continue;
    const row = byGeometry[record.geometry] || (byGeometry[record.geometry] = { Pass: 0, Partial: 0, Fail: 0 });
    row[record.grade] += 1;
    for (const key of REPORT_KEYS) byKey[key] += record[key]?.count || 0;
    if (record.documentOverflow) byKey.documentOverflow += 1;
    if (record.mainOverflow) byKey.mainOverflow += 1;
    byKey.unscrolled += record.tables?.unscrolled?.length || 0;
  }
  return { byGeometry, byKey };
}

const before = load(beforeLabel);
const after = load(afterLabel);
const current = after || before;
if (!current) {
  console.error(`No evidence under ${evidenceRoot}/{${beforeLabel},${afterLabel}}. Run the responsive-matrix crawl first.`);
  process.exit(1);
}

const surfaces = new Map(inventory.pages.map(surface => [surface.route, surface]));
const beforePages = before ? summarise(before) : new Map();
const currentPages = summarise(current);

const rows = [...currentPages.values()].sort((a, b) => a.route.localeCompare(b.route) || a.role.localeCompare(b.role)).map(page => {
  const surface = surfaces.get(page.route) || {};
  const previous = beforePages.get(`${page.route}\u0000${page.role}`);
  const findings = Object.keys(page.defects).map(key => DEFECT_IDS[key]);
  const blocking = Object.keys(page.defects).filter(key => !['silentTruncation', 'tinyText', 'tinyChartText', 'smallTargets'].includes(key));
  const hadBlocking = previous ? Object.keys(previous.defects).some(key => !['silentTruncation', 'tinyText', 'tinyChartText', 'smallTargets'].includes(key)) : null;
  let status = blocking.length ? 'Pending' : 'Verified';
  if (!blocking.length && hadBlocking) status = 'Fixed';
  return {
    page: page.title?.replace(/ · Edify$/, '') || surface.page_title || page.route,
    route: page.route,
    module: surface.app || surface.module || '',
    role: page.role,
    roles: surface.role_access || [],
    pageType: surface.page_type || '',
    header: surface.header_variant || '',
    table: surface.table_pattern || '',
    mobile: page.bands.mobile || (page.error ? 'Error' : '—'),
    tablet: page.bands.tablet || (page.error ? 'Error' : '—'),
    desktop: page.bands.desktop || (page.error ? 'Error' : '—'),
    before: previous ? Object.fromEntries(BAND_ORDER.map(band => [band, previous.bands[band] || '—'])) : null,
    findings,
    defects: Object.fromEntries(Object.entries(page.defects).map(([key, value]) => [key, {
      count: value.count,
      geometries: [...value.geometries],
      examples: [...value.examples],
    }])),
    correction: [...new Set(Object.keys(page.defects).map(key => CORRECTIONS[key]))],
    status,
  };
});

const summary = {
  generated: new Date().toISOString(),
  beforeLabel: before ? beforeLabel : null,
  afterLabel: after ? afterLabel : null,
  pages: new Set(rows.map(row => row.route)).size,
  rolePages: rows.length,
  roles: [...new Set(rows.map(row => row.role))].sort(),
  before: before ? totals(before) : null,
  current: totals(current),
  status: rows.reduce((acc, row) => ({ ...acc, [row.status]: (acc[row.status] || 0) + 1 }), {}),
};

fs.writeFileSync(
  path.join(root, 'docs', 'responsive-audit-matrix.json'),
  JSON.stringify({ summary, rows }, null, 1) + '\n'
);

const md = [];
const cell = value => String(value ?? '').replace(/\|/g, '\\|');
md.push('# Responsive audit matrix', '');
md.push('Generated by `scripts/build_responsive_matrix.cjs` from the `e2e/responsive-matrix.spec.js` crawl: every argument-free page each seeded role can open, measured at the thirteen geometries of the responsive standard (320×568 to 2560×1440). Phones and tablets are measured in a touch context; laptops and wider in a desktop context. Each page loads once per context and is then resized through the geometries, so resize and orientation changes are exercised too.', '');
md.push(`- Pages: **${summary.pages}** routes, **${summary.rolePages}** role/page pairs, roles: ${summary.roles.join(', ')}.`);
md.push(`- Evidence: ${summary.beforeLabel ? `\`${summary.beforeLabel}\` (before) and ` : ''}\`${summary.afterLabel || summary.beforeLabel}\` (${summary.afterLabel ? 'after' : 'current'}).`);
md.push(`- Row status: ${Object.entries(summary.status).map(([key, value]) => `${key} ${value}`).join(' · ')}.`, '');
md.push('Grades per geometry: **Fail** = the page or its workspace scrolls sideways, or a table overflows with no scroll region; **Partial** = a button, tab, badge, navigation label, table header or table cell wraps; **Pass** = neither. A band (mobile 320–430, tablet 768–1024 including square, desktop 1280–2560) takes its worst geometry.', '');

md.push('## Defects by class (sum over every page × geometry)', '');
const keys = ['documentOverflow', 'mainOverflow', 'unscrolled', ...REPORT_KEYS];
md.push(`| Defect | ${summary.before ? 'Before | ' : ''}${summary.afterLabel ? 'After' : 'Current'} |`);
md.push(`|---|${summary.before ? '---:|' : ''}---:|`);
for (const key of keys) {
  md.push(`| ${DEFECT_IDS[key]} | ${summary.before ? `${summary.before.byKey[key]} | ` : ''}${summary.current.byKey[key]} |`);
}
md.push('');

md.push('## Grades by geometry (role/page pairs)', '');
md.push(`| Geometry | ${summary.before ? 'Before Pass / Partial / Fail | ' : ''}${summary.afterLabel ? 'After' : 'Current'} Pass / Partial / Fail |`);
md.push(`|---|${summary.before ? '---|' : ''}---|`);
for (const geometry of Object.keys(summary.current.byGeometry)) {
  const now = summary.current.byGeometry[geometry];
  const was = summary.before?.byGeometry[geometry];
  md.push(`| ${geometry} | ${was ? `${was.Pass} / ${was.Partial} / ${was.Fail} | ` : ''}${now.Pass} / ${now.Partial} / ${now.Fail} |`);
}
md.push('');

md.push('## Page matrix', '');
md.push('| Page | Route | Module | Role | Type | Mobile | Tablet | Desktop | Findings | Correction | Status |');
md.push('|---|---|---|---|---|---|---|---|---|---|---|');
for (const row of rows) {
  const band = key => row.before && row.before[key] !== row[key] ? `${row.before[key]} → ${row[key]}` : row[key];
  md.push(`| ${cell(row.page)} | \`${cell(row.route)}\` | ${cell(row.module)} | ${row.role} | ${cell(row.pageType)} | ${band('mobile')} | ${band('tablet')} | ${band('desktop')} | ${cell(row.findings.join('; '))} | ${cell(row.correction.join('; '))} | ${row.status} |`);
}
md.push('');

md.push('## Remaining examples', '');
for (const row of rows.filter(r => r.status === 'Pending')) {
  const lines = Object.entries(row.defects)
    .filter(([key]) => !['silentTruncation', 'tinyText', 'tinyChartText', 'smallTargets'].includes(key))
    .map(([key, value]) => `${DEFECT_IDS[key]} at ${value.geometries.join(', ')}${value.examples.length ? ` — ${value.examples.map(e => `“${e}”`).join(', ')}` : ''}`);
  md.push(`- \`${row.route}\` (${row.role}): ${lines.join('; ')}`);
}
md.push('');

fs.writeFileSync(path.join(root, 'docs', 'responsive-audit-matrix.md'), md.join('\n'));
console.log(`Wrote docs/responsive-audit-matrix.{json,md}: ${summary.rolePages} role/page pairs, status ${JSON.stringify(summary.status)}`);
