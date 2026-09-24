// A saved date opens its own month in every time zone (controls audit F-07,
// 2026-09-14). Each drawer's real initialisation runs in a child process with
// TZ set, so this machine's zone never decides the result.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { spawnSync } = require('node:child_process');

// Drawers whose date is a scripted calendar. None since #122 (b99409a,
// 2026-09-23) put every drawer's date on a native input; a scripted calendar
// that comes back goes here, so its saved month is checked in every zone.
const DRAWERS = [];

// Drawers whose date is a native <input type="date"> (8bb11a1 moved the
// project drawer; #122 the scheduling drawers and the cluster planner, whose
// planned_date_field.html it removed). Its value is a calendar-day string the
// browser shows as-is and never turns into an instant, so no zone can move it
// to another month — as long as no script comes back to parse it.
const NATIVE_DATE_DRAWERS = [
  ['templates/partials/schools/assign_to_project_drawer.html', 'start_date'],
  ['templates/partials/planning/schedule_drawer.html', 'scheduled_date'],
  ['templates/partials/planning/schedule_cluster_drawer.html', 'scheduled_date'],
  ['templates/partials/clusters/cluster_action_planner_drawer.html', 'scheduled_date'],
  ['templates/partials/core_schools/schedule_training_drawer.html', 'scheduled_date'],
  ['templates/partials/core_schools/schedule_visit_drawer.html', 'scheduled_date'],
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

for (const [path, name] of NATIVE_DATE_DRAWERS) {
  test(`${path} keeps its ${name} a native calendar day`, () => {
    const source = fs.readFileSync(path, 'utf8');
    const input = source.match(new RegExp(`<input[^>]*\\bname="${name}"[^>]*>`));
    assert.ok(input, `no ${name} input in ${path}`);
    assert.match(input[0], /\btype="date"/);
    assert.doesNotMatch(
      source,
      /this\.selectedDate/,
      `${path} has a scripted calendar again: move it to DRAWERS so its saved month is checked in every zone`,
    );
  });
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
