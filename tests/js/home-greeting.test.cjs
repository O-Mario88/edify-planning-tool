// The greeting follows the phone's own clock (owner, 2026-10-24: "if the app
// is opened in afternoon it should not again say good morning"). The server
// writes it once when the page is made; an app left open since the morning,
// or a page brought back from the back/forward cache, is corrected as soon
// as it is shown again (static/js/dashboard-greeting.js, on Home and the
// CCEO dashboard).
const { test } = require('node:test');
const assert = require('node:assert/strict');

const { greetingFor, localDay } = require('../../static/js/dashboard-greeting.js');

const at = (hour, minute = 0, day = 24) => new Date(2026, 9, day, hour, minute);

function component(options, startedAt) {
  global.window = { setInterval: () => 1, clearInterval: () => {}, location: { reload() {} } };
  global.document = { addEventListener() {}, removeEventListener() {}, visibilityState: 'visible' };
  const { edifyGreeting } = require('../../static/js/dashboard-greeting.js');
  const greeting = edifyGreeting(options);
  greeting.now = () => startedAt;
  greeting.init();
  return greeting;
}

test('the greeting follows the local hour, as the server words it', () => {
  assert.equal(greetingFor(at(0)), 'Good morning');
  assert.equal(greetingFor(at(11, 59)), 'Good morning');
  assert.equal(greetingFor(at(12)), 'Good afternoon');
  assert.equal(greetingFor(at(16, 59)), 'Good afternoon');
  assert.equal(greetingFor(at(17)), 'Good evening');
  assert.equal(greetingFor(at(23, 59)), 'Good evening');
});

test('a page made in the morning says good afternoon once shown after noon', () => {
  const greeting = component({}, at(8));
  assert.equal(greeting.text, 'Good morning');
  greeting.now = () => at(14, 5);
  greeting.update();
  assert.equal(greeting.text, 'Good afternoon');
});

test('Home opened yesterday is made again, so its figures are today’s', () => {
  const greeting = component({ reloadOnNewDay: true }, at(21));
  let reloaded = 0;
  window.location.reload = () => { reloaded += 1; };
  greeting.now = () => at(7, 30, 25);
  greeting.update();
  assert.equal(reloaded, 1);
  assert.equal(localDay(at(7, 30, 25)), '2026-10-25');
});

test('a page that does not ask to be made again only changes its words', () => {
  const greeting = component({}, at(21));
  let reloaded = 0;
  window.location.reload = () => { reloaded += 1; };
  greeting.now = () => at(7, 30, 25);
  greeting.update();
  assert.equal(reloaded, 0);
  assert.equal(greeting.text, 'Good morning');
});
