"""The page must be usable after a drawer closes.

INC: "the app freezes when you click any button and return on the same page —
you have to refresh for it to be clickable or scrollable."

That was accurate and it was not a rendering bug. Opening a drawer takes the
rest of the shell out of play: every sibling of #drawer-container gets `inert`
(which kills clicks AND focus) plus aria-hidden, and the body stops scrolling.
Each drawer did that for itself, by SNAPSHOTTING what the background looked
like and restoring that snapshot on close. Two things followed:

  * The snapshot is relative. A drawer opening while the background was
    ALREADY inert recorded `inert: true` as the original state, and faithfully
    restored the page to inert on close. Reached by opening a second drawer
    over the first — one ordinary extra click.
  * Teardown hung on an event. `close-drawer` was the only thing that
    restored anything, so any path that removed the drawer's DOM without it
    (an htmx swap into the container, a drawer clearing the container itself)
    destroyed the Alpine component silently and stranded the shell.

`micro-ux.js` held the same assumption for custom dialogs, and re-asserted its
stale snapshot AFTER the drawer had released — which is why typing into a
drawer, pressing Escape and confirming discard froze the page.

The fix is one owner (static/js/drawer-background.js) plus one rule, in both
modules: never take a node another layer already holds, and restore only what
you actually set. "No drawer is open" is an invariant, not a memory.

These tests hold the contract at the source level. The behaviour itself was
verified in a browser across every close path — header button, Escape,
discard-confirm, stacked drawers, and a drawer clearing its own container.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
CONTROLLER = ROOT / "static/js/drawer-background.js"
BASE_DRAWER = ROOT / "templates/components/drawers/base_drawer.html"
MICRO_UX = ROOT / "static/js/micro-ux.js"
BASE_TEMPLATE = ROOT / "templates/base.html"


class TheBackgroundHasOneOwnerTest(SimpleTestCase):
    def test_the_controller_ships_and_is_loaded(self):
        self.assertTrue(CONTROLLER.exists(), "the drawer background owner is missing")
        base = BASE_TEMPLATE.read_text(encoding="utf-8")
        self.assertIn(
            "js/drawer-background.js",
            base,
            "the controller exists but no page loads it",
        )

    def test_the_drawer_does_not_manage_the_background_itself(self):
        """A per-instance snapshot is what made the freeze possible."""
        source = BASE_DRAWER.read_text(encoding="utf-8")
        self.assertNotIn(
            "backgroundStates",
            source,
            "the drawer is snapshotting the background again — a drawer "
            "opening over another one will record 'already inert' as the "
            "state to restore, and restore the page to inert on close",
        )
        self.assertNotIn(
            "node.inert = true",
            source,
            "the drawer is setting inert directly instead of delegating",
        )
        self.assertIn("__edifyDrawerBackground?.lock()", source)
        self.assertIn("__edifyDrawerBackground?.release()", source)

    def test_no_drawer_clears_the_scroll_lock_without_releasing_inert(self):
        """Clearing body.overflow alone leaves the page unclickable.

        It looks like a close — the page scrolls again — which is exactly why
        this was easy to miss: only the `inert` half survived, and `inert` is
        invisible.
        """
        offenders = []
        for path in (ROOT / "templates").rglob("*.html"):
            source = path.read_text(encoding="utf-8")
            if "body.style.overflow" not in source:
                continue
            if "__edifyDrawerBackground" in source:
                continue
            offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(
            offenders,
            [],
            "these release the scroll lock by hand without releasing inert; "
            "call window.__edifyDrawerBackground.release() instead",
        )


class ReleaseIsAbsoluteNotRememberedTest(SimpleTestCase):
    """Both modules must record only what they themselves set."""

    def test_the_controller_skips_nodes_another_layer_already_holds(self):
        source = CONTROLLER.read_text(encoding="utf-8")
        self.assertIn("if (node.inert) return;", source)
        # Release clears what it set rather than replaying a remembered value.
        self.assertIn("node.inert = false;", source)
        self.assertNotIn("node.inert = state.inert", source)

    def test_the_controller_snapshots_once_not_per_drawer(self):
        source = CONTROLLER.read_text(encoding="utf-8")
        self.assertIn("if (locked) return;", source)

    def test_release_does_not_depend_on_the_close_event(self):
        """The container's contents are the truth, however a drawer left."""
        source = CONTROLLER.read_text(encoding="utf-8")
        self.assertIn("MutationObserver", source)
        self.assertIn("htmx:beforeSwap", source)

    def test_micro_ux_does_not_reassert_another_layers_inert(self):
        source = MICRO_UX.read_text(encoding="utf-8")
        self.assertIn("if (node.inert) return;", source)
        self.assertNotIn(
            "state.node.inert = state.inert",
            source,
            "restoring a remembered inert value re-freezes the page when the "
            "value was set by the drawer layer, not by this one",
        )


class WhoeverLocksTheBackgroundReleasesItTest(SimpleTestCase):
    """The hazard is locking, not rendering an overlay.

    Most drawers draw their own `fixed inset-0` panel and never touch the
    background at all — those cannot strand anything. The ones that matter are
    the ones that take `inert` or the scroll lock, because those are invisible
    once set and survive the element that set them.
    """

    #: The one owner, plus the accessibility helper that manages its own
    #: dialogs (and now refuses to touch a node another layer holds).
    OWNERS = {
        "static/js/drawer-background.js",
        "static/js/micro-ux.js",
    }

    LOCKING = re.compile(r"\.inert\s*=\s*true|body\.style\.overflow\s*=\s*['\"]hidden")

    def _sources(self):
        for folder, pattern in (("templates", "*.html"), ("static/js", "*.js")):
            for path in (ROOT / folder).rglob(pattern):
                rel = str(path.relative_to(ROOT))
                if "/vendor/" in rel:
                    continue
                yield rel, path.read_text(encoding="utf-8")

    def test_nothing_takes_the_background_outside_the_owner(self):
        offenders = sorted(
            rel
            for rel, source in self._sources()
            if rel not in self.OWNERS and self.LOCKING.search(source)
        )
        self.assertEqual(
            offenders,
            [],
            "these lock the background themselves. `inert` and the scroll "
            "lock outlive whatever set them, so a second locker — or a "
            "removed element — strands the page with no way back but a "
            "reload. Call window.__edifyDrawerBackground.lock()/release().",
        )
