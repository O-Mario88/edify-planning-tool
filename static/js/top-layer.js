/*
 * Everything that floats opens where it belongs (owner, 2026-09-27): "NO
 * action button dropdown drawer opens from a fixed position. they have to open
 * where the button is", "this should also apply to all fix positions items",
 * and "make sure the dropdown is actually dropping down".
 *
 * A `position: fixed` box is placed against the window only while no ancestor
 * has a transform, filter, containment or container type; otherwise it is
 * placed against that ancestor, scrolls with it and is cut off by its
 * overflow. Container queries give main, tables, cards and every Core School
 * row a container type, so the Core Schools Actions list landed offset by its
 * row, clipped by its card, or off screen in a scrolled workspace — and every
 * modal or bar written inside a page was held to the workspace's scroll.
 *
 * So whatever floats is shown in the browser's top layer (Popover API): above
 * the page, against the window, clipped by nothing, yet still in place in the
 * document for Alpine, htmx, forms, focus order and CSS selectors.
 *
 *  - Dropdowns: EdifyLayer.open(panel, button) drops the panel DOWN from the
 *    button, on its right ('end') or left ('start') edge, inside the window,
 *    and moves it with the button; `onLost` closes it once the button leaves
 *    the screen. Alpine panels say `x-dropdown="$refs.button"` beside x-show.
 *  - Overlays need no markup: an element any stylesheet makes position: fixed
 *    is lifted while it is shown inside a box that would trap it (or shown
 *    while something else is lifted, so the newest is on top).
 *    `data-edify-layer="off"` opts one out.
 */
(function (factory) {
  "use strict";
  var api = factory(typeof window !== "undefined" ? window : null);
  if (typeof module === "object" && module.exports) module.exports = api;
  if (typeof window !== "undefined" && typeof document !== "undefined" && !window.EdifyLayer) {
    window.EdifyLayer = api;
    api.start();
  }
})(function (win) {
  "use strict";

  var MARGIN = 8; // the closest a panel comes to the window's edge
  var LIFTED = "data-edify-lifted";
  var DROPDOWN = "data-edify-dropdown";
  var doc = win && win.document;
  var supported = Boolean(win && win.HTMLElement && "popover" in win.HTMLElement.prototype);

  /* Pure; tests/js/top-layer.test.cjs holds it to the rule. Always below the
     button, never over it: `need` is how far the panel runs past the foot of
     the window, which the opener first scrolls away (makeRoom); what still
     does not fit scrolls inside the panel (maxHeight). A button too near one
     side of the window takes its other edge. */
  function plan(rect, size, view, options) {
    options = options || {};
    var gap = options.gap == null ? 4 : options.gap;
    var room = Math.max(0, view.height - rect.bottom - gap - MARGIN);
    var left = options.align === "start" ? rect.left : rect.right - size.width;
    if (left < MARGIN) left = rect.left;
    if (left + size.width > view.width - MARGIN) left = rect.right - size.width;
    left = Math.max(MARGIN, Math.min(left, view.width - size.width - MARGIN));
    return {
      left: Math.round(left),
      top: Math.round(rect.bottom + gap),
      maxHeight: size.height > room ? Math.floor(room) : null,
      need: Math.max(0, Math.ceil(size.height - room)),
    };
  }

  /* Its foot is the top of the bottom navigation when that is on screen. */
  function viewport() {
    var width = win.innerWidth;
    var client = doc.documentElement.clientWidth;
    var height = win.innerHeight;
    var nav = doc.querySelector(".edify-bottom-nav");
    if (nav && nav.getClientRects().length) {
      var top = nav.getBoundingClientRect().top;
      if (top > 0 && top < height) height = top;
    }
    return { width: client ? Math.min(client, width) : width, height: height };
  }

  function isOpen(el) {
    try { return el.matches(":popover-open"); } catch (error) { return false; }
  }

  // `why`: "trapped" (its ancestors would trap it), "stacked" (shown while a
  // trapped overlay or a dropdown is up, so it opens over that) or "live".
  function lift(el, why) {
    if (!supported || !el.isConnected) return false;
    if (!el.hasAttribute(LIFTED)) {
      el.setAttribute("popover", "manual");
      el.setAttribute(LIFTED, why || "");
    }
    try { if (!isOpen(el)) el.showPopover(); } catch (error) { return false; }
    return true;
  }

  function drop(el) {
    try { if (isOpen(el)) el.hidePopover(); } catch (error) { /* already gone */ }
    el.removeAttribute("popover");
    el.removeAttribute(LIFTED);
  }

  function inTopLayer(el) {
    return el.hasAttribute(LIFTED) || isOpen(el) || (el.tagName === "DIALOG" && el.matches(":modal"));
  }

  /* Whether an ancestor makes `fixed` relative to itself (CSS Position 3).
     The page receding behind an open drawer (drawer-background.js) is meant
     to take its fixed bars with it, so it does not count. */
  function trapped(el) {
    for (var node = el.parentElement; node && node !== doc.documentElement; node = node.parentElement) {
      if (inTopLayer(node)) return false;
      if (node.classList.contains("edify-drawer-recede")) continue;
      var s = win.getComputedStyle(node);
      var set = function (value) { return value && value !== "none"; };
      if (set(s.transform) || set(s.translate) || set(s.scale) || set(s.rotate) || set(s.perspective) ||
          set(s.filter) || set(s.backdropFilter) || set(s.webkitBackdropFilter) ||
          (s.containerType && s.containerType !== "normal") || s.contentVisibility === "auto" ||
          /layout|paint|strict|content/.test(s.contain || "") ||
          /transform|translate|scale|rotate|perspective|filter|contain/.test(s.willChange || "")) return true;
    }
    return false;
  }

  /* ── Dropdowns ─────────────────────────────────────────────────────── */

  var anchors = new WeakMap();
  var wanted = new WeakMap();
  var open = [];
  var listening = false;
  var frame = 0;

  // What can hide the button as the page scrolls (table scroller, card,
  // workspace), up to the first box that is itself in the top layer.
  function clippers(trigger) {
    var boxes = [];
    for (var node = trigger.parentElement; node && node !== doc.documentElement; node = node.parentElement) {
      var style = win.getComputedStyle(node);
      if (style.overflowX !== "visible" || style.overflowY !== "visible") boxes.push(node);
      if (inTopLayer(node)) break;
    }
    return boxes;
  }

  function onScreen(state) {
    var box = state.trigger.getBoundingClientRect();
    if (!box.width && !box.height) return false;
    var view = viewport();
    var edges = [Math.max(box.top, 0), Math.min(box.bottom, view.height), Math.max(box.left, 0), Math.min(box.right, view.width)];
    state.clips.forEach(function (clip) {
      var c = clip.getBoundingClientRect();
      edges = [Math.max(edges[0], c.top), Math.min(edges[1], c.bottom), Math.max(edges[2], c.left), Math.min(edges[3], c.right)];
    });
    return edges[1] > edges[0] && edges[3] > edges[2];
  }

  function place(panel) {
    var state = anchors.get(panel);
    if (!state || !panel.isConnected) return null;
    var style = panel.style;
    style.right = style.bottom = "auto";
    style.margin = "0";
    style.maxHeight = style.overflowY = "";
    style.left = style.top = "0px"; // measured where nothing narrows it
    var spot = plan(state.trigger.getBoundingClientRect(), { width: panel.offsetWidth, height: panel.offsetHeight }, viewport(), state);
    if (spot.maxHeight !== null) {
      style.maxHeight = spot.maxHeight + "px";
      style.overflowY = "auto";
    }
    style.left = spot.left + "px";
    style.top = spot.top + "px";
    if (!isOpen(panel)) {
      // No top layer: take up whatever offset a containing block adds.
      var landed = panel.getBoundingClientRect();
      style.left = Math.round(2 * spot.left - landed.left) + "px";
      style.top = Math.round(2 * spot.top - landed.top) + "px";
    }
    return spot;
  }

  /* Scroll what holds the button up by the room the panel needs, never so
     far that the button leaves the top of its scroller. */
  function makeRoom(state, need) {
    var boxes = state.clips.concat(doc.scrollingElement ? [doc.scrollingElement] : []);
    for (var i = 0; i < boxes.length && need > 0; i += 1) {
      var box = boxes[i];
      var page = box === doc.scrollingElement;
      if (box.scrollHeight <= box.clientHeight || (!page && !/(auto|scroll)/.test(win.getComputedStyle(box).overflowY))) continue;
      var headroom = state.trigger.getBoundingClientRect().top - (page ? 0 : Math.max(box.getBoundingClientRect().top, 0)) - MARGIN;
      var travel = Math.floor(Math.min(need, headroom, box.scrollHeight - box.clientHeight - box.scrollTop));
      if (travel > 0) { box.scrollTop += travel; need -= travel; }
    }
  }

  function follow() {
    frame = 0;
    open.slice().forEach(function (panel) {
      var state = anchors.get(panel);
      if (!panel.isConnected || !state.trigger.isConnected) {
        closePanel(panel);
        if (state.onLost) state.onLost();
      } else if (state.onLost && !onScreen(state)) {
        state.onLost(); // it would float over the wrong row
      } else {
        place(panel);
      }
    });
  }

  function schedule() {
    if (!frame) frame = win.requestAnimationFrame(follow);
  }

  function listen(on) {
    if (listening === on) return;
    listening = on;
    var method = on ? "addEventListener" : "removeEventListener";
    win[method]("scroll", schedule, { capture: true, passive: true });
    win[method]("resize", schedule, { passive: true });
    if (win.visualViewport) win.visualViewport[method]("resize", schedule, { passive: true });
  }

  function openPanel(panel, trigger, options, frames) {
    if (!panel || !trigger) return;
    wanted.set(panel, true);
    // x-show without a transition shows its element a frame after the state
    // changes; measured before that, the panel is 0px wide.
    if (panel.hidden || panel.style.display === "none" || panel._x_isShown === false) {
      if ((frames || 0) < 10) {
        win.requestAnimationFrame(function () {
          if (wanted.get(panel)) openPanel(panel, trigger, options, (frames || 0) + 1);
        });
      }
      return;
    }
    options = options || {};
    var state = {
      trigger: trigger,
      align: options.align === "start" ? "start" : "end",
      gap: options.gap == null ? 4 : options.gap,
      onLost: options.onLost || null,
      clips: clippers(trigger),
    };
    anchors.set(panel, state);
    mark(panel);
    var fresh = open.indexOf(panel) === -1;
    lift(panel);
    var spot = place(panel);
    if (fresh && spot && spot.need > 0) {
      makeRoom(state, spot.need);
      place(panel);
    }
    if (fresh) open.push(panel);
    listen(true);
    raiseLive();
  }

  // Marked before it first opens, so the overlay pass never takes it.
  function mark(panel) {
    if (panel && panel.setAttribute) panel.setAttribute(DROPDOWN, "");
  }

  /* The popover attribute stays while closed, so the panel's own x-show
     showing it again cannot draw it in the page before it is lifted. */
  function closePanel(panel) {
    wanted.set(panel, false);
    var index = open.indexOf(panel);
    if (index === -1) return;
    open.splice(index, 1);
    try { if (isOpen(panel)) panel.hidePopover(); } catch (error) { /* already gone */ }
    if (!open.length) { listen(false); sync(); }
  }

  /* ── Overlays, found from the stylesheets ──────────────────────────── */

  var fixedSelectors = [];
  var known = {};
  var readSheets = new WeakSet();
  var overlaySelector = "";
  var overlays = new Set();
  var showing = new WeakSet();

  // Top-level commas only: `:is(.a, .b)` is one selector.
  function splitSelectors(text) {
    var parts = [];
    var depth = 0;
    var quote = "";
    var start = 0;
    for (var i = 0; i < text.length; i += 1) {
      var ch = text[i];
      if (quote) { if (ch === quote && text[i - 1] !== "\\") quote = ""; continue; }
      if (ch === '"' || ch === "'") quote = ch;
      else if (ch === "(" || ch === "[") depth += 1;
      else if (ch === ")" || ch === "]") depth -= 1;
      else if (ch === "," && depth === 0) { parts.push(text.slice(start, i)); start = i + 1; }
    }
    parts.push(text.slice(start));
    return parts.map(function (part) { return part.trim(); }).filter(Boolean);
  }

  function collect(rules) {
    Array.prototype.forEach.call(rules, function (rule) {
      if (rule.style && rule.selectorText && rule.style.getPropertyValue("position").trim() === "fixed") {
        splitSelectors(rule.selectorText).forEach(function (selector) {
          // Not a pseudo-element, a self-managed popover or a nested `&` rule.
          if (known[selector] || /::|:popover-open|&/.test(selector)) return;
          try { doc.createDocumentFragment().querySelector(selector); } catch (error) { return; }
          known[selector] = true;
          fixedSelectors.push(selector);
        });
      }
      if (rule.cssRules && rule.cssRules.length) collect(rule.cssRules);
    });
  }

  // True when a stylesheet not read before brought new fixed selectors.
  function readStylesheets() {
    var before = fixedSelectors.length;
    Array.prototype.forEach.call(doc.styleSheets, function (sheet) {
      if (readSheets.has(sheet)) return;
      try { collect(sheet.cssRules); } catch (error) { return; } // another origin
      readSheets.add(sheet);
    });
    overlaySelector = fixedSelectors.concat(['[style*="position: fixed"]', '[style*="position:fixed"]']).join(",");
    return fixedSelectors.length !== before;
  }

  function discover(root) {
    if (!overlaySelector || !root || root.nodeType !== 1) return;
    var found = Array.prototype.slice.call(root.querySelectorAll(overlaySelector));
    if (root.matches(overlaySelector)) found.push(root);
    found.forEach(function (el) {
      if (el.hasAttribute(DROPDOWN) || el.getAttribute("data-edify-layer") === "off") return;
      if (el.hasAttribute("popover") && !el.hasAttribute(LIFTED)) return; // its own popover
      overlays.add(el);
    });
  }

  function rendered(el) {
    return el.checkVisibility ? el.checkVisibility() : Boolean(el.getClientRects().length);
  }

  function fixed(el) {
    return win.getComputedStyle(el).position === "fixed";
  }

  /* A toast or connection banner speaks about whatever is on screen, so it
     stays above the newest thing lifted. */
  function raiseLive() {
    overlays.forEach(function (el) {
      if (!el.isConnected || !el.matches('[aria-live], [role="status"], [role="alert"]') || !rendered(el) || !fixed(el)) return;
      if (!el.hasAttribute(LIFTED)) { lift(el, "live"); return; }
      try { el.hidePopover(); el.showPopover(); } catch (error) { /* not shown */ }
    });
  }

  function sync() {
    if (!overlays.size) return;
    // What holds the top layer: an open dropdown or a trapped overlay. Only
    // while something does are other overlays lifted to stay above it; once
    // nothing does, they go back to the page (a bottom nav shown again after
    // a drawer closed must not stay in the top layer).
    // A dropdown swapped out with its drawer or row was never closed.
    open = open.filter(function (panel) { return panel.isConnected; });
    if (!open.length) listen(false);
    var seen = [];
    var holding = open.length > 0;
    overlays.forEach(function (el) {
      if (!el.isConnected || el.hasAttribute(DROPDOWN)) { overlays.delete(el); return; }
      var shown = rendered(el);
      var appeared = shown && !showing.has(el);
      if (shown) showing.add(el); else showing.delete(el);
      var lifted = el.hasAttribute(LIFTED);
      var isFixed = shown && fixed(el);
      // Read as it appears, and re-read while it is lifted for it: an overlay
      // already on screen is not pulled out of the page by a later change
      // around it.
      var trap = isFixed && (appeared || el.getAttribute(LIFTED) === "trapped") && trapped(el);
      if (trap) holding = true;
      seen.push({ el: el, lifted: lifted, fixed: isFixed, appeared: appeared, trap: trap });
    });
    var liftedAny = false;
    seen.forEach(function (item) {
      if (item.lifted) {
        if (!item.fixed || (!item.trap && !holding)) drop(item.el);
      } else if (item.appeared && (item.trap || holding)) {
        if (lift(item.el, item.trap ? "trapped" : "stacked")) liftedAny = true;
      }
    });
    if (liftedAny) raiseLive();
  }

  function start() {
    if (!doc) return;
    function boot() {
      readStylesheets();
      discover(doc.body);
      sync();
      // A mutation observer's callback is a microtask: an overlay x-show has
      // just shown is lifted before the frame that would draw it trapped.
      new win.MutationObserver(function (records) {
        records.forEach(function (record) {
          if (record.addedNodes) Array.prototype.forEach.call(record.addedNodes, discover);
        });
        sync();
      }).observe(doc.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["class", "style", "hidden", "open"] });
      // A new width can make an overlay fixed that was not (`fixed lg:absolute`):
      // everything on screen is read again as if it had just appeared.
      win.addEventListener("resize", function () {
        showing = new WeakSet();
        win.requestAnimationFrame(sync);
      }, { passive: true });
      // A swapped-in page can bring its own stylesheet.
      doc.addEventListener("htmx:afterSettle", function () {
        if (readStylesheets()) { discover(doc.body); sync(); }
      });
    }
    if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", boot);
    else boot();

    // `x-dropdown="$refs.button"` (`.start` for the left edge) on an x-show
    // panel opens it at the button whenever x-show shows it. When the button
    // leaves the screen, a plain x-show property is set false to close it.
    function register(Alpine) {
      Alpine.directive("dropdown", function (el, directive, utils) {
        var shows = (el.getAttribute("x-show") || "").trim();
        if (!shows) return;
        mark(el);
        var button = utils.evaluateLater(directive.expression || "$el.previousElementSibling");
        var shown = utils.evaluateLater(shows);
        var align = directive.modifiers.indexOf("start") !== -1 ? "start" : "end";
        var settable = /^[A-Za-z_$][\w$]*(\.[A-Za-z_$][\w$]*)*$/.test(shows);
        utils.effect(function () {
          shown(function (value) {
            if (!value) { closePanel(el); return; }
            Alpine.nextTick(function () {
              button(function (trigger) {
                openPanel(el, trigger, {
                  align: align,
                  onLost: settable ? function () { utils.evaluate(shows + " = false"); } : null,
                });
              });
            });
          });
        });
        utils.cleanup(function () { closePanel(el); });
      });
    }
    if (win.Alpine && win.Alpine.directive) register(win.Alpine);
    else doc.addEventListener("alpine:init", function () { register(win.Alpine); });
  }

  return {
    supported: supported,
    plan: plan,
    open: openPanel,
    close: closePanel,
    mark: mark,
    splitSelectors: splitSelectors,
    start: start,
  };
});
