/* Tick boxes that act on a group (owner, 2026-10-05).
 * Select all: a checkbox with `data-select-all` ticks every enabled, visible
 * checkbox in its scope ([data-select-scope], else its table, fieldset or
 * form); a selector as its value narrows which. Each box gets a change event.
 * Activity bar: ticking `input[data-activity-pick]` shows [data-activity-bar]
 * with the ticked ids; one activity drawn twice ticks as one.
 * Rationale: docs/ui-components.md, "Tick boxes". */
(function () {
  'use strict';
  if (window.EdifyGroupSelect) return;
  var doc = document, busy = false;
  var PICK = 'input[data-activity-pick]', ALL = 'input[data-select-all]';

  function each(root, selector, fn) {
    Array.prototype.forEach.call(root.querySelectorAll(selector), fn);
  }

  function members(master) {
    var scope = master.closest('[data-select-scope]') || master.closest('table, fieldset, form') || doc;
    var found = [];
    each(scope, master.getAttribute('data-select-all') || 'input[type="checkbox"]', function (box) {
      if (box !== master && box.type === 'checkbox' && !box.disabled &&
          !box.hasAttribute('data-select-all') && box.getClientRects().length) found.push(box);
    });
    return found;
  }

  function set(box, on) {
    if (box.checked === on) return;
    box.checked = on;
    box.dispatchEvent(new Event('change', { bubbles: true }));
  }

  function picked() {
    var ids = [];
    each(doc, PICK + ':checked', function (box) {
      if (ids.indexOf(box.value) < 0) ids.push(box.value);
    });
    return ids;
  }

  function settle() {
    var states = [];
    each(doc, ALL, function (master) {
      var boxes = members(master);
      var on = boxes.filter(function (box) { return box.checked; }).length;
      states.push([master, on > 0 && on === boxes.length, on > 0 && on < boxes.length]);
    });
    states.forEach(function (state) {
      state[0].checked = state[1];
      state[0].indeterminate = state[2];
    });
    var bar = doc.querySelector('[data-activity-bar]');
    if (!bar) return;
    var ids = picked();
    bar.hidden = !ids.length;
    each(bar, '[data-activity-count]', function (node) { node.textContent = ids.length; });
    each(bar, '[data-activity-noun]', function (node) {
      node.textContent = ids.length === 1 ? 'activity selected' : 'activities selected';
    });
    each(bar, 'input[name="ids"]', function (input) { input.value = ids.join(','); });
  }

  function during(fn) {
    busy = true;
    try { fn(); } finally { busy = false; }
    settle();
  }

  // The same activity in the month grid and in the agenda is one tick. Each
  // twin hears of it too, so its row's selected mark follows.
  function twin(source) {
    each(doc, PICK, function (box) {
      if (box !== source && box.value === source.value) set(box, source.checked);
    });
  }

  doc.addEventListener('change', function (event) {
    var box = event.target;
    if (busy || !box || box.type !== 'checkbox') return;
    during(function () {
      var all = box.hasAttribute('data-select-all');
      var changed = all ? members(box) : [box];
      if (all) changed.forEach(function (member) { set(member, box.checked); });
      changed.forEach(function (member) {
        if (member.hasAttribute('data-activity-pick')) twin(member);
      });
    });
  });

  doc.addEventListener('click', function (event) {
    if (event.target.closest && event.target.closest('[data-activity-clear]')) {
      during(function () { each(doc, PICK + ':checked', function (box) { set(box, false); }); });
    } else if (doc.querySelector(ALL)) {
      // A "Clear" that empties an Alpine list unticks boxes without an event.
      setTimeout(settle, 0);
    }
  });

  doc.addEventListener('htmx:afterSettle', settle);
  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', settle);
  else settle();

  window.EdifyGroupSelect = Object.freeze({ settle: settle, picked: picked });
})();
