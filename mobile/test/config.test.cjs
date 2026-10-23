// The app's server setting (capacitor.config.js): production by default, and
// never an unencrypted server outside a local or private network.
const { test } = require("node:test");
const assert = require("node:assert/strict");
const { resolveServer } = require("../capacitor.config.js");
const config = require("../capacitor.config.js");

test("the app opens Home on the production site by default", () => {
  assert.equal(config.server.url, "https://edifyplanning.app/home");
  assert.equal(config.server.cleartext, false);
  assert.equal(config.appId, "app.edifyplanning.mobile");
  assert.equal(config.appName, "Edify");
});

test("plain http is allowed only for a local or private address", () => {
  assert.deepEqual(resolveServer("http://10.0.2.2:8000"), { origin: "http://10.0.2.2:8000", cleartext: true });
  assert.deepEqual(resolveServer("http://192.168.1.20:8000"), { origin: "http://192.168.1.20:8000", cleartext: true });
  assert.throws(() => resolveServer("http://edifyplanning.app"));
  assert.throws(() => resolveServer("http://evil.example"));
  assert.throws(() => resolveServer("ftp://edifyplanning.app"));
});
