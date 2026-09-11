/*
 * A form that refuses to submit has to say why.
 *
 * THE DEFECT THIS FIXES (owner, 2026-09-11)
 *
 * "When I schedule a visit, it does not save as in the database, the save
 * button does nothing."
 *
 * It was doing exactly nothing, and the save that never happened was correct:
 * a `required` control somewhere in the drawer was empty, so the browser
 * refused the submit. Measured on the schedule drawer with In-school Training
 * chosen and no training picked yet: no request, no message, no console error
 * — `catalogue_item_id` reported "Please select an item in the list." to the
 * browser and nobody else.
 *
 * The browser does raise its own bubble, but it is the wrong instrument here.
 * It vanishes after a few seconds, it renders outside the document so a
 * drawer that scrolls can carry the field away from it, and it names one
 * field at a time. A planner who has scrolled past a conditional field sees a
 * dead button and concludes the product is broken — which is what happened.
 *
 * htmx cannot help: native validation blocks the submit BEFORE htmx is
 * involved, so `htmx:validation:halted` never fires (measured — the event log
 * is empty). The only signal is the native `invalid` event, which does not
 * bubble, so this listens in the capture phase.
 *
 * WHAT IT DOES
 *
 * Collects every control the browser rejected in one submit attempt, names
 * them by their visible label, and writes one message into the form — into
 * the form's own error area when it has one, otherwise a block inserted at
 * the top. The message clears as soon as the form is submitted successfully
 * or the offending controls are filled, so it never outlives the problem.
 */
(function () {
  "use strict";

  if (window.__edifyFormRefusal) return;
  window.__edifyFormRefusal = true;

  var PANEL_CLASS = "edify-form-refusal";

  /* The visible name of a control, in the order a reader would look for it:
     its own label, the label wrapping it, an aria-label, then the field name
     as a last resort so the message is never empty. */
  function labelFor(control) {
    var byId = control.id && document.querySelector('label[for="' + control.id + '"]');
    var wrapping = control.closest && control.closest("label");
    var text =
      (byId && byId.textContent) ||
      (wrapping && wrapping.textContent) ||
      control.getAttribute("aria-label") ||
      control.getAttribute("placeholder") ||
      control.name ||
      "";
    text = text.replace(/\s+/g, " ").replace(/\*$/, "").trim();
    /* Labels often carry their own hint text after a dash or bullet. */
    return text.split(/ [·—-] /)[0].trim() || control.name || "a required field";
  }

  function panelFor(form) {
    /* The form's own error area, when the page gave it one — the schedule
       drawers post their server-side errors into #form-errors, and putting
       this in the same place keeps one spot to look. */
    var target = form.getAttribute("hx-target");
    if (target && target.charAt(0) === "#") {
      var declared = document.querySelector(target);
      if (declared && form.contains(declared)) return declared;
    }
    var existing = form.querySelector("." + PANEL_CLASS);
    if (existing) return existing;
    var panel = document.createElement("div");
    panel.className = PANEL_CLASS;
    form.insertBefore(panel, form.firstChild);
    return panel;
  }

  function render(form, controls) {
    var panel = panelFor(form);
    if (!panel) return;
    var names = [];
    controls.forEach(function (control) {
      var name = labelFor(control);
      if (names.indexOf(name) === -1) names.push(name);
    });
    var lead =
      names.length === 1
        ? "Add " + names[0] + " before saving."
        : "Add these before saving: " + names.join(", ") + ".";
    panel.innerHTML = "";
    var note = document.createElement("div");
    note.className = "edify-note";
    note.setAttribute("data-tone", "warning");
    note.setAttribute("role", "alert");
    var title = document.createElement("p");
    title.className = "edify-note__title";
    title.textContent = "Not saved yet";
    var body = document.createElement("p");
    body.className = "edify-note__body";
    body.textContent = lead;
    note.appendChild(title);
    note.appendChild(body);
    panel.appendChild(note);
    panel.hidden = false;
  }

  function clear(form) {
    if (!form) return;
    var panel = form.querySelector("." + PANEL_CLASS);
    if (panel) panel.innerHTML = "";
    var target = form.getAttribute("hx-target");
    if (target && target.charAt(0) === "#") {
      var declared = document.querySelector(target);
      /* Only ours: a server-rendered error in the same box is not this
         listener's to remove. */
      if (declared && form.contains(declared) && declared.querySelector("." + PANEL_CLASS + "-owned")) {
        declared.innerHTML = "";
      }
    }
  }

  /* One submit attempt raises `invalid` once per rejected control, all in the
     same tick. They are gathered and reported together so a reader fixes the
     whole form once rather than discovering the next missing field on every
     press. */
  var pending = new Map();

  document.addEventListener(
    "invalid",
    function (event) {
      var control = event.target;
      var form = control && control.form;
      if (!form) return;
      if (!pending.has(form)) {
        pending.set(form, []);
        window.requestAnimationFrame(function () {
          var controls = pending.get(form) || [];
          pending.delete(form);
          if (!controls.length) return;
          render(form, controls);
          var first = controls[0];
          if (first.scrollIntoView) {
            first.scrollIntoView({ block: "center", behavior: "smooth" });
          }
        });
      }
      pending.get(form).push(control);
    },
    true
  );

  /* The moment the form goes out successfully the note has done its job. */
  document.addEventListener("htmx:beforeRequest", function (event) {
    if (event.target && event.target.tagName === "FORM") clear(event.target);
  });
})();
