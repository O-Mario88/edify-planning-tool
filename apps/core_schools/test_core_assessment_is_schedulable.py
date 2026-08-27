"""CORE-01 (D5's user-visible half) — an unresolvable critical, on every school.

`CORE_PACKAGE_SPEC` declares the mandatory Core School package: one core
assessment, four visits, four trainings. The assessment slot is created with
the rest, and `resync_plan_completion` sets `CorePlan.assessment_completed`
from slots that have reached a done status. All of that works.

Nothing can put an activity in that slot. `resolve_item_for_workflow_kind`
returns None for `core_assessment_visit` because no catalogue item carries that
activity type — the type exists in the model's choices, carries a workload
weight, and is named across a dozen modules, but no governed item costs it. So
`assessment_completed` is 0 for every core school in every financial year.

What makes that a defect rather than an absence is what the readers do with it.
`core_assessment_missing` is the FIRST and most severe blocker on every core
school row, rendered "critical". It is a registered sendable TeamAction whose
ask is "Complete the core assessment" and whose stated reason is that the
package cannot be planned until the assessment is on file. And
`condition_still_holds` re-reads `plan.assessment_completed`, so the action can
never be resolved by anybody.

Put together: the platform tells a CCEO to do something, routes them to a page
with no control that does it, and keeps the accountability record open for
ever. This codebase already states the principle that settles it, a few lines
from the registration itself — where the responsible actor is somebody else,
the ask is not made of staff, because "manufacturing one against a CCEO for
work a partner has not done would hold the wrong person to it."

WHAT THIS FIXES AND WHAT IT DOES NOT

It does not create the catalogue item. What a Core Assessment costs is a
Country Director configuration decision, and the costing layer says so in as
many words: an unknown profile raises "Country Director configuration must be
repaired before scheduling." Inventing a price to make a test pass would be
manufacturing a passing result, which the audit mandate forbids in terms.

What it fixes is the platform's behaviour in the meantime. The gap is reported
where a Country Director will see it, in the health module that exists to catch
exactly this class ("If any of these has no active costed catalogue item,
ordinary work is blocked again — which is the entire defect this module exists
to catch early"). And the unresolvable ask is no longer sent to a member of
staff who cannot possibly close it.
"""

from __future__ import annotations

from django.test import TestCase


class CoreAssessmentSchedulabilityTest(TestCase):
    """The gap itself, and the check that has to notice it."""

    def test_every_core_package_slot_can_now_be_scheduled(self):
        """D5, answered: a Core Assessment costs what a school visit costs.

        This test used to assert the opposite — that the Core package declared
        a slot no catalogue item could serve — and said that if the list ever
        came back empty, the assessment had become schedulable and the rest of
        CORE-01 could be closed. That is what happened. The Country Director's
        answer was that a Core Assessment adds no cost because the staff are
        already making the visit, so ``COSTED_AS`` routes the kind to the
        school-visit costing and the gap closed.

        Kept rather than deleted, pointing the other way: if this list grows
        again, a mandatory slot has lost its costing and every core school is
        about to start collecting a blocker nobody can clear.
        """
        from apps.activity_catalogue.scheduling_health import core_package_kind_gaps

        self.assertEqual(
            core_package_kind_gaps(),
            [],
            "a mandatory Core package slot has no costed catalogue item again",
        )

    def test_the_assessment_resolves_to_the_school_visit_costing(self):
        """The decision itself, not just its effect.

        The gap could close for the wrong reason — somebody seeding a separate
        Core Assessment item with a made-up price, which is exactly what the
        Country Director said not to do. This asserts the answer that was
        actually given: the same item that costs a school visit costs this.
        """
        from apps.activity_catalogue.services import resolve_item_for_workflow_kind

        assessment = resolve_item_for_workflow_kind("core_assessment_visit")
        visit = resolve_item_for_workflow_kind("school_visit")
        self.assertIsNotNone(assessment, "the Core Assessment has no costing")
        self.assertEqual(
            assessment.stable_code,
            visit.stable_code,
            "the Core Assessment is being costed as something other than a "
            "school visit -- the decision was that it adds no separate cost",
        )

    def test_scheduling_health_is_green_on_the_core_package(self):
        from apps.activity_catalogue.scheduling_health import scheduling_health

        checks = {c["key"]: c for c in scheduling_health()["checks"]}
        self.assertIn(
            "scheduling_core_package_slot_unschedulable",
            checks,
            "the module whose whole purpose is catching a slot type with no "
            "costed item must actually check the Core package's own slots",
        )
        self.assertEqual(
            checks["scheduling_core_package_slot_unschedulable"]["status"], "pass"
        )

    def test_the_check_is_green_when_every_mandatory_slot_can_be_scheduled(self):
        """Guard the check from being a constant.

        A check that fails no matter what is worth as little as one that
        passes no matter what, so this drives the healthy branch with a real
        catalogue item rather than trusting the shape of the code.
        """
        from apps.activity_catalogue.models import (
            ActivityCatalogueItem,
            CatalogueStatus,
        )
        from apps.activity_catalogue.scheduling_health import (
            core_package_kind_gaps,
            scheduling_health,
        )

        template = ActivityCatalogueItem.objects.filter(
            stable_code="CORE_SCHOOL_FOLLOWUP_VISIT", status=CatalogueStatus.ACTIVE
        ).first()
        self.assertIsNotNone(template, "the core visit item is the control here")

        template.pk = None
        template.id = None
        template.stable_code = "TEST_ONLY_CORE_ASSESSMENT"
        template.name = "Test-only Core Assessment"
        template.activity_type = "core_assessment_visit"
        template.workflow_kind = "core_assessment_visit"
        template.standard_support = True
        template.save()

        self.assertEqual(core_package_kind_gaps(), [])
        checks = {c["key"]: c for c in scheduling_health()["checks"]}
        self.assertEqual(
            checks["scheduling_core_package_slot_unschedulable"]["status"], "pass"
        )


class TheUnresolvableAskIsNotSentToStaffTest(TestCase):
    """CORE-01's second half: nobody is held to work the platform blocks."""

    def test_the_core_assessment_ask_is_sendable_now_the_slot_can_be_scheduled(self):
        """The withholding was conditional, and the condition has lifted.

        This asserted the ask was NOT sendable, because the platform blocked
        the work: a CCEO was told to complete a core assessment and routed to
        a page with no control that schedules one. The withholding was written
        to lift by itself — "the moment a Country Director configures the
        catalogue item, the gap closes and the ask returns" — and D5 is that
        configuration. A genuinely missing assessment is worth chasing again.

        The mechanism still has to be present, so both halves are asserted:
        the ask is registered, and it is now sendable.
        """
        from apps.planning.action_service import ISSUE_PLAYBOOK, sendable_issue_keys

        self.assertIn("core_assessment_missing", ISSUE_PLAYBOOK)
        self.assertIn(
            "core_assessment_missing",
            sendable_issue_keys(),
            "the Core Assessment is schedulable now, so withholding the ask "
            "leaves a real gap unchased",
        )

    def test_it_becomes_sendable_again_once_the_slot_can_be_scheduled(self):
        from apps.activity_catalogue.models import (
            ActivityCatalogueItem,
            CatalogueStatus,
        )
        from apps.planning.action_service import sendable_issue_keys

        template = ActivityCatalogueItem.objects.filter(
            stable_code="CORE_SCHOOL_FOLLOWUP_VISIT", status=CatalogueStatus.ACTIVE
        ).first()
        template.pk = None
        template.id = None
        template.stable_code = "TEST_ONLY_CORE_ASSESSMENT_2"
        template.name = "Test-only Core Assessment 2"
        template.activity_type = "core_assessment_visit"
        template.workflow_kind = "core_assessment_visit"
        template.standard_support = True
        template.save()

        self.assertIn(
            "core_assessment_missing",
            sendable_issue_keys(),
            "the withholding is conditional on the gap, not a deletion — a "
            "configured platform must be able to chase a genuinely missing "
            "assessment",
        )

    def test_the_other_core_blocker_is_untouched(self):
        """Guard against over-correcting: package_behind IS resolvable."""
        from apps.planning.action_service import sendable_issue_keys

        self.assertIn("core_package_behind", sendable_issue_keys())
