/* Staff Activity Log: open and close a person's detail row. The detail is
   fetched the first time it opens (the log never loads every person's
   sessions and actions up front). */
(function () {
  "use strict";

  function toggle(personId, opener) {
    var row = document.getElementById("sal-detail-" + personId);
    if (!row) return;
    var open = row.hidden;
    row.hidden = !open;
    document.querySelectorAll('[data-sal-toggle="' + personId + '"][aria-expanded]').forEach(function (button) {
      button.setAttribute("aria-expanded", open ? "true" : "false");
    });
    var person = document.querySelector('[data-sal-person="' + personId + '"]');
    if (person) person.classList.toggle("sal-person--open", open);
    var detail = row.querySelector("[data-table-detail]");
    if (open && detail && !detail.dataset.loaded && window.htmx) {
      detail.dataset.loaded = "1";
      window.htmx.ajax("GET", detail.dataset.src, { target: detail, swap: "innerHTML" });
    }
    if (!open && opener && opener.closest("[data-table-detail]")) {
      var name = document.querySelector('.sal-name[data-sal-toggle="' + personId + '"]');
      if (name) name.focus();
    }
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-sal-toggle]");
    if (!button || !button.closest("[data-staff-activity]")) return;
    event.preventDefault();
    toggle(button.getAttribute("data-sal-toggle"), button);
    var menu = button.closest("details");
    if (menu) menu.removeAttribute("open");
  });
})();
