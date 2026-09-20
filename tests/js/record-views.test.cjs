const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');

test('record-views does not convert tables to cards or inject view controls', () => {
  const listeners = {}, controls = [];
  function node(tag = 'SPAN') {
    const classes = new Set();
    return {
      tagName: tag,
      children: [],
      dataset: {},
      attrs: {},
      colSpan: 1,
      rowSpan: 1,
      classList: { add: k => classes.add(k), remove: k => classes.delete(k) },
      setAttribute(k, v) { this.attrs[k] = v; },
      append(...items) { this.children.push(...items); },
      prepend(item) { this.children.unshift(item); item.parent = this; },
      remove() {
        if (this.parent) this.parent.children = this.parent.children.filter(n => n !== this);
        const i = controls.indexOf(this);
        if (i >= 0) controls.splice(i, 1);
      },
      addEventListener(name, fn) { this[name] = fn; },
      querySelectorAll() { return []; },
    };
  }

  const cells = [node('TD'), node('TD'), node('TD')];
  const row = node('TR'); row.cells = cells;
  const head = node('TR'); head.cells = ['School', 'Status', 'Action'].map(text => Object.assign(node('TH'), { textContent: text }));
  const tbody = node('TBODY');
  const table = Object.assign(node('TABLE'), { caption: { textContent: 'Schools' }, tFoot: null });
  const region = { before: n => controls.push(n) };
  table.matches = () => true;
  table.closest = selector => selector === '#main-content' ? {} : region;
  table.querySelectorAll = selector => ({
    ':scope > thead > tr': [head],
    ':scope > tbody > tr': [row],
    ':scope > thead, :scope > tbody': [node('THEAD'), tbody],
    '.edify-record-field-label': [],
  }[selector] || []);

  const document = {
    readyState: 'complete',
    createElement: tag => node(tag.toUpperCase()),
    querySelectorAll: () => [table],
    addEventListener: (name, fn) => listeners[name] = fn,
  };

  vm.runInNewContext(fs.readFileSync('static/js/record-views.js', 'utf8'), { document });

  // Tables must not be given cards view or controls
  assert.equal(controls.length, 0, 'No card controls should be injected');
  assert.equal(table.dataset.recordView, undefined, 'Table must not be set to cards');
});
