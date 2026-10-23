/* Country Targets: every row saved at once (owner, 2026-10-20: "I want to
 * update all the fields and save at once").
 *
 * The editor has some 150 rows of thirteen boxes — about 1,950 fields, more
 * than Django's DATA_UPLOAD_MAX_NUMBER_FIELDS (1,000) accepts in one request.
 * Rather than raise that guard for the whole platform, Save gathers the boxes
 * into one JSON field and leaves the boxes themselves out of the request, so
 * the form sends three fields whatever its size. The server reads the same
 * names either way (apps/frontend/views/team_performance_views.py). */
(function () {
  'use strict';

  function bundle(event) {
    var form = event.target;
    if (!form.matches || !form.matches('form[data-tp-targets-form]')) return;
    var values = {};
    var boxes = form.querySelectorAll('input[data-tp-target]');
    Array.prototype.forEach.call(boxes, function (box) {
      values[box.name] = box.value;
    });
    form.querySelector('input[name="payload"]').value = JSON.stringify(values);
    // Out of the request, still on screen: a disabled box is not sent.
    Array.prototype.forEach.call(boxes, function (box) { box.disabled = true; });
    // Back from the browser's cache (Back after saving), the boxes work again.
    window.addEventListener('pageshow', function () {
      Array.prototype.forEach.call(boxes, function (box) { box.disabled = false; });
    }, { once: true });
  }

  document.addEventListener('submit', bundle, true);
})();
