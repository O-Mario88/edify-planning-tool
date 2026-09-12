/* Back · Forward · Refresh for the installed app.
 *
 * The platform installs as a standalone PWA (display: standalone), so on a
 * phone or an installed desktop app there is no browser chrome: no way back
 * from a deep link, no way forward after going back, and no reload when a
 * page freezes. These three controls sit at the left of the top bar and do
 * exactly what the browser's own would. Page headers keep their real parent
 * links (partials/_back_link.html); this is the global control beside them.
 *
 * Back and forward disable themselves when there is nowhere to go, read
 * from the Navigation API where the browser has it and from history.length
 * otherwise. Refresh spins its icon until the page is gone, so a frozen page
 * visibly answers the press.
 */
(function () {
  "use strict";

  function state() {
    var nav = window.navigation;
    if (nav && typeof nav.canGoBack === "boolean") {
      return { back: nav.canGoBack, forward: nav.canGoForward };
    }
    // No Navigation API: history.length counts both directions, so back is
    // knowable and forward is not — leave forward enabled rather than hide a
    // working control behind a guess.
    return { back: window.history.length > 1, forward: true };
  }

  function bind(root) {
    var backButton = root.querySelector("[data-history-back]");
    var forwardButton = root.querySelector("[data-history-forward]");
    var refreshButton = root.querySelector("[data-history-refresh]");
    if (!backButton || !forwardButton || !refreshButton) return;

    function sync() {
      var s = state();
      backButton.disabled = !s.back;
      forwardButton.disabled = !s.forward;
    }

    backButton.addEventListener("click", function () {
      if (!backButton.disabled) window.history.back();
    });
    forwardButton.addEventListener("click", function () {
      if (!forwardButton.disabled) window.history.forward();
    });
    refreshButton.addEventListener("click", function () {
      if (refreshButton.disabled) return;
      refreshButton.disabled = true;
      refreshButton.classList.add("is-refreshing");
      refreshButton.setAttribute("aria-label", "Refreshing");
      // Same as the browser's own reload: the current URL, no cache trick
      // that would leave a second copy of the page in history.
      window.location.reload();
    });

    window.addEventListener("pageshow", function () {
      refreshButton.disabled = false;
      refreshButton.classList.remove("is-refreshing");
      refreshButton.setAttribute("aria-label", "Refresh this page");
      sync();
    });
    window.addEventListener("popstate", sync);
    if (window.navigation && window.navigation.addEventListener) {
      window.navigation.addEventListener("currententrychange", sync);
    }
    sync();
  }

  function init() {
    var root = document.querySelector("[data-history-controls]");
    if (root) bind(root);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
