/* A signed-in page restored by "Back" (the back/forward cache) shows nothing
 * until /login/state confirms the session, and goes to sign in if it has
 * ended: on a shared phone, "Back" after signing out never shows the last
 * person's page. Offline it is shown as it was (tests/js/restore-guard.test.cjs). */
(function (root) {
  "use strict";

  var FLAG = "data-restore-check";

  function check(win) {
    var html = win.document.documentElement;
    html.setAttribute(FLAG, "");
    return win
      .fetch("/login/state", { headers: { "X-Edify-Background": "1" }, cache: "no-store" })
      .then(function (response) {
        return response.json();
      })
      .then(function (state) {
        if (state && state.signedIn === false) {
          win.location.replace("/login");
          return;
        }
        html.removeAttribute(FLAG);
      })
      .catch(function () {
        html.removeAttribute(FLAG);
      });
  }

  function start(win) {
    win.addEventListener("pageshow", function (event) {
      if (event.persisted) check(win);
    });
  }

  var api = { check: check, start: start };
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.EdifyRestoreGuard = api;
    start(root);
  }
})(typeof window !== "undefined" ? window : this);
