/*
 * One pending state for every HTMX action on the platform.
 *
 * The reported symptom was people clicking a button repeatedly because nothing
 * happened. That is accurate: hover and press feedback exist (components.css
 * INTERACTION LAYER), but they end the moment the pointer lifts. Between
 * releasing the mouse and the server answering — which on a slow request is
 * seconds — the control looked exactly as it had before the click. There was
 * nothing to read, so the reasonable conclusion was that the click missed.
 *
 * Three templates carried hx-disabled-elt. This gives the other several hundred
 * the same behaviour without touching any of them, by listening to the HTMX
 * lifecycle at the document level.
 *
 * What it does NOT do, deliberately:
 *
 *  - It does not claim success. The label returns to normal when the request
 *    finishes; whether the work succeeded is the swapped content's story to
 *    tell, and a checkmark drawn by the client is a lie the client cannot back
 *    up.
 *  - It does not replace backend idempotency. Disabling a button stops the
 *    honest double-click, not a replayed request. The finance paths hold their
 *    own row locks for that reason.
 *  - It does not fire on non-mutating GETs by default. A spinner on every
 *    filter keystroke is noise, and noise is what people learn to ignore.
 */
(function () {
  "use strict";

  if (window.__edifyPendingInstalled) return;
  window.__edifyPendingInstalled = true;

  var controlStates = new WeakMap();
  var requests = new Map();

  /* Verb → progressive form. The label should name the work in flight, not
     say "Loading…", which tells the user nothing they did not already know. */
  var PENDING_LABELS = [
    [/^schedule\b/i, "Scheduling…"],
    [/^submit\b/i, "Submitting…"],
    [/^approve\b/i, "Approving…"],
    [/^disburse\b/i, "Disbursing…"],
    [/^save\b/i, "Saving…"],
    [/^upload\b/i, "Uploading…"],
    [/^verify\b/i, "Verifying…"],
    [/^assign\b/i, "Assigning…"],
    [/^send\b/i, "Sending…"],
    [/^add\b/i, "Adding…"],
    [/^create\b/i, "Creating…"],
    [/^confirm\b/i, "Confirming…"],
    [/^return\b/i, "Returning…"],
    [/^clear\b/i, "Clearing…"],
    [/^pay\b/i, "Paying…"],
    [/^close\b/i, "Closing…"],
    [/^remove\b/i, "Removing…"],
    [/^delete\b/i, "Deleting…"],
  ];

  function pendingLabelFor(text) {
    var trimmed = (text || "").trim();
    for (var i = 0; i < PENDING_LABELS.length; i++) {
      if (PENDING_LABELS[i][0].test(trimmed)) return PENDING_LABELS[i][1];
    }
    return "Working…";
  }

  /* Only controls that change something. A GET that filters a list is not a
     mutation, and marking it pending puts a spinner on every keystroke. */
  function isMutating(element) {
    return Boolean(
      element.getAttribute("hx-post") ||
        element.getAttribute("hx-put") ||
        element.getAttribute("hx-patch") ||
        element.getAttribute("hx-delete") ||
        element.closest("form[hx-post], form[hx-put], form[hx-patch], form[hx-delete]")
    );
  }

  function controlFor(event) {
    var element = event.detail && event.detail.elt;
    if (!element || !element.tagName) return null;
    if (element.tagName === "FORM") {
      var triggering = event.detail.requestConfig && event.detail.requestConfig.triggeringEvent;
      var submitter = triggering && triggering.submitter;
      if (submitter && element.contains(submitter)) return submitter;
      var focused = document.activeElement;
      if (focused && element.contains(focused) && focused.matches('button, input[type="submit"]')) return focused;
      return element.querySelector('button[type="submit"], input[type="submit"], button:not([type])');
    }
    if (element.matches('button, a, input[type="submit"]')) return element;
    return null;
  }

  function markPending(control) {
    if (!control || control.dataset.edifyPending === "1") return;

    var state = {
      nodes: Array.from(control.childNodes),
      value: control.value,
      width: control.style.width,
      busy: control.getAttribute("aria-busy"),
      disabled: control.getAttribute("aria-disabled"),
      pendingClass: control.classList.contains("is-pending")
    };
    controlStates.set(control, state);
    var rect = control.getBoundingClientRect();
    if (rect.width) control.style.width = rect.width + "px";
    control.dataset.edifyPending = "1";
    control.setAttribute("aria-busy", "true");
    var isInput = control.tagName === "INPUT";
    var label = pendingLabelFor(isInput ? control.value : control.textContent);
    if (isInput) control.value = label;
    else control.textContent = label;
    control.setAttribute("aria-disabled", "true");
    control.classList.add("is-pending");
  }

  function clearPending(control) {
    var state = control && controlStates.get(control);
    if (!state) return;
    if (control.tagName === "INPUT") control.value = state.value;
    else control.replaceChildren.apply(control, state.nodes);
    control.style.width = state.width;
    [ ["aria-busy", state.busy], ["aria-disabled", state.disabled] ].forEach(function (entry) {
      if (entry[1] === null) control.removeAttribute(entry[0]);
      else control.setAttribute(entry[0], entry[1]);
    });
    delete control.dataset.edifyPending;
    if (!state.pendingClass) control.classList.remove("is-pending");
    controlStates.delete(control);
  }

  // Track the actual request: swaps may replace the initiating element, and
  // an error emits more than one terminal lifecycle event for the same XHR.
  document.body.addEventListener("htmx:beforeRequest", function (event) {
    var detail = event.detail || {};
    var key = detail.xhr;
    if (!key || event.defaultPrevented || navigator.onLine === false || requests.has(key)) return;
    var element = detail.elt;
    var control = element && element.tagName && isMutating(element) ? controlFor(event) : null;
    if (control && controlStates.has(control)) {
      event.preventDefault();
      return;
    }
    requests.set(key, control);
    markPending(control);
    startProgress();
    // A document-level guard may cancel after this body listener has run.
    // Cancelled requests do not emit afterRequest, so release their state once
    // all listeners have seen the event.
    Promise.resolve().then(function () {
      if (event.defaultPrevented) finishRequest(key);
    });
  });

  function finishRequest(key) {
    if (!requests.has(key)) return;
    clearPending(requests.get(key));
    requests.delete(key);
    stopProgress();
  }

  ["htmx:afterRequest", "htmx:responseError", "htmx:sendError", "htmx:timeout"].forEach(function (name) {
    document.body.addEventListener(name, function (event) {
      finishRequest(event.detail && event.detail.xhr);
    });
  });

  /* ── Route progress ─────────────────────────────────────────────────────
     A navigation or a large swap needs acknowledgement too, and the pending
     button only covers the control that started it — a sidebar link or a tab
     leaves the page looking untouched while the request runs.

     Deliberately delayed by 140ms. A fast response that flashes a progress bar
     reads as a glitch, and a bar that appears on every interaction stops
     meaning "working" and starts meaning nothing. Only requests slow enough to
     be noticed get one. */
  var PROGRESS_DELAY_MS = 140;
  var progressTimer = null;
  var progressBar = null;
  var inFlight = 0;

  function ensureBar() {
    if (progressBar) return progressBar;
    progressBar = document.createElement("div");
    progressBar.className = "edify-route-progress";
    progressBar.setAttribute("role", "progressbar");
    progressBar.setAttribute("aria-label", "Loading");
    document.body.appendChild(progressBar);
    return progressBar;
  }

  function startProgress() {
    inFlight += 1;
    if (progressTimer !== null) return;
    progressTimer = window.setTimeout(function () {
      progressTimer = null;
      if (inFlight > 0) ensureBar().classList.add("is-active");
    }, PROGRESS_DELAY_MS);
  }

  function stopProgress() {
    inFlight = Math.max(0, inFlight - 1);
    if (inFlight > 0) return;
    if (progressTimer !== null) {
      window.clearTimeout(progressTimer);
      progressTimer = null;
    }
    if (progressBar) progressBar.classList.remove("is-active");
  }

  /* The actual duplicate-submit guard. Capture phase, so it runs before HTMX's
     own click handling and can stop the second request from being issued at
     all rather than cancelling it afterwards. */
  document.addEventListener(
    "click",
    function (event) {
      var control = event.target.closest && event.target.closest('[data-edify-pending="1"]');
      if (!control) return;
      event.preventDefault();
      event.stopPropagation();
    },
    true
  );
})();
