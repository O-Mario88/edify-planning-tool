/* The address bar (<meta name="theme-color">) takes the page canvas. In the
 * app the phone's bars follow the page beside them (2026-10-25): an iPhone
 * runs the page under its status bar, icons set from the page top; Android's
 * bars take the page's top and bottom colours (EdifyChromePlugin.java).
 * tests/js/system-chrome.test.cjs. */
(function (root) {
  "use strict";

  function hexOf(value) {
    var text = String(value || "").trim().toLowerCase();
    var m = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/.exec(text);
    if (m) return "#" + m[1] + m[1] + m[2] + m[2] + m[3] + m[3];
    return /^#[0-9a-f]{6}$/.test(text) ? text : null;
  }

  /** A computed colour as [r, g, b, alpha]. */
  function rgba(value) {
    var m = /^rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)(?:[\s,/]+([\d.]+))?\s*\)$/.exec(String(value || "").trim());
    if (!m) return null;
    return [Number(m[1]), Number(m[2]), Number(m[3]), m[4] === undefined ? 1 : Number(m[4])];
  }

  function toHex(rgb) {
    return "#" + rgb.slice(0, 3).map(function (n) {
      return ("0" + Math.max(0, Math.min(255, Math.round(n))).toString(16)).slice(-2);
    }).join("");
  }

  function rgbHex(value) {
    var c = rgba(value);
    return c && c[3] >= 1 ? toHex(c) : null;
  }

  /** Whether dark icons read on this colour. */
  function isLight(hex) {
    var n = parseInt(hex.slice(1), 16);
    return 0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255) > 150;
  }

  /** A background image's bottom-most linear gradient, read at the edge's end. */
  function gradientEnd(image, atTop) {
    var text = String(image || "");
    var start = text.lastIndexOf("linear-gradient(");
    if (start === -1) return null;
    var body = text.slice(start);
    var colours = body.match(/rgba?\([^)]*\)/g);
    if (!colours) return null;
    var first = /^linear-gradient\(\s*(to top|0deg)/.test(body) ? !atTop : atTop;
    return rgba(colours[first ? 0 : colours.length - 1]);
  }

  function stackAt(doc, x, y) {
    if (doc.elementsFromPoint) return Array.prototype.slice.call(doc.elementsFromPoint(x, y));
    var stack = [];
    for (var el = doc.elementFromPoint ? doc.elementFromPoint(x, y) : null; el && el.nodeType === 1; el = el.parentElement) {
      stack.push(el);
    }
    return stack;
  }

  /** The colour painted at (x, y): the topmost opaque background, with the
   *  see-through ones above it blended on; an element's opacity counts. */
  function surfaceAt(win, x, y) {
    var stack = stackAt(win.document, x, y);
    var atTop = y < (win.innerHeight || 0) / 2;
    var layers = [];
    for (var s = 0; s < stack.length; s += 1) {
      var style = win.getComputedStyle(stack[s]);
      var c = rgba(style.backgroundColor);
      var painted = gradientEnd(style.backgroundImage, atTop);
      if (painted && painted[3] >= 1 && !(c && c[3] >= 1)) c = painted;
      if (!c) continue;
      c[3] *= style.opacity === undefined || style.opacity === "" ? 1 : Number(style.opacity);
      if (c[3] >= 1) {
        for (var i = layers.length - 1; i >= 0; i -= 1) {
          var a = layers[i][3];
          c = [0, 1, 2].map(function (k) { return c[k] * (1 - a) + layers[i][k] * a; });
        }
        return toHex(c);
      }
      if (c[3] > 0) layers.push(c);
    }
    return null;
  }

  function noop() {}

  function apply(win) {
    var doc = win.document;
    var color = hexOf(win.getComputedStyle(doc.documentElement).getPropertyValue("--edify-bg"));
    if (!color) return null;
    var meta = doc.querySelector('meta[name="theme-color"]');
    if (meta && meta.content !== color) meta.content = color;
    var cap = win.Capacitor;
    var plugins = cap && cap.isNativePlatform && cap.isNativePlatform() && cap.Plugins;
    if (!plugins) return color;
    var middle = win.innerWidth / 2;
    var top = surfaceAt(win, middle, 1) || color;
    if (cap.getPlatform() === "android" && plugins.EdifyChrome) {
      var bottom = surfaceAt(win, middle, win.innerHeight - 1) || color;
      if (win.__edifyBars === top + bottom) return color; // told only on a change
      win.__edifyBars = top + bottom;
      var done = plugins.EdifyChrome.setBars({ top: top, bottom: bottom });
      if (done && done.catch) done.catch(noop);
      return color;
    }
    var bar = plugins.StatusBar;
    if (!bar) return color;
    if (cap.getPlatform() === "android") {
      // An Android build from before EdifyChrome.
      bar.setStyle({ style: isLight(color) ? "LIGHT" : "DARK" });
      bar.setBackgroundColor({ color: color });
      return color;
    }
    // iPhone: the page runs under the bar (the config's own strip is a fixed
    // colour no page can change), once; then icons for the page top.
    if (!win.__edifyOverlay && typeof bar.setOverlaysWebView === "function") {
      win.__edifyOverlay = true;
      var overlay = bar.setOverlaysWebView({ overlay: true });
      if (overlay && overlay.catch) overlay.catch(noop);
    }
    bar.setStyle({ style: isLight(top) ? "LIGHT" : "DARK" }); // LIGHT = dark icons
    return color;
  }

  function start(win) {
    var doc = win.document;
    var run = function () {
      try {
        apply(win);
      } catch (error) {
        /* The bars keep their colour. */
      }
    };
    if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", run, { once: true });
    else run();
    win.addEventListener("pageshow", run);
    win.addEventListener("load", run, { once: true });
    if (win.MutationObserver) {
      var timer;
      new win.MutationObserver(function () {
        win.clearTimeout(timer);
        timer = win.setTimeout(run, 450); // after the 400ms theme fade
      }).observe(doc.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    }
    // In the app what sits at the edges changes as the page loads, scrolls,
    // swaps a part, or opens a drawer or menu: looked at once a frame.
    var cap = win.Capacitor;
    if (!(cap && cap.isNativePlatform && cap.isNativePlatform()) || !win.requestAnimationFrame) return;
    var queued = false;
    var soon = function () {
      if (queued) return;
      queued = true;
      win.requestAnimationFrame(function () {
        queued = false;
        run();
      });
    };
    var later = function () {
      win.setTimeout(soon, 60);
      win.setTimeout(soon, 420); // after a 300ms slide
    };
    win.addEventListener("load", function () {
      win.setTimeout(soon, 300);
      win.setTimeout(soon, 1200);
    }, { once: true });
    win.addEventListener("scroll", soon, { passive: true });
    win.addEventListener("resize", soon);
    doc.addEventListener("htmx:afterSettle", soon);
    doc.addEventListener("click", later, true);
    doc.addEventListener("keydown", later, true);
    doc.addEventListener("transitionend", soon, true);
    doc.addEventListener("animationend", soon, true);
  }

  var api = { hexOf: hexOf, rgbHex: rgbHex, isLight: isLight, surfaceAt: surfaceAt, apply: apply, start: start };
  if (typeof module === "object" && module.exports) module.exports = api;
  else {
    root.EdifySystemChrome = api;
    start(root);
  }
})(typeof window !== "undefined" ? window : this);
