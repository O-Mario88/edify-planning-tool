(function () {
  "use strict";

  const ROOT_SELECTOR = "[data-analytics-enterprise]";
  const STORAGE_PREFIX = "edify.analytics.disclosure.";

  function safeStorageGet(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (_) {
      return null;
    }
  }

  function safeStorageSet(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (_) {
      // Storage can be disabled by browser policy; the disclosure still works.
    }
  }

  function interaction(root, eventName, element) {
    window.dispatchEvent(new CustomEvent("edify:analytics-interaction", {
      detail: {
        event: eventName,
        page: window.location.pathname,
        element: element && (element.dataset.analyticsId || element.id || element.name || element.tagName.toLowerCase()),
        at: new Date().toISOString()
      }
    }));
  }

  function initialiseRoot(root) {
    if (root.dataset.analyticsInitialised === "true") return;
    root.dataset.analyticsInitialised = "true";

    root.querySelectorAll("details[data-analytics-disclosure]").forEach(function (details, index) {
      const disclosureId = details.dataset.analyticsId || details.id || String(index);
      const key = STORAGE_PREFIX + window.location.pathname + "." + disclosureId;
      const saved = safeStorageGet(key);
      if (saved !== null) details.open = saved === "open";

      details.addEventListener("toggle", function () {
        safeStorageSet(key, details.open ? "open" : "closed");
        interaction(root, details.open ? "disclosure_open" : "disclosure_close", details);
      });
    });

    root.addEventListener("change", function (event) {
      if (event.target.matches("select, input[type='date'], input[type='search']")) {
        interaction(root, "filter_change", event.target);
      }
    });

    root.addEventListener("click", function (event) {
      const tracked = event.target.closest("[data-analytics-track], .analytics-decision-frame__action");
      if (tracked) interaction(root, tracked.dataset.analyticsTrack || "action", tracked);
    });
  }

  function initialise(container) {
    if (container.matches && container.matches(ROOT_SELECTOR)) initialiseRoot(container);
    container.querySelectorAll(ROOT_SELECTOR).forEach(initialiseRoot);
  }

  document.addEventListener("DOMContentLoaded", function () { initialise(document); });
  document.body.addEventListener("htmx:afterSwap", function (event) { initialise(event.target); });
})();
