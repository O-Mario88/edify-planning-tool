/*
 * One owner of the "a drawer is open" background state.
 *
 * THE DEFECT THIS FIXES
 *
 * Opening a drawer takes the rest of the shell out of play: every sibling of
 * #drawer-container gets `inert` (which kills clicks AND focus) plus
 * aria-hidden, and the body stops scrolling. Each drawer used to do that for
 * itself, in its own Alpine component, by SNAPSHOTTING what the background
 * looked like and restoring that snapshot on close.
 *
 * Both halves of that were wrong.
 *
 *  1. The snapshot is relative. When a drawer opened while the background was
 *     ALREADY inert, it recorded `inert: true` as the original state — and
 *     faithfully restored the page to inert when it closed. The page then
 *     accepted no clicks at all until a reload.
 *
 *  2. Teardown hung on an event. Restoration only ran from the
 *     `close-drawer` handler, so any path that removed the drawer's DOM
 *     without that event — htmx swapping a second drawer into the container,
 *     or anything clearing it — destroyed the Alpine component silently and
 *     left the shell inert forever.
 *
 * Together those produced the reported symptom precisely: click a control
 * that opens a drawer while one is already open, close it, and the page is
 * frozen — not clickable, not scrollable — until you refresh.
 *
 * THE RULE
 *
 * "No drawer is open" is not a remembered state, it is an invariant: the
 * shell is interactive and the body scrolls. So the snapshot is taken ONCE,
 * on the first lock, and a lock while already locked changes nothing. Release
 * is idempotent and absolute, and it is driven by the container's actual
 * contents rather than by any drawer remembering to announce itself.
 */
(function () {
  "use strict";

  if (window.__edifyDrawerBackground) return;

  var HOST_ID = "drawer-container";
  var RECEDE_CLASS = "edify-drawer-recede";
  var OPENING_ATTR = "data-opening-frame";
  var locked = false;
  var nodes = [];
  var states = [];
  var bodyOverflow = "";

  function host() {
    return document.getElementById(HOST_ID);
  }

  function siblingsOf(hostNode) {
    if (!hostNode || !hostNode.parentElement) return [];
    return Array.prototype.filter.call(
      hostNode.parentElement.children,
      function (node) {
        /* A leaving frame is the drawer's, not the page's. */
        return node !== hostNode && !node.hasAttribute(OPENING_ATTR);
      }
    );
  }

  /* Snapshot only when nothing is held. A second drawer opening over the
     first must not record the first drawer's handiwork as the way the page
     is supposed to look. */
  function lock() {
    var hostNode = host();
    if (!hostNode) return;
    if (locked) return;
    /* Only nodes this controller actually inerts are recorded, and a node
       that is ALREADY inert is left entirely alone — the mobile sidebar
       binds :inert reactively and owns its own node, so touching it here
       would fight Alpine and strand it when the drawer released first. */
    nodes = [];
    states = [];
    siblingsOf(hostNode).forEach(function (node) {
      if (node.inert) return;
      nodes.push(node);
      states.push({ ariaHidden: node.getAttribute("aria-hidden") });
      node.inert = true;
      node.setAttribute("aria-hidden", "true");
      /* The visible half of "out of play": drawers.css drains the colour from
         these nodes and steps them back, so the page reads as depth behind the
         floating card rather than as a busy page under a grey sheet. They are
         exactly the right nodes for it — everything except the drawer's own
         container, so the transform never becomes the drawer's containing
         block (owner, 2026-09-06). */
      node.classList.add(RECEDE_CLASS);
    });
    bodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    locked = true;
  }

  function release() {
    if (!locked) return;
    nodes.forEach(function (node, index) {
      var state = states[index] || { ariaHidden: null };
      node.inert = false;
      node.classList.remove(RECEDE_CLASS);
      if (state.ariaHidden === null) node.removeAttribute("aria-hidden");
      else node.setAttribute("aria-hidden", state.ariaHidden);
    });
    document.body.style.overflow = bodyOverflow;
    nodes = [];
    states = [];
    bodyOverflow = "";
    locked = false;
  }

  /* The container's contents are the truth. A drawer that is gone is closed,
     however it left — dispatched event, htmx swap, or a caller emptying the
     node. This is what makes the lock impossible to strand. */
  function syncToContainer() {
    var hostNode = host();
    if (!hostNode) {
      release();
      return;
    }
    if (hostNode.children.length === 0) release();
  }

  window.__edifyDrawerBackground = {
    lock: lock,
    release: release,
    sync: syncToContainer,
    isLocked: function () {
      return locked;
    },
  };

  /* ── The drawer answers the click, not the server ───────────────────────
     Until a drawer's HTML arrived a click showed nothing (interaction-pending
     leaves GETs alone), so a slow Schedule looked like a dead button (owner,
     2026-09-28). A drawer opening over nothing shows its frame at once; the
     drawer that arrives fades in over it. The frame takes neither the lock
     nor focus, so the arriving drawer still records where focus returns. */
  var opening = null;
  var FRAME =
    '<div class="drawer-backdrop type-center"></div>' +
    '<div class="drawer-surface size-md type-center" role="dialog" aria-modal="true" aria-busy="true" aria-label="Loading">' +
    '<header class="drawer-header"><div class="drawer-header__identity"><div class="drawer-header__copy">' +
    '<p class="drawer-header__eyebrow">Edify workspace</p><div class="drawer-header__title-row"><h3></h3></div>' +
    '<p class="drawer-header__subtitle" role="status">Loading…</p></div></div>' +
    '<button type="button" class="drawer-close-btn" aria-label="Cancel"><svg class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" aria-hidden="true"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg></button></header>' +
    '<div class="drawer-body"><div class="platform-skeleton opening-frame__lines" aria-hidden="true">' +
    "<span></span><span></span><span></span><span></span><span></span><span></span><span></span></div></div></div>";

  /* The asking control's own name ("Schedule activity for Kasubi Primary");
     a form or a load trigger has none worth reading back. */
  function labelFor(trigger) {
    if (!trigger || !trigger.getAttribute) return "";
    var text = trigger.getAttribute("aria-label") || trigger.getAttribute("title");
    if (!text && /^(A|BUTTON)$/.test(trigger.tagName)) text = trigger.textContent;
    text = (text || "").replace(/\s+/g, " ").trim();
    return text.length <= 90 ? text : "";
  }

  function showOpening(hostNode, trigger) {
    var frame = document.createElement("div");
    frame.className = "edify-drawer-root opening-frame relative z-50";
    frame.setAttribute(OPENING_ATTR, "");
    frame.innerHTML = FRAME;
    frame.querySelector("h3").textContent = labelFor(trigger) || "Opening";
    /* A drawer that opens under its control (Notifications, Messages; owner,
       2026-10-10) is framed there too, so it does not appear in the middle
       of the screen and then jump to the bell. */
    if (trigger && trigger.hasAttribute && trigger.hasAttribute("data-drawer-anchor")) {
      var surface = frame.querySelector(".drawer-surface");
      var box = trigger.getBoundingClientRect();
      surface.className = "drawer-surface size-sm type-anchored";
      frame.querySelector(".drawer-backdrop").className = "drawer-backdrop type-anchored";
      surface.style.setProperty("--edify-anchor-top", Math.round(box.bottom + 8) + "px");
      surface.style.setProperty("--edify-anchor-right", Math.max(8, Math.round(document.documentElement.clientWidth - box.right)) + "px");
    }
    frame.querySelector(".drawer-backdrop").addEventListener("click", cancelOpening);
    frame.querySelector(".drawer-close-btn").addEventListener("click", cancelOpening);
    hostNode.appendChild(frame);
    /* Laid out closed, then shown: the same entrance as a drawer. Not
       `.active`, which means a drawer that arrived (drawers.css). */
    void frame.offsetWidth;
    frame.classList.add("opening-frame--shown");
    opening = { frame: frame, trigger: trigger };
  }

  function dropOpening() {
    if (!opening) return;
    var frame = opening.frame;
    opening = null;
    if (frame.parentNode) frame.parentNode.removeChild(frame);
    syncToContainer();
  }

  /* Escape, the backdrop or ✕. Aborted, so a late answer cannot open it. */
  function cancelOpening() {
    if (!opening) return;
    var trigger = opening.trigger;
    dropOpening();
    if (trigger && window.htmx) window.htmx.trigger(trigger, "htmx:abort");
  }

  /* The answer arrived: the frame steps out beside the container, stops
     being a dialog, and fades under the drawer's entrance. */
  function handOff(hostNode) {
    if (!opening || opening.frame.parentNode !== hostNode) return;
    var frame = opening.frame;
    opening = null;
    hostNode.parentNode.insertBefore(frame, hostNode);
    var surface = frame.querySelector(".drawer-surface");
    surface.removeAttribute("role");
    surface.removeAttribute("aria-modal");
    frame.setAttribute("aria-hidden", "true");
    frame.classList.remove("opening-frame--shown");
    frame.classList.add("opening-frame--leaving");
    setTimeout(function () {
      if (frame.parentNode) frame.parentNode.removeChild(frame);
    }, 320);
  }

  /* beforeSend: a request cancelled at beforeRequest never answers. */
  document.addEventListener("htmx:beforeSend", function (event) {
    var detail = event.detail || {};
    var hostNode = host();
    if (!hostNode || detail.target !== hostNode || opening) return;
    var verb = (detail.requestConfig && detail.requestConfig.verb) || "get";
    if (String(verb).toLowerCase() !== "get") return;
    if (hostNode.children.length) return;
    showOpening(hostNode, detail.elt);
  });

  /* An error, an abort, or nothing swapped here: never strand the frame. */
  ["htmx:afterRequest", "htmx:sendError", "htmx:timeout"].forEach(function (name) {
    document.addEventListener(name, function () {
      if (opening && opening.frame.parentNode === host()) dropOpening();
    });
  });

  document.addEventListener("keydown", function (event) {
    if (opening && event.key === "Escape") cancelOpening();
  });

  /* A swap INTO the container replaces whatever drawer is there. Releasing
     first means the incoming drawer locks from a clean baseline instead of
     inheriting the outgoing one's state as its "original". */
  document.addEventListener("htmx:beforeSwap", function (event) {
    var target = event.detail && event.detail.target;
    if (target && target.id === HOST_ID) {
      handOff(target);
      release();
    }
  });

  document.addEventListener("htmx:afterSwap", function (event) {
    var target = event.detail && event.detail.target;
    if (target && target.id === HOST_ID) syncToContainer();
  });

  /* Backstop for every path that touches the container without htmx: the
     drawer's own delayed self-removal, a script clearing innerHTML, an
     Alpine transition finishing. */
  function observe() {
    var hostNode = host();
    if (!hostNode || hostNode.__edifyObserved) return;
    hostNode.__edifyObserved = true;
    new MutationObserver(syncToContainer).observe(hostNode, { childList: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", observe);
  } else {
    observe();
  }
  /* The shell is re-rendered on some navigations, which replaces the
     container node the observer was attached to. */
  document.addEventListener("htmx:afterSettle", observe);
})();
