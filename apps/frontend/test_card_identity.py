"""Registered cards must keep their identity in the rendered DOM.

The template scan in ``apps/system_health/card_inventory.py`` reads source, so
it cannot see a card that a loop renders twice or a partial that is included
from two places. This checks the page a role actually receives.

`data-card-key` is what makes that possible: before the registry there was no
attribute to group by, so "the same card twice" could only be spotted by
comparing wording.
"""

from __future__ import annotations

import re
from collections import Counter

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.core.cards import CARD_REGISTRY, cards_for_page, get_card

_CARD_KEY_RE = re.compile(r'data-card-key="([^"]+)"')
_COMPONENT_RE = re.compile(r'data-component-type="card"')


def _admin():
    return get_user_model().objects.create_user(
        email="card-identity-admin@edify.test",
        name="Card Identity Admin",
        roles=["Admin"],
        active_role="Admin",
        password="x",
        is_active=True,
    )


class MainDashboardCardIdentityTest(TestCase):
    def setUp(self):
        self.client.force_login(_admin())
        self.body = self.client.get("/dashboard").content.decode()

    def test_the_page_renders(self):
        self.assertIn("Main Dashboard", self.body)

    def test_every_card_carries_a_key(self):
        keys = _CARD_KEY_RE.findall(self.body)
        self.assertEqual(len(keys), len(_COMPONENT_RE.findall(self.body)))
        self.assertTrue(keys)

    def test_no_card_key_appears_twice(self):
        """§47: the duplicate-card-key count on a page is zero."""
        repeated = sorted(
            key for key, n in Counter(_CARD_KEY_RE.findall(self.body)).items() if n > 1
        )
        self.assertEqual(
            repeated,
            [],
            f"the same card is rendered more than once: {repeated}",
        )

    def test_every_rendered_key_is_registered(self):
        """§4: no unregistered card may render."""
        for key in set(_CARD_KEY_RE.findall(self.body)):
            with self.subTest(key):
                get_card(key)  # raises KeyError when unregistered

    def test_every_card_registered_to_this_page_actually_renders(self):
        """A registry entry nothing renders is a promise the page broke."""
        rendered = set(_CARD_KEY_RE.findall(self.body))
        registered = {c.key for c in cards_for_page("dashboard_main")}
        self.assertEqual(
            registered - rendered,
            set(),
            "registered for dashboard_main but not rendered",
        )

    def test_no_html_id_is_duplicated(self):
        ids = re.findall(r'\sid="([^"]+)"', self.body)
        repeated = sorted(k for k, n in Counter(ids).items() if n > 1)
        self.assertEqual(repeated, [], f"duplicate HTML ids: {repeated}")


class CardAccessibilityTest(TestCase):
    """§52: a card needs a heading, an accessible name and honest semantics.

    Verified in a real browser at 360px, 430px and desktop as well: no card
    overflows, no title clips, no nested interactive elements, and every
    `aria-labelledby` resolves. These assertions pin the parts that can be
    checked from the served HTML so a regression fails in CI rather than in a
    later manual pass.
    """

    def setUp(self):
        self.client.force_login(_admin())
        self.body = self.client.get("/dashboard").content.decode()

    def _card_blocks(self):
        # Each registered card opens a <section …data-card-key="…">.
        return (
            re.findall(r'<section[^>]*data-card-key="([^"]+)"[^>]*>', self.body) or []
        )

    def test_every_registered_card_is_a_section(self):
        """A card is a labelled region, not an anonymous <div>."""
        keys = set(_CARD_KEY_RE.findall(self.body))
        section_keys = set(self._card_blocks())
        self.assertEqual(
            keys - section_keys,
            set(),
            "cards not rendered as <section>: they lose their region semantics",
        )

    def test_every_card_names_itself_for_assistive_technology(self):
        for key in set(_CARD_KEY_RE.findall(self.body)):
            with self.subTest(key):
                self.assertRegex(
                    self.body,
                    rf'data-card-key="{re.escape(key)}"[^>]*aria-labelledby="[^"]+"'
                    rf"|"
                    rf'aria-labelledby="[^"]+"[^>]*data-card-key="{re.escape(key)}"',
                )

    def test_every_aria_labelledby_target_exists(self):
        referenced = set(re.findall(r'aria-labelledby="([^"]+)"', self.body))
        ids = set(re.findall(r'\sid="([^"]+)"', self.body))
        dangling = {
            ref for group in referenced for ref in group.split() if ref not in ids
        }
        self.assertEqual(dangling, set(), f"aria-labelledby points nowhere: {dangling}")


class CardScopeExposureTest(TestCase):
    """§28: a card must not reach a role its registry entry excludes."""

    def test_a_non_admin_never_receives_admin_only_cards(self):
        user = get_user_model().objects.create_user(
            email="card-identity-pl@edify.test",
            name="Card Identity PL",
            roles=["Program Lead"],
            active_role="Program Lead",
            password="x",
            is_active=True,
        )
        self.client.force_login(user)
        body = self.client.get("/dashboard").content.decode()

        admin_only = {
            c.key for c in CARD_REGISTRY if c.allowed_roles == frozenset({"ADMIN"})
        }
        self.assertTrue(admin_only, "expected some Admin-only cards")
        leaked = admin_only & set(_CARD_KEY_RE.findall(body))
        self.assertEqual(leaked, set(), f"Admin-only cards reached a PL: {leaked}")
