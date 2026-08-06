"""Contract tests for the canonical card registry.

These lock the rules the pre-registry codebase could not enforce: a card with
no identity, no declared audience, no drill-down and no answer for the empty
case.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.core.cards import (
    AMBIGUOUS_TITLES,
    CARD_REGISTRY,
    CardNotPermitted,
    CardSpec,
    CardType,
    all_cards,
    cards_for_page,
    cards_for_role,
    check,
    get_card,
    render_card,
)
from apps.core.metrics.spec import FilterBehaviour, Period
from apps.core.navigation import ADMIN, ALL_ROLES, PL


def _spec(**overrides) -> CardSpec:
    """A minimal valid spec, so each test can break exactly one rule."""
    base = dict(
        key="test_card",
        title="Test Card For Guards",
        purpose="A card used only by the registry contract tests.",
        question="Does the guard fire?",
        card_type=CardType.OPERATIONAL_QUEUE,
        owner_page="dashboard_main",
        allowed_roles=frozenset({ADMIN}),
        scope="test scope",
        service="apps.core.cards.tests",
        source_models=("activities.Activity",),
        period=Period.MONTH,
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        empty_message="Nothing here.",
        drilldown="/planning",
    )
    base.update(overrides)
    return CardSpec(**base)


class RegistryIntegrityTests(SimpleTestCase):
    def test_registry_passes_its_own_checks(self):
        check()

    def test_registry_is_not_empty(self):
        self.assertTrue(all_cards())

    def test_card_keys_are_unique(self):
        keys = [c.key for c in CARD_REGISTRY]
        self.assertEqual(len(keys), len(set(keys)))

    def test_no_two_cards_on_one_page_share_a_title(self):
        """§6: the required same-page duplicate count is zero."""
        seen: set[tuple[str, str]] = set()
        for card in CARD_REGISTRY:
            pair = (card.owner_page, card.title.casefold())
            with self.subTest(card.key):
                self.assertNotIn(pair, seen)
            seen.add(pair)

    def test_every_card_answers_a_question(self):
        for card in CARD_REGISTRY:
            with self.subTest(card.key):
                self.assertTrue(card.question.strip())
                self.assertTrue(card.purpose.strip())

    def test_every_card_declares_who_may_see_it(self):
        for card in CARD_REGISTRY:
            with self.subTest(card.key):
                self.assertTrue(card.allowed_roles)
                self.assertFalse(set(card.allowed_roles) - ALL_ROLES)

    def test_every_card_says_what_empty_means(self):
        for card in CARD_REGISTRY:
            with self.subTest(card.key):
                self.assertTrue(card.empty_message.strip())

    def test_every_card_has_a_drilldown_or_a_stated_reason(self):
        for card in CARD_REGISTRY:
            with self.subTest(card.key):
                self.assertTrue(card.drilldown or card.no_drilldown_reason)

    def test_no_card_uses_an_ambiguous_title(self):
        for card in CARD_REGISTRY:
            with self.subTest(card.key):
                self.assertNotIn(card.title.strip().casefold(), AMBIGUOUS_TITLES)

    def test_unregistered_key_is_rejected(self):
        with self.assertRaises(KeyError):
            get_card("no_such_card")


class SpecValidationTests(SimpleTestCase):
    def test_an_ambiguous_title_is_rejected(self):
        with self.assertRaises(ValueError):
            _spec(title="Summary")

    def test_a_missing_empty_message_is_rejected(self):
        with self.assertRaises(ValueError):
            _spec(empty_message="  ")

    def test_a_missing_question_is_rejected(self):
        with self.assertRaises(ValueError):
            _spec(question="")

    def test_an_unknown_role_is_rejected(self):
        with self.assertRaises(ValueError):
            _spec(allowed_roles=frozenset({"WIZARD"}))

    def test_no_allowed_roles_is_rejected(self):
        with self.assertRaises(ValueError):
            _spec(allowed_roles=frozenset())

    def test_a_missing_drilldown_needs_a_reason(self):
        with self.assertRaises(ValueError):
            _spec(drilldown=None)

    def test_a_drilldown_with_a_reason_is_contradictory(self):
        with self.assertRaises(ValueError):
            _spec(drilldown="/planning", no_drilldown_reason="contextual")

    def test_an_uppercase_key_is_rejected(self):
        with self.assertRaises(ValueError):
            _spec(key="Test_Card")

    def test_a_key_with_spaces_is_rejected(self):
        with self.assertRaises(ValueError):
            _spec(key="test card")

    def test_the_owner_page_may_not_repeat_as_a_secondary(self):
        with self.assertRaises(ValueError):
            _spec(secondary_pages=("dashboard_main",))


class ScopeTests(SimpleTestCase):
    KEY = "admin_priority_schools"

    def test_a_permitted_role_may_render_the_card(self):
        card = render_card(self.KEY, [{"name": "A"}], role_slug=ADMIN)
        self.assertEqual(card.card_key, self.KEY)

    def test_a_role_outside_the_registry_entry_is_refused(self):
        """§28: required unauthorized card data exposure is zero."""
        with self.assertRaises(CardNotPermitted):
            render_card(self.KEY, [{"name": "A"}], role_slug=PL)

    def test_the_check_can_be_skipped_when_the_page_already_gated(self):
        card = render_card(self.KEY, [{"name": "A"}])
        self.assertEqual(card.card_key, self.KEY)

    def test_cards_for_role_only_returns_permitted_cards(self):
        for card in cards_for_role(ADMIN):
            self.assertIn(ADMIN, card.allowed_roles)

    def test_cards_for_page_returns_that_pages_cards(self):
        for card in cards_for_page("dashboard_main"):
            self.assertIn("dashboard_main", card.approved_pages())


class RenderStateTests(SimpleTestCase):
    KEY = "admin_priority_schools"

    def test_records_render_as_a_populated_card(self):
        card = render_card(self.KEY, [{"name": "A"}, {"name": "B"}])
        self.assertFalse(card.is_empty)
        self.assertEqual(len(card.records), 2)

    def test_no_records_is_an_empty_card_with_a_reason(self):
        card = render_card(self.KEY, [])
        self.assertTrue(card.is_empty)
        self.assertEqual(card.empty_message, get_card(self.KEY).empty_message)

    def test_an_error_is_not_dressed_up_as_an_empty_queue(self):
        """§34: "All good" must never stand in for "we could not load it"."""
        card = render_card(self.KEY, [], error="upstream timeout")
        self.assertFalse(card.is_empty)
        self.assertEqual(card.error, "upstream timeout")

    def test_the_title_comes_from_the_registry_not_the_caller(self):
        card = render_card(self.KEY, [])
        self.assertEqual(card.title, get_card(self.KEY).title)

    def test_the_drilldown_defaults_to_the_registered_one(self):
        card = render_card(self.KEY, [])
        self.assertEqual(card.drilldown_url, get_card(self.KEY).drilldown)

    def test_a_caller_may_supply_a_filter_preserving_drilldown(self):
        card = render_card(self.KEY, [], drilldown_url="/schools?district=Gulu")
        self.assertEqual(card.drilldown_url, "/schools?district=Gulu")

    def test_the_rendered_dict_carries_the_key_for_the_dom_guard(self):
        card = render_card(self.KEY, []).as_dict()
        self.assertEqual(card["card_key"], self.KEY)
        self.assertIn("card_type", card)
        self.assertIn("empty_message", card)
