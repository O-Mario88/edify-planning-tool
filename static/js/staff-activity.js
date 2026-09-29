/* Staff Activity Log: a row opens its person in the right column, under Team
   Insights (owner, 2026-09-29), fetched when opened — the log never loads
   every person's sessions and actions up front. */
(function () {
  "use strict";

  function panel() { return document.getElementById("sal-picked"); }

  function mark(personId) {
    document.querySelectorAll("[data-sal-person]").forEach(function (row) {
      var open = row.getAttribute("data-sal-person") === personId;
      row.classList.toggle("sal-person--open", open);
      row.querySelectorAll(".sal-name").forEach(function (b) { b.setAttribute("aria-expanded", open ? "true" : "false"); });
    });
  }

  function open(personId) {
    var row = document.querySelector('[data-sal-person="' + personId + '"]');
    var target = panel();
    if (!row || !target || !window.htmx) return;
    mark(personId);
    target.innerHTML = '<p class="sal-loading">Loading…</p>';
    window.htmx.ajax("GET", row.getAttribute("data-sal-src"), { target: target, swap: "innerHTML" });
    target.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  document.addEventListener("click", function (event) {
    var closer = event.target.closest("[data-sal-close]");
    if (closer && panel() && panel().contains(closer)) {
      event.preventDefault();
      var name = document.querySelector(".sal-person--open .sal-name");
      mark("");
      panel().innerHTML = '<p class="sal-none">Select a staff member to see their sign-in history, time by module, meaningful actions and period trend.</p>';
      if (name) name.focus();
      return;
    }
    var button = event.target.closest("[data-sal-toggle]");
    if (!button || !button.closest("[data-staff-activity]")) return;
    event.preventDefault();
    open(button.getAttribute("data-sal-toggle"));
    var menu = button.closest("details");
    if (menu) menu.removeAttribute("open");
  });
})();
