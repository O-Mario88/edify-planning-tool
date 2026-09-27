// Where a dropdown opens (static/js/top-layer.js). Owner, 2026-09-27: "NO
// action button dropdown drawer opens from a fixed position. they have to
// open where the button is" and "make sure the dropdown is actually dropping
// down (the drawer is down not up on top of the action button)".
const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');

const layer = require(path.resolve(__dirname, '../../static/js/top-layer.js'));

const phone = { width: 375, height: 760 };
const menu = { width: 176, height: 146 };
const button = (left, top, width = 90, height = 40) => ({ left, top, right: left + width, bottom: top + height });

test('a menu opens down from its button, right edges together', () => {
  const at = button(270, 200);
  const spot = layer.plan(at, menu, phone, { align: 'end' });
  assert.equal(spot.top, at.bottom + 4);
  assert.equal(spot.left + menu.width, at.right);
  assert.equal(spot.maxHeight, null);
  assert.equal(spot.need, 0);
});

test('it never opens above the button, however little room is below', () => {
  for (const top of [500, 600, 650, 700, 716]) {
    const at = button(270, top);
    const spot = layer.plan(at, menu, phone, { align: 'end' });
    assert.ok(spot.top >= at.bottom, `button at ${top}: the menu starts under it`);
    const room = Math.max(0, phone.height - at.bottom - 4 - 8);
    if (menu.height > room) {
      // The opener scrolls the page up by `need`; what still does not fit
      // scrolls inside the menu, which ends inside the window.
      assert.equal(spot.need, Math.ceil(menu.height - room));
      assert.equal(spot.maxHeight, Math.floor(room));
      if (room > 0) assert.ok(spot.top + spot.maxHeight <= phone.height - 8);
    }
  }
});

test('left-aligned menus start at the button', () => {
  const at = button(40, 100);
  assert.equal(layer.plan(at, menu, phone, { align: 'start' }).left, 40);
});

test('a button near the left edge takes its left edge instead of leaving the screen', () => {
  const at = button(23, 100, 116);
  const spot = layer.plan(at, menu, phone, { align: 'end' });
  assert.equal(spot.left, 23);
});

test('a button near the right edge takes its right edge instead of leaving the screen', () => {
  const at = button(300, 100, 60);
  const spot = layer.plan(at, menu, phone, { align: 'start' });
  assert.equal(spot.left + menu.width, at.right);
});

test('a panel wider than both sides stays inside the window', () => {
  const wide = { width: 340, height: 100 };
  const spot = layer.plan(button(150, 100, 60), wide, phone, { align: 'end' });
  assert.ok(spot.left >= 8);
  assert.ok(spot.left + wide.width <= phone.width - 8);
});

test('the stylesheet reader splits selector lists only at the top level', () => {
  assert.deepEqual(layer.splitSelectors('.a, main :is(.b, .c) > .d,[data-x="1,2"]'), [
    '.a',
    'main :is(.b, .c) > .d',
    '[data-x="1,2"]',
  ]);
});
