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

  var LABEL_KEY = "edifyOriginalLabel";
  var WIDTH_KEY = "edifyOriginalWidth";

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
      return element.querySelector(
        'button[type="submit"], input[type="submit"], button:not([type])'
      );
    }
    if (element.tagName === "BUTTON" || element.tagName === "A") return element;
    return null;
  }

  function markPending(control) {
    if (!control || control.dataset.edifyPending === "1") return;

    /* Freeze the width before the label changes. "Schedule" becoming
       "Scheduling…" is wider, and a button that grows mid-click shifts every
       control beside it — motion caused by feedback is worse than no
       feedback. */
    var rect = control.getBoundingClientRect();
    if (rect.width) {
      control.dataset[WIDTH_KEY] = control.style.width || "";
      control.style.width = rect.width + "px";
    }

    control.dataset.edifyPending = "1";
    control.setAttribute("aria-busy", "true");

    var label = control.textContent;
    control.dataset[LABEL_KEY] = label;
    control.textContent = pendingLabelFor(label);

    /* aria-disabled, not disabled: a disabled button loses focus, which throws
       a keyboard user back to the top of the document mid-task. HTMX still
       refuses the second request because of the guard in the capture handler
       below. */
    control.setAttribute("aria-disabled", "true");
    control.classList.add("is-pending");
  }

  function clearPending(control) {
    if (!control || control.dataset.edifyPending !== "1") return;
    if (control.dataset[LABEL_KEY] !== undefined) {
      control.textContent = control.dataset[LABEL_KEY];
      delete control.dataset[LABEL_KEY];
    }
    if (control.dataset[WIDTH_KEY] !== undefined) {
      control.style.width = control.dataset[WIDTH_KEY];
      delete control.dataset[WIDTH_KEY];
    }
    delete control.dataset.edifyPending;
    control.removeAttribute("aria-busy");
    control.removeAttribute("aria-disabled");
    control.classList.remove("is-pending");
  }

  document.body.addEventListener("htmx:beforeRequest", function (event) {
    var element = event.detail && event.detail.elt;
    if (!element || !element.tagName || !isMutating(element)) return;
    markPending(controlFor(event));
  });

  /* afterRequest fires for success AND for an error response, which is what we
     want: the control comes back either way. A failed action that leaves its
     button spinning forever is the worst of the states this file exists to
     prevent. */
  ["htmx:afterRequest", "htmx:responseError", "htmx:sendError", "htmx:timeout"].forEach(
    function (name) {
      document.body.addEventListener(name, function (event) {
        clearPending(controlFor(event));
      });
    }
  );

  /* The control is frequently replaced by the swap, taking its pending state
     with it. Anything left behind is swept here so a stale flag cannot outlive
     the request that set it. */
  document.body.addEventListener("htmx:afterSwap", function () {
    document.querySelectorAll('[data-edify-pending="1"]').forEach(function (control) {
      if (!control.isConnected) return;
      clearPending(control);
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

  document.body.addEventListener("htmx:beforeRequest", startProgress);
  ["htmx:afterRequest", "htmx:responseError", "htmx:sendError", "htmx:timeout"].forEach(
    function (name) {
      document.body.addEventListener(name, stopProgress);
    }
  );

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
