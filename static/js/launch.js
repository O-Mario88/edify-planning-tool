(function () {
  "use strict";

  function beginLaunch() {
    var screen = document.querySelector("[data-launch-screen]");
    if (!screen) return;

    // Same-site paths only. The attribute is server-rendered from
    // reverse("frontend:login") today, but the value is handed straight to
    // location.replace(), where a "javascript:" URL would execute and a
    // "//host" one would leave the site — so the check lives next to the
    // navigation rather than in whoever writes the attribute.
    //
    // An allowlist pattern rather than a couple of charAt tests: it has to
    // permit nothing it was not written to permit, where a hand-rolled check
    // has to anticipate every way of spelling the thing it is refusing.
    var SAFE_PATH = /^\/[A-Za-z0-9\-._~!$&'()*+,;=:@%\/?]*$/;
    var raw = screen.getAttribute("data-login-url") || "/login";
    var destination =
      SAFE_PATH.test(raw) && raw.charAt(1) !== "/" ? raw : "/login";
    window.setTimeout(function () {
      screen.classList.add("is-leaving");
      window.setTimeout(function () {
        window.location.replace(destination);
      }, 180);
    }, 1550);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", beginLaunch);
  } else {
    beginLaunch();
  }
})();
