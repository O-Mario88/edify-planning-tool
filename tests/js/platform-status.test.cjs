const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
function setup() {
  const handlers = {}, nodes = [];
  function node() {
    return { children: [], attrs: {}, dataset: {},
      setAttribute(k, v) { this.attrs[k] = v; },
      append(...items) { this.children.push(...items); },
      appendChild(item) { nodes.push(item); },
      addEventListener(name, fn) { this[name] = fn; },
      querySelector() { return this.children[0]; },
      remove() { nodes.splice(nodes.indexOf(this), 1); },
    };
  }
  const document = { createElement: node, body: node(),
    getElementById: id => nodes.find(n => n.id === id),
    addEventListener(name, fn) { (handlers[name] ||= []).push(fn); },
  };
  vm.runInNewContext(fs.readFileSync('static/js/platform-status.js', 'utf8'), {
    document, window: { addEventListener() {}, location: { href: 'http://localhost/' } }, navigator: { onLine: true }, URL,
  });
  return { nodes, emit(type, xhr = {status: 0}) { (handlers[type] || []).forEach(fn => fn({type,detail:{xhr}})); } };
}
test('timeouts and connection failures show one dismissible alert without promising rollback', () => {
  const h = setup(); h.emit('htmx:timeout');
  assert.equal(h.nodes.length, 1); assert.equal(h.nodes[0].attrs.role, 'alert');
  assert.match(h.nodes[0].children[0].textContent, /took too long/);
  assert.match(h.nodes[0].children[0].textContent, /Check whether the action completed/);
  h.emit('htmx:sendError'); assert.equal(h.nodes.length, 1);
  assert.match(h.nodes[0].children[0].textContent, /connection was interrupted/);
  h.nodes[0].children[1].click(); assert.equal(h.nodes.length, 0);
});
test('session and capacity errors retain their dedicated recovery UI', () => {
  const h = setup();
  h.emit('htmx:responseError', {status:401});
  h.emit('htmx:responseError', {status:503,getResponseHeader:()=> '5'});
  assert.equal(h.nodes.length, 0);
  h.emit('htmx:responseError', {status:500}); assert.equal(h.nodes.length, 1);
});
