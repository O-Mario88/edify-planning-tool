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
  var lastInteraction = Date.now();
  var lastBeat = Date.now();

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
    fetch("/staff-activity/beat", {
      method: "POST",
      body: data,
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrf(), "X-Requested-With": "XMLHttpRequest" },
      keepalive: true
    }).catch(function () { /* offline: the next beat carries on */ });
  }
  setInterval(beat, Math.max(15000, Math.floor(HEARTBEAT / 4)));

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") lastBeat = 0;
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
