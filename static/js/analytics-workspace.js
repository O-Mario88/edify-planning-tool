(function () {
  "use strict";

  const ROOT_SELECTOR = "[data-analytics-enterprise]";
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

    /* Evidence disclosures start closed on every visit and one is open at a
       time (owner, 2026-09-25: details expand only when their row is tapped,
       and close when another is tapped or the same one is tapped again). A
       remembered open state reopened them on load, so none is restored. */
    const disclosures = Array.prototype.slice.call(root.querySelectorAll("details[data-analytics-disclosure]"));
    disclosures.forEach(function (details) {
      details.addEventListener("toggle", function () {
        if (details.open) {
          disclosures.forEach(function (other) { if (other !== details && other.open) other.open = false; });
        }
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
