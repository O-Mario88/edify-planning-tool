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

test("the offline page retries a stamped constant, never text read from its own markup", () => {
  const html = require("node:fs").readFileSync(require("node:path").join(__dirname, "..", "www", "offline.html"), "utf8");
  assert.match(html, /var EDIFY_SERVER = "https:\/\/edifyplanning\.app\/home";/);
  assert.doesNotMatch(html, /getAttribute|data-server|innerHTML|dataset/);
  assert.match(html, /window\.location\.replace\(EDIFY_SERVER\)/);
});

// The iOS shell keeps a page inside the app when its host is in
// server.allowNavigation or its address starts with server.url; anything else
// opens in Safari (Capacitor's WebViewDelegationHandler). server.url ends in
// /home, so without the site's host listed, sign-in would leave the app.
function staysInIosApp(address) {
  const { host } = new URL(address);
  return (config.server.allowNavigation || []).includes(host) || address.startsWith(config.server.url);
}

test("every page of the site stays inside the app, and no other site does", () => {
  for (const path of ["/home", "/login?next=/home", "/my-plan", "/"]) {
    assert.ok(staysInIosApp(`https://edifyplanning.app${path}`), path);
  }
  assert.deepEqual(config.server.allowNavigation, ["edifyplanning.app"]);
  assert.equal(staysInIosApp("https://evil.example/home"), false);
});

test("a notification that arrives while the app is open is the page's to show", () => {
  // No banner over the page being used: the bell count moves and one line
  // says what arrived (static/js/native-push.js), as on the web.
  assert.deepEqual(config.plugins.PushNotifications.presentationOptions, []);
});
