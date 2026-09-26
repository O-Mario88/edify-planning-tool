/*
 * One Edify calendar for every date field.
 *
 * Owner, 2026-09-26: "take a look at the design of calendar in the schedule a
 * day of visit in cluster drawer to have the same system calendar design ...
 * look at the entire platform for deviating calendar design and fix it" — and,
 * asked which calendar that is, the Edify calendar popover rather than the
 * browser's own picker, which draws a different calendar in every browser and
 * none of them in the platform's colours.
 *
 * WHY AN ENHANCER RATHER THAN A TEMPLATE COMPONENT
 *
 * Seventy-odd date fields in about fifty templates each carry their own name,
 * validation, htmx trigger, Alpine binding or `form=` attribute. Rewriting each
 * one would put all of that at risk, so every `<input type="date">` stays in
 * the page, untouched and in place — still the field the form submits,
 * validates and listens to — and this file sets the Edify calendar beside it:
 *
 *   <input type="date" …>                   the real field, unchanged; kept
 *                                           in the page but not on screen
 *   <span class="edify-datepick">           takes the field's layout classes
 *     <input type="text" readonly …>        what the reader sees and presses.
 *                                           A text field, so every page's
 *                                           field rules style it exactly as
 *                                           they styled the date field
 *     <span role="dialog">…</span>          the month, drawn when opened
 *   </span>
 *
 * The date field is not moved: moving it would make Alpine tear down and
 * rebuild its x-model and @change bindings, and a `<label>` wrapping it would
 * start naming the new field instead.
 *
 * A picked day is written to the date field and announced with `input` and
 * `change`, so x-model, @change, hx-trigger="change" and a form's own change
 * listener see exactly what a typed date gave them. A value written by code —
 * x-model, `:value`, a browser test's fill(), a form reset — is read back into
 * the visible field.
 *
 * A saved date is a calendar day, never an instant: it is read as its parts
 * and built as a local date, so a reader west of UTC is never shown the
 * previous month (controls audit F-07, 2026-09-14).
 *
 * `data-native-date` on a field or an ancestor keeps the browser's own picker.
 */
(function (factory) {
  "use strict";
  var api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (typeof window !== "undefined" && typeof document !== "undefined" && !window.__edifyDatePick) {
    window.__edifyDatePick = api;
    api.start(document);
  }
})(function () {
  "use strict";

  var MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
  ];
  var WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

  /* ── Calendar days, as parts ─────────────────────────────────────────── */

  function daysInMonth(year, month) {
    return new Date(Date.UTC(year, month, 0)).getUTCDate();
  }

  function localDate(year, month, day) {
    var date = new Date(2000, 0, 1);
    date.setFullYear(year, month - 1, day);
    return date;
  }

  function fromDate(date) {
    return { y: date.getFullYear(), m: date.getMonth() + 1, d: date.getDate() };
  }

  function parseIso(value) {
    var match = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value || "").trim());
    if (!match) return null;
    var day = { y: Number(match[1]), m: Number(match[2]), d: Number(match[3]) };
    if (day.m < 1 || day.m > 12 || day.d < 1 || day.d > daysInMonth(day.y, day.m)) return null;
    return day;
  }

  function pad(number, width) {
    var text = String(number);
    while (text.length < width) text = "0" + text;
    return text;
  }

  function toIso(day) {
    return pad(day.y, 4) + "-" + pad(day.m, 2) + "-" + pad(day.d, 2);
  }

  function compare(a, b) {
    return a.y - b.y || a.m - b.m || a.d - b.d;
  }

  function addDays(day, count) {
    return fromDate(localDate(day.y, day.m, day.d + count));
  }

  function addMonths(day, count) {
    var index = day.y * 12 + (day.m - 1) + count;
    var year = Math.floor(index / 12);
    var month = index - year * 12 + 1;
    return { y: year, m: month, d: Math.min(day.d, daysInMonth(year, month)) };
  }

  function weekday(day) {
    return localDate(day.y, day.m, day.d).getDay();
  }

  function within(day, min, max) {
    return !(min && compare(day, min) < 0) && !(max && compare(day, max) > 0);
  }

  function clamp(day, min, max) {
    if (min && compare(day, min) < 0) return min;
    if (max && compare(day, max) > 0) return max;
    return day;
  }

  /* Six weeks, Sunday first, blanks around the month: the popover keeps one
     height whichever month it shows. */
  function monthCells(year, month) {
    var cells = [];
    var lead = weekday({ y: year, m: month, d: 1 });
    var count = daysInMonth(year, month);
    for (var i = 0; i < lead; i++) cells.push(null);
    for (var d = 1; d <= count; d++) cells.push({ y: year, m: month, d: d });
    while (cells.length < 42) cells.push(null);
    return cells;
  }

  function shortLabel(day) {
    return MONTHS[day.m - 1].slice(0, 3) + " " + day.d + ", " + day.y;
  }

  function longLabel(day) {
    return WEEKDAYS[weekday(day)] + ", " + MONTHS[day.m - 1] + " " + day.d + ", " + day.y;
  }

  /* The month a field opens on: its own date's, else today's, kept inside
     the field's min and max. */
  function openingDay(value, min, max, now) {
    return parseIso(value) || clamp(fromDate(now || new Date()), parseIso(min), parseIso(max));
  }

  /* ── The field ───────────────────────────────────────────────────────── */

  /* Classes that place a field in its row rather than draw it. The wrapper
     takes them, so the new field sits exactly where the date field sat; the
     width classes go to both, so the visible field still fills its wrapper. */
  var PLACEMENT = /^(?:[a-z0-9]+:)*(?:-?m[trblxyse]?-|flex-(?:1|auto|initial|none)$|grow|shrink|basis-|col-|row-|self-|justify-self-|place-self-|order-|block$|inline-block$|inline$|hidden$|flex$|inline-flex$|grid$)/;
  var WIDTH = /^(?:[a-z0-9]+:)*(?:w-|min-w-|max-w-)/;

  var GLYPH =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" focusable="false">' +
    '<rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path stroke-linecap="round" d="M8 3v4M16 3v4M3.5 10h17"/></svg>';
  var CARET =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" focusable="false">' +
    '<path stroke-linecap="round" stroke-linejoin="round" d="M6 9l6 6 6-6"/></svg>';
  var PREV =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" focusable="false">' +
    '<path stroke-linecap="round" stroke-linejoin="round" d="M15 18l-6-6 6-6"/></svg>';
  var NEXT =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true" focusable="false">' +
    '<path stroke-linecap="round" stroke-linejoin="round" d="M9 6l6 6-6 6"/></svg>';

  var nextId = 0;
  var openField = null;
  var fields = typeof Set !== "undefined" ? new Set() : null;
  var valueProperty =
    typeof HTMLInputElement !== "undefined"
      ? Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")
      : null;

  function uid(prefix) {
    nextId += 1;
    return prefix + "-" + nextId;
  }

  function Field(native) {
    var doc = native.ownerDocument;
    this.native = native;
    this.doc = doc;
    this.mode = "days";

    var wrapper = doc.createElement("span");
    wrapper.className = "edify-datepick";
    var display = doc.createElement("input");
    display.type = "text";
    display.readOnly = true;
    display.autocomplete = "off";
    display.spellcheck = false;
    display.size = 13;
    display.setAttribute("inputmode", "none");
    display.setAttribute("role", "combobox");
    display.setAttribute("aria-haspopup", "dialog");
    display.setAttribute("aria-expanded", "false");
    display.setAttribute("data-edify-datepick-field", "");
    display.placeholder = native.getAttribute("placeholder") || "Select a date";

    var placement = [];
    var look = [];
    Array.prototype.forEach.call(native.classList, function (name) {
      if (PLACEMENT.test(name)) {
        placement.push(name);
        return;
      }
      look.push(name);
      if (WIDTH.test(name)) placement.push(name);
    });
    placement.forEach(function (name) { wrapper.classList.add(name); });
    this.sized = look.some(function (name) { return WIDTH.test(name); });
    display.className = look.join(" ");
    display.classList.add("edify-datepick__field");

    /* Spans throughout, never a div: shared field rules select a control by
       the shape of its container (the filter bars' `div:not(:has(div))`),
       and a calendar that brought a div along switched them off. */
    var pop = doc.createElement("span");
    pop.className = "edify-datepick__pop";
    pop.id = uid("edify-datepick");
    pop.hidden = true;
    pop.setAttribute("role", "dialog");
    pop.setAttribute("aria-modal", "false");
    display.setAttribute("aria-controls", pop.id);

    /* The field's label now names the field the reader uses. The date field
       keeps no label of its own (it is hidden from assistive technology), so
       a label — or a test's getByLabel — finds exactly one field. */
    display.id = native.id ? native.id + "-field" : uid("edify-datepick-field");
    this.labels = Array.prototype.slice.call(native.labels || []);
    this.labels.forEach(function (label) { label.htmlFor = display.id; });
    if (!this.labels.length) {
      display.setAttribute("aria-label", native.getAttribute("aria-label") || native.title || "Date");
    }
    pop.setAttribute("aria-label", "Choose a date");
    var described = native.getAttribute("aria-describedby");
    if (described) display.setAttribute("aria-describedby", described);

    var glyph = doc.createElement("span");
    glyph.className = "edify-datepick__glyph";
    glyph.innerHTML = GLYPH;
    var caret = doc.createElement("span");
    caret.className = "edify-datepick__caret";
    caret.innerHTML = CARET;

    wrapper.appendChild(display);
    wrapper.appendChild(glyph);
    wrapper.appendChild(caret);
    wrapper.appendChild(pop);
    native.insertAdjacentElement("afterend", wrapper);

    native.classList.add("edify-datepick__native");
    native.tabIndex = -1;
    native.setAttribute("aria-hidden", "true");

    this.wrapper = wrapper;
    this.display = display;
    this.pop = pop;
    this.bind();
    this.sync();
    fields.add(this);
    this.refit();
  }

  Field.prototype.refit = function () {
    this.fitted = false;
    if (!this.fit() && sizeWatch) sizeWatch.observe(this.wrapper);
  };

  /* The new field takes the date field's natural width. A date field with no
     width class is as wide as "mm/dd/yyyy" and its calendar mark, and a row
     that sizes its items from their content sizes from that; a text field's
     natural width comes from its `size`. So the date field is measured where
     it stands (the new field briefly out of the way), `size` is chosen to
     give the same natural width, and a field with no width class of its own
     is also given that width outright. A field with a width class keeps it:
     a pixel width there would stop a filter row sharing its space. Needs a
     rendered field, so one in a closed panel is measured when it appears,
     and every field is measured again once the web font has loaded. */
  Field.prototype.fit = function () {
    var native = this.native;
    var display = this.display;
    var wrapper = this.wrapper;
    if (this.fitted) return true;
    if (!display.offsetWidth) return false;
    wrapper.style.setProperty("display", "none", "important");
    native.classList.remove("edify-datepick__native");
    var actual = native.offsetWidth;
    var width = native.style.getPropertyValue("width");
    var priority = native.style.getPropertyPriority("width");
    native.style.setProperty("width", "auto", "important");
    var natural = native.offsetWidth;
    native.style.setProperty("width", width, priority);
    native.classList.add("edify-datepick__native");
    wrapper.style.removeProperty("display");
    if (!natural) return false;
    /* Measured inline, as the date field was: a block-level field would
       report its container's width rather than its own. */
    display.style.setProperty("display", "inline-block", "important");
    display.style.setProperty("width", "auto", "important");
    display.size = 1;
    var one = display.offsetWidth;
    display.size = 11;
    var step = (display.offsetWidth - one) / 10 || 8;
    display.style.removeProperty("width");
    display.style.removeProperty("display");
    display.size = Math.max(1, Math.round((natural - one) / step) + 1);
    if (!this.sized && Math.abs(actual - natural) <= 1) display.style.width = natural + "px";
    this.fitted = true;
    return true;
  };

  Field.prototype.bind = function () {
    var field = this;
    var native = this.native;

    if (valueProperty) {
      Object.defineProperty(native, "value", {
        configurable: true,
        enumerable: true,
        get: function () { return valueProperty.get.call(this); },
        set: function (value) {
          valueProperty.set.call(this, value);
          field.sync();
        },
      });
    }

    native.addEventListener("input", function () { field.sync(); });
    native.addEventListener("change", function () { field.sync(); });
    native.addEventListener("invalid", function () { field.display.setAttribute("aria-invalid", "true"); });
    /* Code that focuses the date field (a drawer's first field) means the
       field the reader can see. Not when it is invalid: that is the browser
       pointing at a missing required date, and its message stays only while
       the date field keeps focus. aria-invalid marks the visible field. */
    native.addEventListener("focus", function () {
      if (native.validity && !native.validity.valid) return;
      field.display.focus({ preventScroll: true });
    });
    native.addEventListener("click", function (event) { event.preventDefault(); });
    /* A label press focuses the field, as it does any other field, rather
       than opening the calendar. */
    this.labels.forEach(function (label) {
      label.addEventListener("click", function (event) {
        if (field.wrapper.contains(event.target)) return;
        event.preventDefault();
        field.display.focus();
      });
    });
    if (native.form) {
      native.form.addEventListener("reset", function () { setTimeout(function () { field.sync(); }, 0); });
    }

    this.display.addEventListener("click", function () { field.toggle(); });
    this.display.addEventListener("keydown", function (event) { field.onFieldKey(event); });
    this.pop.addEventListener("click", function (event) { field.onPopClick(event); });
    this.pop.addEventListener("keydown", function (event) { field.onPopKey(event); });
  };

  Field.prototype.min = function () { return parseIso(this.native.min); };
  Field.prototype.max = function () { return parseIso(this.native.max); };

  Field.prototype.locked = function () {
    return this.native.disabled || this.native.readOnly;
  };

  Field.prototype.sync = function () {
    var day = parseIso(this.native.value);
    this.display.value = day ? shortLabel(day) : "";
    this.display.disabled = this.native.disabled;
    if (this.native.required) this.display.setAttribute("aria-required", "true");
    else this.display.removeAttribute("aria-required");
    if (day || !this.native.required) this.display.removeAttribute("aria-invalid");
    this.wrapper.toggleAttribute("data-empty", !day);
    /* micro-ux marks a field that holds something (consistency.css tints it)
       from its own input and change events, which reach the date field, not
       this one. */
    this.display.toggleAttribute("data-edify-filled", !!day);
    this.wrapper.hidden = this.native.hidden || this.native.style.display === "none";
  };

  Field.prototype.contains = function (node) {
    return node === this.native || this.wrapper.contains(node);
  };

  Field.prototype.toggle = function () {
    if (openField === this) this.close(false);
    else this.open();
  };

  Field.prototype.open = function () {
    if (this.locked()) return;
    if (openField && openField !== this) openField.close(false);
    openField = this;
    this.mode = "days";
    this.focusDay = openingDay(this.native.value, this.native.min, this.native.max);
    this.pop.hidden = false;
    this.wrapper.setAttribute("data-open", "");
    this.display.setAttribute("aria-expanded", "true");
    this.render(true);
    this.place();
  };

  Field.prototype.close = function (returnFocus) {
    if (openField === this) openField = null;
    this.pop.hidden = true;
    this.pop.innerHTML = "";
    this.wrapper.removeAttribute("data-open");
    this.display.setAttribute("aria-expanded", "false");
    if (returnFocus) this.display.focus({ preventScroll: true });
  };

  /* Written through the date field's own setter and announced the way a typed
     date is, so every listener on the page sees an ordinary edit. */
  Field.prototype.choose = function (day) {
    if (day && !within(day, this.min(), this.max())) return;
    var value = day ? toIso(day) : "";
    var changed = this.native.value !== value;
    this.native.value = value;
    if (changed) {
      this.native.dispatchEvent(new Event("input", { bubbles: true }));
      this.native.dispatchEvent(new Event("change", { bubbles: true }));
    }
    this.close(true);
  };

  /* Fixed, so no scrolling drawer or table can clip it, but measured from its
     own containing block: a transformed drawer makes `fixed` relative to the
     drawer rather than the window. */
  Field.prototype.place = function () {
    var pop = this.pop;
    var anchor = this.display.getBoundingClientRect();
    var view = this.doc.documentElement;
    pop.style.left = "0px";
    pop.style.top = "0px";
    var origin = pop.getBoundingClientRect();
    var width = pop.offsetWidth;
    var height = pop.offsetHeight;
    var viewWidth = view.clientWidth || window.innerWidth;
    var viewHeight = window.innerHeight;
    var left = Math.max(8, Math.min(anchor.left, viewWidth - width - 8));
    var below = viewHeight - anchor.bottom;
    var top = below >= height + 12 || below >= anchor.top ? anchor.bottom + 6 : anchor.top - height - 6;
    top = Math.max(8, Math.min(top, viewHeight - height - 8));
    pop.style.left = left - origin.left + "px";
    pop.style.top = top - origin.top + "px";
  };

  Field.prototype.render = function (moveFocus) {
    if (this.mode === "months") this.renderMonths();
    else this.renderDays();
    if (moveFocus) {
      var target = this.pop.querySelector('[tabindex="0"]');
      if (target) target.focus({ preventScroll: true });
    }
  };

  Field.prototype.renderDays = function () {
    var focus = this.focusDay;
    var picked = parseIso(this.native.value);
    var min = this.min();
    var max = this.max();
    var now = fromDate(new Date());
    var captionId = this.pop.id + "-caption";
    var html =
      '<span class="edify-datepick__head">' +
      '<button type="button" class="edify-datepick__step" data-go="prev" aria-label="Previous month">' + PREV + "</button>" +
      '<button type="button" class="edify-datepick__caption" id="' + captionId + '" data-go="months" aria-live="polite">' +
      MONTHS[focus.m - 1] + " " + focus.y + "</button>" +
      '<button type="button" class="edify-datepick__step" data-go="next" aria-label="Next month">' + NEXT + "</button>" +
      "</span>" +
      '<span class="edify-datepick__days" role="grid" aria-labelledby="' + captionId + '">' +
      '<span class="edify-datepick__week" role="row">';
    WEEKDAYS.forEach(function (name) {
      html += '<span class="edify-datepick__dow" role="columnheader" aria-label="' + name + '">' + name.slice(0, 2) + "</span>";
    });
    html += "</span>";
    monthCells(focus.y, focus.m).forEach(function (day, index) {
      if (index % 7 === 0) html += (index ? "</span>" : "") + '<span class="edify-datepick__week" role="row">';
      if (!day) {
        html += '<span class="edify-datepick__day" role="gridcell" data-blank></span>';
        return;
      }
      var attrs =
        ' data-day="' + toIso(day) + '"' +
        ' tabindex="' + (compare(day, focus) === 0 ? "0" : "-1") + '"' +
        ' aria-selected="' + (picked && compare(day, picked) === 0 ? "true" : "false") + '"' +
        ' aria-label="' + longLabel(day) + '"';
      if (compare(day, now) === 0) attrs += ' aria-current="date"';
      if (!within(day, min, max)) attrs += ' aria-disabled="true"';
      html += '<button type="button" class="edify-datepick__day" role="gridcell"' + attrs + ">" + day.d + "</button>";
    });
    html += "</span></span>";
    html += this.footer(now, min, max);
    this.pop.innerHTML = html;
  };

  Field.prototype.renderMonths = function () {
    var focus = this.focusDay;
    var min = this.min();
    var max = this.max();
    var captionId = this.pop.id + "-caption";
    var html =
      '<span class="edify-datepick__head">' +
      '<button type="button" class="edify-datepick__step" data-go="prev-year" aria-label="Previous year">' + PREV + "</button>" +
      '<button type="button" class="edify-datepick__caption" id="' + captionId + '" data-go="days" aria-live="polite">' + focus.y + "</button>" +
      '<button type="button" class="edify-datepick__step" data-go="next-year" aria-label="Next year">' + NEXT + "</button>" +
      "</span>" +
      '<span class="edify-datepick__months" role="group" aria-labelledby="' + captionId + '">';
    MONTHS.forEach(function (name, index) {
      var month = index + 1;
      var open =
        within({ y: focus.y, m: month, d: daysInMonth(focus.y, month) }, min, null) &&
        within({ y: focus.y, m: month, d: 1 }, null, max);
      html +=
        '<button type="button" class="edify-datepick__month" data-month="' + month + '"' +
        ' tabindex="' + (month === focus.m ? "0" : "-1") + '"' +
        ' aria-pressed="' + (month === focus.m ? "true" : "false") + '"' +
        ' aria-label="' + name + " " + focus.y + '"' +
        (open ? "" : ' aria-disabled="true"') + ">" + name.slice(0, 3) + "</button>";
    });
    html += "</span>";
    this.pop.innerHTML = html;
  };

  Field.prototype.footer = function (now, min, max) {
    var html = '<span class="edify-datepick__foot">';
    html +=
      '<button type="button" class="edify-datepick__link" data-go="today"' +
      (within(now, min, max) ? "" : ' aria-disabled="true"') + ">Today</button>";
    if (!this.native.required) {
      html += '<button type="button" class="edify-datepick__link" data-go="clear">Clear</button>';
    }
    return html + "</span>";
  };

  Field.prototype.onFieldKey = function (event) {
    var key = event.key;
    if (key === "Escape" && openField === this) {
      event.preventDefault();
      event.stopPropagation();
      this.close(true);
      return;
    }
    if (key === "Enter" || key === " " || key === "ArrowDown" || key === "ArrowUp") {
      event.preventDefault();
      if (openField !== this) this.open();
      return;
    }
    if ((key === "Backspace" || key === "Delete") && !this.native.required && !this.locked()) {
      event.preventDefault();
      if (this.native.value) this.choose(null);
    }
  };

  Field.prototype.onPopClick = function (event) {
    /* Always: a calendar inside a <label> must not hand the press to the label. */
    event.preventDefault();
    var target = event.target.closest("button");
    if (!target || !this.pop.contains(target)) return;
    if (target.getAttribute("aria-disabled") === "true") return;
    var go = target.getAttribute("data-go");
    if (target.hasAttribute("data-day")) return this.choose(parseIso(target.getAttribute("data-day")));
    if (target.hasAttribute("data-month")) {
      this.focusDay = clamp(
        { y: this.focusDay.y, m: Number(target.getAttribute("data-month")), d: 1 },
        this.min(),
        this.max(),
      );
      this.mode = "days";
      return this.render(true);
    }
    if (go === "today") return this.choose(fromDate(new Date()));
    if (go === "clear") return this.choose(null);
    if (go === "prev" || go === "next") this.focusDay = addMonths(this.focusDay, go === "prev" ? -1 : 1);
    if (go === "prev-year" || go === "next-year") this.focusDay = addMonths(this.focusDay, go === "prev-year" ? -12 : 12);
    if (go === "months" || go === "days") this.mode = go;
    this.render(false);
    var again =
      this.pop.querySelector('[data-go="' + go + '"]') ||
      this.pop.querySelector(".edify-datepick__caption");
    if (again) again.focus({ preventScroll: true });
    this.place();
  };

  var DAY_KEYS = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
  var MONTH_KEYS = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -3, ArrowDown: 3 };

  Field.prototype.onPopKey = function (event) {
    var key = event.key;
    if (key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      this.close(true);
      return;
    }
    var onDay = event.target.hasAttribute && event.target.hasAttribute("data-day");
    var onMonth = event.target.hasAttribute && event.target.hasAttribute("data-month");
    if (!onDay && !onMonth) return;
    var day = this.focusDay;
    if (onDay) {
      if (key in DAY_KEYS) day = addDays(day, DAY_KEYS[key]);
      else if (key === "Home") day = addDays(day, -weekday(day));
      else if (key === "End") day = addDays(day, 6 - weekday(day));
      else if (key === "PageUp" || key === "PageDown") day = addMonths(day, (key === "PageUp" ? -1 : 1) * (event.shiftKey ? 12 : 1));
      else return;
    } else {
      if (key in MONTH_KEYS) day = addMonths(day, MONTH_KEYS[key]);
      else if (key === "PageUp" || key === "PageDown") day = addMonths(day, key === "PageUp" ? -12 : 12);
      else return;
    }
    event.preventDefault();
    this.focusDay = day;
    this.render(true);
  };

  /* ── Wiring ──────────────────────────────────────────────────────────── */

  /* What code can change on a date field without an event: its limits, its
     state, a value written as an attribute, being hidden. */
  var watched = null;
  var WATCHED = ["value", "min", "max", "disabled", "readonly", "required", "hidden", "style"];
  /* Fields enhanced while hidden, waiting to be measured. Unobserved before
     measuring, so the measurement cannot re-trigger its own observer. */
  var sizeWatch =
    typeof ResizeObserver !== "undefined"
      ? new ResizeObserver(function (entries) {
          entries.forEach(function (entry) {
            var native = entry.target.previousElementSibling;
            var field = native && native.__edifyDatePick;
            sizeWatch.unobserve(entry.target);
            if (field && !field.fit()) sizeWatch.observe(entry.target);
          });
        })
      : null;

  function enhance(native) {
    if (native.__edifyDatePick || native.type !== "date") return;
    if (native.closest("[data-native-date]")) return;
    native.__edifyDatePick = new Field(native);
    if (watched) watched.observe(native, { attributes: true, attributeFilter: WATCHED });
  }

  function scan(node) {
    if (!node || node.nodeType !== 1) return;
    if (node.matches('input[type="date"]')) enhance(node);
    node.querySelectorAll('input[type="date"]').forEach(enhance);
  }

  function start(doc) {
    var win = doc.defaultView;

    function boot() {
      watched = new MutationObserver(function (records) {
        records.forEach(function (record) {
          var field = record.target.__edifyDatePick;
          if (field) field.sync();
        });
      });
      scan(doc.body);
      new MutationObserver(function (records) {
        records.forEach(function (record) {
          record.addedNodes.forEach(scan);
          /* A date field removed on its own takes its calendar with it. */
          record.removedNodes.forEach(function (node) {
            var field = node.__edifyDatePick;
            if (field && !node.isConnected) {
              if (openField === field) field.close(false);
              field.wrapper.remove();
              fields.delete(field);
            }
          });
        });
      }).observe(doc.body, { childList: true, subtree: true });
    }

    doc.addEventListener("pointerdown", function (event) {
      if (openField && !openField.contains(event.target)) openField.close(false);
    }, true);
    doc.addEventListener("focusin", function (event) {
      if (openField && !openField.contains(event.target)) openField.close(false);
    });
    function follow() {
      if (!openField) return;
      var box = openField.display.getBoundingClientRect();
      if (box.bottom < 0 || box.top > win.innerHeight || !openField.display.isConnected) openField.close(false);
      else openField.place();
    }
    win.addEventListener("resize", follow);
    win.addEventListener("scroll", follow, { capture: true, passive: true });

    if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", boot);
    else boot();
    if (doc.fonts && doc.fonts.ready) {
      doc.fonts.ready.then(function () {
        fields.forEach(function (field) {
          if (field.native.isConnected) field.refit();
          else fields.delete(field);
        });
      });
    }
  }

  return {
    start: start,
    enhance: enhance,
    parseIso: parseIso,
    toIso: toIso,
    addDays: addDays,
    addMonths: addMonths,
    monthCells: monthCells,
    shortLabel: shortLabel,
    longLabel: longLabel,
    openingDay: openingDay,
    within: within,
  };
});
