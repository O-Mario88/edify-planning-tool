"""Planning is the only way an operational Activity comes into existence.

The governing rule is that every operational and funded Activity originates
from Planning: Planning decides what happens, who executes it, when, why, and
which Cost Catalogue rule applies. A code path that constructs an Activity
directly skips all of it — catalogue eligibility, SSA lineage, frequency,
scope, duplicate prevention, and the cost snapshot that must be written in the
same transaction.

The money side of this ecosystem already holds, and the audit that produced
this test is the evidence: ActivityScheduleCostLine, WeeklyFundRequestLine and
AdminBudgetLine each have exactly ONE construction site outside tests. One
chokepoint per record is what makes "no cost without a catalogue snapshot" and
"no fund-request line without a source cost line" enforceable at all.

Activity creation now has one path. Catch-up plans and accepted Field Debrief
recommendations both go through the canonical service without a scheduled
instant, so they carry Planning provenance but price nothing at creation.
The test fails the moment a new path appears.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

REPO = Path(settings.BASE_DIR)
APPS = REPO / "apps"

#: Direct construction of the model, in any of the forms an ORM offers.
CREATE_RE = re.compile(
    r"\bActivity\.objects\.(?:create|bulk_create|get_or_create|update_or_create)\b"
)

#: The canonical service. Activity is constructed here on purpose — this is
#: the funnel every other path is supposed to enter through.
CANONICAL = {"apps/activities/services.py"}

#: Explicitly permitted non-operational exceptions. The rule allows migration
#: and seed paths; it does not allow them to become an operational bypass, so
#: they are enumerated rather than pattern-matched.
PERMITTED_EXCEPTIONS = {
    "apps/core/management/commands/seed.py": (
        "Demo/dev seeding. Never runs against production data, and is gated by "
        "the environment stamp."
    ),
}

#: Operational exceptions are forbidden. Keep this explicit empty mapping so
#: a future waiver cannot be slipped in without changing a review-visible
#: contract test.
KNOWN_BYPASSES = {}


def _sources():
    for path in APPS.rglob("*.py"):
        rel = str(path.relative_to(REPO))
        if "/test" in rel or rel.endswith("tests.py") or "/migrations/" in rel:
            continue
        yield rel, path.read_text(encoding="utf-8")


class PlanningIsTheCreationGateTest(SimpleTestCase):
    def test_no_new_path_constructs_an_activity_directly(self):
        found = {rel for rel, source in _sources() if CREATE_RE.search(source)}
        allowed = CANONICAL | set(PERMITTED_EXCEPTIONS) | set(KNOWN_BYPASSES)
        unexpected = sorted(found - allowed)
        self.assertEqual(
            unexpected,
            [],
            "these construct an Activity outside Planning. Route them through "
            "apps.activities.services.create, or add an entry here with the "
            "reason — silently is the one option that is not available.",
        )

    def test_every_listed_bypass_still_exists(self):
        """A stale allowance is worse than none: it quietly re-permits a path
        that was actually fixed, so the next one to appear passes unnoticed."""
        found = {rel for rel, source in _sources() if CREATE_RE.search(source)}
        for rel in sorted(KNOWN_BYPASSES):
            self.assertIn(
                rel,
                found,
                f"{rel} no longer constructs an Activity — remove it from "
                "KNOWN_BYPASSES so the list keeps meaning what it says.",
            )

    def test_the_canonical_service_is_where_activities_are_built(self):
        source = (REPO / "apps/activities/services.py").read_text()
        self.assertTrue(
            CREATE_RE.search(source),
            "the funnel must be the thing that actually constructs the record",
        )


class MoneyRecordsHaveOneChokepointTest(SimpleTestCase):
    """The invariants that make the finance chain provable.

    Each of these is the single place its record can come into existence. That
    is what lets "no cost without a catalogue snapshot" and "no fund-request
    line without a source cost line" be enforced in one place instead of
    argued about per call site.
    """

    SINGLE_SOURCE = {
        "ActivityScheduleCostLine": "apps/budget/costing_service.py",
        "WeeklyFundRequestLine": "apps/fund_requests/weekly_service.py",
        "AdminBudgetLine": "apps/monthly_work_plan/services.py",
    }

    def test_each_money_record_is_constructed_in_exactly_one_module(self):
        for model, expected in self.SINGLE_SOURCE.items():
            pattern = re.compile(
                rf"\b{model}\.objects\.(?:create|bulk_create|get_or_create|"
                rf"update_or_create)\b|\b{model}\("
            )
            sites = sorted(rel for rel, source in _sources() if pattern.search(source))
            # The model's own module defines the class; that is not a call site.
            sites = [s for s in sites if not s.endswith("models.py")]
            with self.subTest(model=model):
                self.assertEqual(
                    sites,
                    [expected],
                    f"{model} must be built in one place. A second site is a "
                    "second set of rules for the same money.",
                )
