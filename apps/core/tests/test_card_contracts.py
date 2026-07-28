"""Every registered card's declared contract must hold against the real app.

The registry can say anything; these tests check that what it says is true.
A drill-down that 404s, or a card promising a role it never reaches, is worse
than no declaration at all -- it looks audited.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import resolve
from django.urls.exceptions import Resolver404

from apps.core.cards import CARD_REGISTRY, get_card, render_card
from apps.core.navigation import PAGE_PERMISSIONS


class DrilldownResolutionTests(TestCase):
    """§30: every card's drill-down must be a route that exists."""

    def test_every_declared_drilldown_resolves_to_a_view(self):
        unresolved = []
        for card in CARD_REGISTRY:
            if not card.drilldown:
                continue
            try:
                resolve(card.drilldown)
            except Resolver404:
                unresolved.append(f"{card.key} -> {card.drilldown}")
        self.assertEqual(unresolved, [], f"card drill-downs that 404: {unresolved}")

    def test_every_drilldown_is_an_absolute_path(self):
        for card in CARD_REGISTRY:
            if card.drilldown:
                with self.subTest(card.key):
                    self.assertTrue(
                        card.drilldown.startswith("/"),
                        f"{card.key}: {card.drilldown!r} is not a path",
                    )

    def test_a_card_without_a_drilldown_explains_itself(self):
        for card in CARD_REGISTRY:
            if not card.drilldown:
                with self.subTest(card.key):
                    self.assertTrue(card.no_drilldown_reason.strip())


class DrilldownReachabilityTests(TestCase):
    """A drill-down the card's own audience cannot open is a dead end."""

    def _user(self, role):
        return get_user_model().objects.create_user(
            email=f"card-drill-{role.lower()}@edify.test",
            name=f"Card Drill {role}",
            roles=[role],
            active_role=role,
            password="x",
            is_active=True,
        )

    def test_an_admin_can_open_every_admin_card_drilldown(self):
        self.client.force_login(self._user("Admin"))
        failures = []
        for card in CARD_REGISTRY:
            if not card.drilldown or "ADMIN" not in card.allowed_roles:
                continue
            response = self.client.get(card.drilldown, follow=True)
            if response.status_code != 200:
                failures.append(
                    f"{card.key} -> {card.drilldown} ({response.status_code})"
                )
        self.assertEqual(
            failures,
            [],
            f"drill-downs the card's own audience cannot open: {failures}",
        )


class ScopeDeclarationTests(TestCase):
    """A card's audience must not exceed the page it lives on."""

    def test_allowed_roles_are_a_subset_of_the_owning_pages_permissions(self):
        """§28: a card cannot admit a role the page itself refuses.

        `dashboard_main` is the generic dashboard fall-through, whose route
        permission is `dashboard`; every other owning page names its own key.
        """
        page_permission_key = {"dashboard_main": "dashboard"}
        violations = []
        for card in CARD_REGISTRY:
            key = page_permission_key.get(card.owner_page, card.owner_page)
            allowed_on_page = PAGE_PERMISSIONS.get(key)
            if allowed_on_page is None:
                continue
            excess = set(card.allowed_roles) - set(allowed_on_page)
            if excess:
                violations.append(f"{card.key}: {sorted(excess)}")
        self.assertEqual(
            violations,
            [],
            f"cards admitting roles their page refuses: {violations}",
        )


class EmptyAndErrorStateTests(TestCase):
    """§§31/34: empty and error must be distinguishable, always."""

    KEY = "admin_attention_needed"

    def test_an_empty_card_states_why_it_is_empty(self):
        card = render_card(self.KEY, [])
        self.assertTrue(card.is_empty)
        self.assertTrue(card.empty_message.strip())
        self.assertIsNone(card.error)

    def test_an_errored_card_is_never_reported_as_empty(self):
        card = render_card(self.KEY, [], error="database timeout")
        self.assertFalse(card.is_empty)
        self.assertIsNotNone(card.error)

    def test_every_registered_card_has_a_distinct_empty_message(self):
        """A shared "No data" tells the reader nothing about which queue."""
        messages = [c.empty_message.strip().casefold() for c in CARD_REGISTRY]
        generic = {"no data", "none", "empty", "nothing"}
        for card in CARD_REGISTRY:
            with self.subTest(card.key):
                self.assertNotIn(card.empty_message.strip().casefold(), generic)
        # Not required to be globally unique, but near-total repetition would
        # mean the messages are boilerplate rather than written for the card.
        self.assertGreater(len(set(messages)), len(messages) // 2)

    def test_the_empty_message_reads_as_a_sentence(self):
        for card in CARD_REGISTRY:
            with self.subTest(card.key):
                self.assertTrue(card.empty_message[0].isupper())
                self.assertTrue(card.empty_message.rstrip().endswith("."))


class PurposeContractTests(TestCase):
    """§9: a card must be able to say what it does *not* mean, when it matters."""

    def test_cards_whose_scope_could_be_over_read_say_so(self):
        """Spot-check: the cards most easily misread carry a disclaimer."""
        for key in (
            "admin_priority_schools",
            "admin_ssa_intervention_extremes",
            "admin_budget_and_fund_request_snapshot",
        ):
            with self.subTest(key):
                self.assertTrue(get_card(key).does_not_mean.strip())
