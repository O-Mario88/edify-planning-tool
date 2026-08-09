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
        return node !== hostNode;
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

  /* A swap INTO the container replaces whatever drawer is there. Releasing
     first means the incoming drawer locks from a clean baseline instead of
     inheriting the outgoing one's state as its "original". */
  document.addEventListener("htmx:beforeSwap", function (event) {
    var target = event.detail && event.detail.target;
    if (target && target.id === HOST_ID) release();
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
