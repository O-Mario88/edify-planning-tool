"""KPI cards must be addressable by a stable key, never by their wording.

``CDDashboardService`` read two of ``CDAnalyticsService``'s cards by display
label -- ``analytics["Overall Target Achievement"]`` and
``analytics["Budget Utilization"]``. Nothing tested that coupling, so the first
person to reword either card for clarity would have taken the Country Director
dashboard down with a KeyError. These tests make the label safe to edit.
"""

from __future__ import annotations

import ast
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ANALYTICS = Path(settings.BASE_DIR) / "apps" / "analytics"


def _source(name: str) -> str:
    return (ANALYTICS / name).read_text(encoding="utf-8")


class CardKeyContractTests(SimpleTestCase):
    def test_no_service_indexes_another_services_cards_by_label(self):
        """A subscript whose key is a Title Case string is a label lookup."""
        offenders = []
        for path in ANALYTICS.glob("*.py"):
            if path.name.startswith("test_"):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Subscript):
                    continue
                key = node.slice
                if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                    continue
                text = key.value
                # Registry-style keys are lower_snake_case; display labels
                # carry capitals and spaces.
                if " " in text and text != text.lower():
                    offenders.append(f"{path.name}:{node.lineno} -> {text!r}")

        self.assertEqual(
            offenders,
            [],
            "address KPI cards by their stable `key`, not their display label:\n"
            + "\n".join(offenders),
        )

    def test_every_cd_analytics_kpi_card_declares_a_key(self):
        source = _source("cd_analytics_service.py")
        tree = ast.parse(source)

        card_defs = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "card"
        ]
        self.assertTrue(card_defs, "expected a local `card` builder")

        kpi_card = next(
            (fn for fn in card_defs if fn.args.args and fn.args.args[0].arg == "key"),
            None,
        )
        self.assertIsNotNone(
            kpi_card,
            "the CD analytics KPI card builder must take `key` as its first "
            "argument so cards are addressable without their wording",
        )

    def test_cd_dashboard_looks_up_by_the_keys_analytics_publishes(self):
        """The two sides of the contract must agree, statically."""
        published = set()
        tree = ast.parse(_source("cd_analytics_service.py"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call) and getattr(node.func, "id", "") == "card"
            ):
                continue
            if not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                if first.value.islower():
                    published.add(first.value)

        self.assertTrue(published, "no card keys found in cd_analytics_service")

        consumed = set()
        dash = ast.parse(_source("cd_dashboard_service.py"))
        for node in ast.walk(dash):
            if not isinstance(node, ast.Subscript):
                continue
            target = node.value
            if getattr(target, "id", "") != "analytics":
                continue
            key = node.slice
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                consumed.add(key.value)

        self.assertTrue(consumed, "no analytics lookups found in cd_dashboard_service")
        missing = consumed - published
        self.assertEqual(
            missing,
            set(),
            f"cd_dashboard_service reads card keys that cd_analytics_service "
            f"does not publish: {sorted(missing)}",
        )
