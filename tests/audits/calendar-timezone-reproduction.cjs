// Read the actual calendar initialization snippet; exercise it without a browser.
// TZ changes only this Node process, never the user's system settings.
const fs = require('node:fs');
const paths = [
  'templates/partials/planning/schedule_drawer.html',
  'templates/partials/planning/schedule_cluster_drawer.html',
  'templates/partials/clusters/planned_date_field.html',
];
let failed = false;
for (const path of paths) {
  const source = fs.readFileSync(path, 'utf8');
  const match = source.match(/let parts = String\(this\.selectedDate\)[\s\S]*?this\.currentMonth = d\.getMonth\(\);/);
  if (!match) throw new Error(`Calendar initialization changed: ${path}`);
  const state = {selectedDate: '2026-09-01'};
  new Function(match[0] + '\n}').call(state);
  const actual = `${state.currentYear}-${String(state.currentMonth+1).padStart(2,'0')}`;
  const passed = actual === '2026-09';
  failed ||= !passed;
  console.log(JSON.stringify({path, timezone:process.env.TZ, selectedDate:state.selectedDate,
                             expectedMonth:'2026-09', actualMonth:actual, passed}));
}
process.exitCode = failed ? 1 : 0;
