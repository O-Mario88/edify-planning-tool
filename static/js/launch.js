(function () {
  "use strict";

  function beginLaunch() {
    var screen = document.querySelector("[data-launch-screen]");
    if (!screen) return;

    // Same-site paths only. The attribute is server-rendered today, but this
    // value is handed straight to location.replace(), where a "javascript:"
    // URL would execute and a "//host" one would leave the site — so the
    // check lives next to the navigation rather than in whoever writes it.
    var raw = screen.getAttribute("data-login-url") || "/login";
    var destination =
      raw.charAt(0) === "/" && raw.charAt(1) !== "/" ? raw : "/login";
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
