(function () {
  "use strict";

  function beginLaunch() {
    var screen = document.querySelector("[data-launch-screen]");
    if (!screen) return;

    var destination = screen.getAttribute("data-login-url") || "/login";
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
