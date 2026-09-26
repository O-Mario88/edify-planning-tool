// The Edify calendar (static/js/date-picker.js) reads every date field's value.
// A date-only value is a calendar day, never an instant: it must open its own
// month and show its own day in every time zone (controls audit F-07,
// 2026-09-14). Each zone runs in a child process with TZ set, so this
// machine's zone never decides the result.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const SCRIPT = path.resolve(__dirname, '../../static/js/date-picker.js');
const api = require(SCRIPT);
const ZONES = ['America/Guatemala', 'UTC', 'Africa/Kampala', 'Pacific/Kiritimati'];

function inZone(zone, expression) {
  const script = `const api = require(${JSON.stringify(SCRIPT)}); process.stdout.write(JSON.stringify(${expression}));`;
  const run = spawnSync(process.execPath, ['-e', script], { env: { ...process.env, TZ: zone }, encoding: 'utf8' });
  assert.equal(run.status, 0, run.stderr);
  return JSON.parse(run.stdout);
}

test('a saved date opens its own month east, west and at UTC', () => {
  for (const zone of ZONES) {
    for (const [value, month] of [['2026-09-01', '2026-09'], ['2028-02-29', '2028-02'], ['2027-01-01', '2027-01']]) {
      const day = inZone(zone, `api.openingDay(${JSON.stringify(value)})`);
      assert.equal(`${day.y}-${String(day.m).padStart(2, '0')}`, month, `${value} in ${zone}`);
      assert.equal(inZone(zone, `api.toIso(api.openingDay(${JSON.stringify(value)}))`), value, zone);
    }
  }
});

test('the field shows the day it holds in every zone', () => {
  for (const zone of ZONES) {
    assert.equal(inZone(zone, "api.shortLabel(api.parseIso('2026-09-01'))"), 'Sep 1, 2026', zone);
    assert.equal(inZone(zone, "api.longLabel(api.parseIso('2026-09-01'))"), 'Tuesday, September 1, 2026', zone);
  }
});

test('only real calendar days are read', () => {
  assert.deepEqual(api.parseIso('2028-02-29'), { y: 2028, m: 2, d: 29 });
  assert.equal(api.parseIso('2027-02-29'), null);
  assert.equal(api.parseIso('2026-13-01'), null);
  assert.equal(api.parseIso('2026-04-31'), null);
  assert.equal(api.parseIso(''), null);
  assert.equal(api.parseIso('06/10/2026'), null);
});

test('a month is six Sunday-first weeks with blanks around it', () => {
  const cells = api.monthCells(2026, 9);
  assert.equal(cells.length, 42);
  // 1 September 2026 is a Tuesday.
  assert.deepEqual(cells.slice(0, 3), [null, null, { y: 2026, m: 9, d: 1 }]);
  assert.equal(cells.filter(Boolean).length, 30);
  assert.equal(cells.filter(Boolean).at(-1).d, 30);
});

test('stepping by month keeps the day inside the shorter month', () => {
  assert.deepEqual(api.addMonths({ y: 2026, m: 1, d: 31 }, 1), { y: 2026, m: 2, d: 28 });
  assert.deepEqual(api.addMonths({ y: 2028, m: 3, d: 31 }, -1), { y: 2028, m: 2, d: 29 });
  assert.deepEqual(api.addMonths({ y: 2026, m: 12, d: 15 }, 1), { y: 2027, m: 1, d: 15 });
  assert.deepEqual(api.addDays({ y: 2026, m: 12, d: 31 }, 1), { y: 2027, m: 1, d: 1 });
});

test('an empty field opens on today, kept inside its min and max', () => {
  const now = new Date(2026, 8, 26);
  assert.deepEqual(api.openingDay('', '', '', now), { y: 2026, m: 9, d: 26 });
  assert.deepEqual(api.openingDay('', '2026-10-05', '', now), { y: 2026, m: 10, d: 5 });
  assert.deepEqual(api.openingDay('', '', '2026-08-31', now), { y: 2026, m: 8, d: 31 });
  assert.equal(api.within({ y: 2026, m: 10, d: 4 }, api.parseIso('2026-10-05'), null), false);
  assert.equal(api.within({ y: 2026, m: 10, d: 5 }, api.parseIso('2026-10-05'), null), true);
});
