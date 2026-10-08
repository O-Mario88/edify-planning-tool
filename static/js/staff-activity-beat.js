/* Staff Activity heartbeat (2026-09-29; apps.accounts.presence). Beats only
   while the page is visible, focused and touched within IDLE; the server's
   clock decides durations. An interaction only restarts the idle clock:
   nothing typed or read. Idle/poll htmx requests carry X-Edify-Background. */
(function () {
  "use strict";

  var body = document.body;
  if (!body || body.dataset.edifyActivity !== "on") return;
  var HEARTBEAT = (parseInt(body.dataset.edifyActivityBeat, 10) || 60) * 1000;
  var IDLE = (parseInt(body.dataset.edifyActivityIdle, 10) || 300) * 1000;
  var SESSION = (parseInt(body.dataset.edifySessionIdle, 10) || 1800) * 1000;
  var lastInteraction = Date.now();
  var lastBeat = Date.now();
  var askAfter = 0;

  function touched() {
    lastInteraction = Date.now();
  }
  ["pointerdown", "keydown", "input", "change", "wheel", "touchstart"].forEach(function (name) {
    document.addEventListener(name, touched, { capture: true, passive: true });
  });
  var scrollTimer = null;
  document.addEventListener("scroll", function () {
    if (scrollTimer) return;
    scrollTimer = setTimeout(function () { scrollTimer = null; touched(); }, 1000);
  }, { capture: true, passive: true });

  function active() {
    return document.visibilityState === "visible"
      && (typeof document.hasFocus !== "function" || document.hasFocus())
      && Date.now() - lastInteraction <= IDLE;
  }

  function csrf() {
    var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function beat() {
    if (!active() || Date.now() - lastBeat < HEARTBEAT - 1000) return;
    lastBeat = Date.now();
    var data = new FormData();
    data.append("page", window.location.pathname);
    data.append("idle", Math.round((Date.now() - lastInteraction) / 1000));
    fetch("/staff-activity/beat", {
      method: "POST",
      body: data,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrf(), "X-Requested-With": "XMLHttpRequest" },
      keepalive: true
    }).catch(function () { /* offline: the next beat carries on */ });
  }
  // Untouched for SESSION: is it still signed in? The server answers, as
  // another tab may be in use (SlidingSessionMiddleware).
  function stillSignedIn() {
    var now = Date.now();
    if (now - lastInteraction < SESSION || now < askAfter) return;
    askAfter = now + 60000;
    fetch("/login/state", { headers: { "X-Edify-Background": "1" } })
      .then(function (response) { return response.ok && !response.redirected ? response.json() : 0; })
      .then(function (state) {
        if (!state) return;
        if (state.signedIn) askAfter = Date.now() + state.remaining * 1000 + 1000;
        else { lastInteraction = Date.now(); window.EdifyPlatformStatus.showSessionExpired(); }
      }, function () {});
  }
  setInterval(function () { beat(); stillSignedIn(); }, Math.max(15000, Math.floor(HEARTBEAT / 4)));

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") { lastBeat = 0; stillSignedIn(); }
  });

  document.addEventListener("htmx:configRequest", function (event) {
    var detail = event.detail || {};
    var trigger = detail.triggeringEvent;
    var userEvent = trigger && trigger.isTrusted && /^(click|submit|change|input|keyup|keydown|search)$/.test(trigger.type);
    if (userEvent) touched();
    if (!userEvent && !active()) {
      detail.headers = detail.headers || {};
      detail.headers["X-Edify-Background"] = "1";
    }
  });
})();
