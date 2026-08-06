"""What the risk detector must and must not fire on.

The false positives matter as much as the true ones. A supervision page that
flags work which is simply not due yet trains people to ignore it, and an
ignored risk list is the same as no risk list.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import SimpleTestCase

from apps.planning import risk_service
from apps.planning.oversight_service import (
    STAGE_PARTNER_AWAITING_SCHEDULE,
    STAGE_STAFF_SCHEDULED,
    PlanningOversightItem,
)

TODAY = date(2026, 6, 15)


def staff_item(**overrides) -> PlanningOversightItem:
    defaults = dict(
        stage=STAGE_STAFF_SCHEDULED,
        activity_id="act-1",
        activity_status="scheduled",
        planned_date=TODAY + timedelta(days=5),
        planned_cost=50_000,
        operational_owner_id="staff-1",
        operational_owner_name="James",
        evidence_status="none",
    )
    defaults.update(overrides)
    return PlanningOversightItem(**defaults)


def assignment_item(**overrides) -> PlanningOversightItem:
    defaults = dict(
        stage=STAGE_PARTNER_AWAITING_SCHEDULE,
        partner_assignment_id="pa-1",
        partner_id="p-1",
        partner_name="Partner X",
        managing_staff_id="staff-1",
        managing_staff_name="James",
        assigned_date=TODAY - timedelta(days=2),
        planned_cost=0,
    )
    defaults.update(overrides)
    return PlanningOversightItem(**defaults)


def keys(item) -> set[str]:
    return {r.key for r in risk_service.risks_for(item, TODAY)}


class NoFalsePositivesTest(SimpleTestCase):
    def test_healthy_future_work_carries_no_risk(self):
        self.assertEqual(keys(staff_item()), set())

    def test_a_fresh_partner_handover_is_not_yet_a_risk(self):
        """A partner given work on Friday is not delinquent on Monday."""
        self.assertEqual(keys(assignment_item()), set())

    def test_work_completed_on_time_carries_no_risk(self):
        item = staff_item(
            planned_date=TODAY - timedelta(days=10),
            activity_status="closed",
            evidence_status="accepted",
            salesforce_status="recorded",
        )
        self.assertEqual(keys(item), set())


class DetectorTest(SimpleTestCase):
    def test_a_stalled_partner_handover_fires(self):
        item = assignment_item(
            assigned_date=TODAY - timedelta(days=30),
            schedule_by_date=TODAY - timedelta(days=20),
        )
        self.assertIn("partner_not_scheduled", keys(item))

    def test_scheduled_work_without_a_cost_fires_critically(self):
        item = staff_item(planned_cost=0, cost_missing=True)

        risks = {r.key: r for r in risk_service.risks_for(item, TODAY)}

        self.assertIn("scheduled_without_cost", risks)
        self.assertEqual(
            risks["scheduled_without_cost"].severity, risk_service.CRITICAL
        )

    def test_an_unscheduled_assignment_is_never_flagged_for_having_no_cost(self):
        """It has no cost because nothing is scheduled. That is correct, not a risk."""
        item = assignment_item(
            assigned_date=TODAY - timedelta(days=30),
            schedule_by_date=TODAY - timedelta(days=20),
        )
        self.assertNotIn("scheduled_without_cost", keys(item))

    def test_overdue_work_fires_and_escalates_with_age(self):
        recent = staff_item(planned_date=TODAY - timedelta(days=3))
        old = staff_item(planned_date=TODAY - timedelta(days=40))

        recent_risk = {r.key: r for r in risk_service.risks_for(recent, TODAY)}
        old_risk = {r.key: r for r in risk_service.risks_for(old, TODAY)}

        self.assertEqual(recent_risk["activity_overdue"].severity, risk_service.HIGH)
        self.assertEqual(old_risk["activity_overdue"].severity, risk_service.CRITICAL)

    def test_delivered_work_without_evidence_fires(self):
        item = staff_item(
            planned_date=TODAY - timedelta(days=10),
            activity_status="completion_started",
            evidence_status="none",
        )
        self.assertIn("evidence_outstanding", keys(item))

    def test_finished_work_is_not_chased_for_evidence(self):
        """The verification chain has already ruled on it.

        Against live data the wider reading fired on every completed activity,
        which is the same as flagging nothing.
        """
        for status in ("completed", "closed", "ia_verified", "accountant_confirmed"):
            item = staff_item(
                planned_date=TODAY - timedelta(days=30),
                activity_status=status,
                evidence_status="none",
            )
            with self.subTest(status=status):
                self.assertNotIn("evidence_outstanding", keys(item))
                self.assertNotIn("salesforce_missing", keys(item))

    def test_salesforce_fires_only_while_the_id_is_actually_awaited(self):
        awaiting = staff_item(activity_status="salesforce_id_required")
        finished = staff_item(activity_status="completed")

        self.assertIn("salesforce_missing", keys(awaiting))
        self.assertNotIn("salesforce_missing", keys(finished))

    def test_work_that_never_started_is_overdue_not_evidence_missing(self):
        """One condition, one story — otherwise every late activity fires twice."""
        item = staff_item(
            planned_date=TODAY - timedelta(days=10), activity_status="scheduled"
        )

        found = keys(item)

        self.assertIn("activity_overdue", found)
        self.assertNotIn("evidence_outstanding", found)

    def test_an_ia_return_fires_critically(self):
        item = staff_item(activity_status="returned_by_ia")

        risks = {r.key: r for r in risk_service.risks_for(item, TODAY)}

        self.assertEqual(risks["ia_returned"].severity, risk_service.CRITICAL)

    def test_repeated_rescheduling_fires(self):
        self.assertNotIn("repeated_reschedule", keys(staff_item(reschedule_count=2)))
        self.assertIn("repeated_reschedule", keys(staff_item(reschedule_count=3)))


class RiskShapeTest(SimpleTestCase):
    def test_every_risk_names_an_owner_an_action_and_a_route(self):
        """A risk missing any of these is a notification, not a responsibility."""
        items = [
            staff_item(planned_cost=0, cost_missing=True),
            staff_item(planned_date=TODAY - timedelta(days=40)),
            staff_item(activity_status="returned_by_ia"),
            assignment_item(schedule_by_date=TODAY - timedelta(days=20)),
        ]
        for item in items:
            for risk in risk_service.risks_for(item, TODAY):
                with self.subTest(risk=risk.key):
                    self.assertTrue(risk.reason)
                    self.assertTrue(risk.recommended_action)
                    self.assertTrue(risk.route)
                    self.assertTrue(
                        risk.owner_id, "a risk with no owner cannot be sent"
                    )

    def test_annotate_names_who_moves_next(self):
        stalled = assignment_item(schedule_by_date=TODAY - timedelta(days=20))
        overdue = staff_item(planned_date=TODAY - timedelta(days=20))

        risk_service.annotate([stalled, overdue], today=TODAY)

        # A stalled handover waits on the partner; late staff work waits on staff.
        self.assertEqual(stalled.next_action_owner_name, "Partner X")
        self.assertEqual(overdue.next_action_owner_name, "James")

    def test_the_worst_risk_is_listed_first(self):
        item = staff_item(
            planned_date=TODAY - timedelta(days=40),
            cost_missing=True,
            planned_cost=0,
            reschedule_count=5,
        )

        risks = risk_service.risks_for(item, TODAY)

        self.assertEqual(risks[0].severity, risk_service.CRITICAL)
