// A saved date opens its own month in every time zone (controls audit F-07,
// 2026-09-14). Each drawer's real initialisation runs in a child process with
// TZ set, so this machine's zone never decides the result.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { spawnSync } = require('node:child_process');

const DRAWERS = [
  'templates/partials/planning/schedule_drawer.html',
  'templates/partials/planning/schedule_cluster_drawer.html',
  'templates/partials/clusters/planned_date_field.html',
  'templates/partials/core_schools/schedule_training_drawer.html',
  'templates/partials/core_schools/schedule_visit_drawer.html',
  'templates/partials/schools/assign_to_project_drawer.html',
];

function openMonth(path, zone, date) {
  const source = fs.readFileSync(path, 'utf8');
  const match = source.match(/let parts = String\(this\.selectedDate\)[\s\S]*?this\.currentMonth = d\.getMonth\(\);\s*\}/);
  assert.ok(match, `calendar initialisation not found in ${path}`);
  const script = `const s={selectedDate:${JSON.stringify(date)}};(function(){${match[0]}}).call(s);` +
    `process.stdout.write(s.currentYear+'-'+String(s.currentMonth+1).padStart(2,'0'));`;
  const run = spawnSync(process.execPath, ['-e', script], { env: { ...process.env, TZ: zone }, encoding: 'utf8' });
  assert.equal(run.status, 0, run.stderr);
  return run.stdout;
}

for (const path of DRAWERS) {
  test(`${path} opens the saved month east, west and at UTC`, () => {
    for (const zone of ['America/Guatemala', 'UTC', 'Africa/Kampala', 'Pacific/Kiritimati']) {
      assert.equal(openMonth(path, zone, '2026-09-01'), '2026-09', zone);
      assert.equal(openMonth(path, zone, '2028-02-29'), '2028-02', zone);
      assert.equal(openMonth(path, zone, '2027-01-01'), '2027-01', zone);
    }
  });
}
