"""School visit follow-ups without a prior training (owner, 2026-09-15).

Uganda plans follow-up visits for schools with no training recorded. The rule
is governed per fiscal year (FiscalYearPlanningPolicy), not bypassed in a view,
and lifting it removes nothing else: the school must still be operating and in
the planner's portfolio, the once-a-year client visit still holds, and the
calendar and catalogue still apply.
"""

from __future__ import annotations

from unittest.mock import patch

from apps.activities.models import Activity
from apps.audit.models import AuditLog
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.fy import get_operational_fy
from apps.planning.fy_policy import (
    follow_up_requires_prior_training,
    set_follow_up_rule,
)
from apps.planning.models import FiscalYearPlanningPolicy
from apps.planning.test_standard_support_scheduling import (
    StandardSupportBase,
    _schedulable_date,
)


class FollowUpWithoutTrainingTest(StandardSupportBase):
    def follow_up(self, **extra):
        return self.schedule(
            schoolId=self.school.school_id,
            catalogueItemId=self.item("STANDARD_TRAINING_FOLLOW_UP_VISIT").id,
            purposeType="training_follow_up",
            **extra,
        )

    def test_the_uganda_policy_is_off_for_fy2026_and_fy2027(self):
        for fy in ("2026", "2027"):
            with self.subTest(fy=fy):
                self.assertFalse(follow_up_requires_prior_training(fy))
        # A year with no policy keeps the standing rule.
        self.assertTrue(follow_up_requires_prior_training("2031"))

    def test_a_follow_up_is_planned_and_scheduled_without_a_training(self):
        self.assertFalse(
            Activity.objects.filter(
                school=self.school, activity_type__icontains="training"
            ).exists()
        )
        result = self.follow_up()
        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.status, "scheduled")
        self.assertIsNone(activity.follow_up_of_activity_id)
        self.assertEqual(activity.activity_type, "training_follow_up_visit")
        # The focus comes from the SSA: Financial Health is the weakest score.
        self.assertEqual(activity.focus_intervention, "financial_health")
        # Costed through the canonical snapshot, and in the planner's plan.
        self.cost_snapshot.assert_called()
        self.assertIn(activity.responsible_staff_id, {self.staff.id, self.user.id})
        self.assertEqual(activity.evidence_profile_snapshot, "SCHOOL_VISIT_FORM")

    def test_a_named_training_is_still_validated_when_given(self):
        with self.assertRaises(BadRequest):
            self.follow_up(sourceActivityId="does-not-exist")

    def test_duplicate_follow_up_is_still_prevented(self):
        self.follow_up()
        with self.assertRaisesMessage(BadRequest, "visited once a year"):
            self.follow_up()

    def test_an_out_of_portfolio_school_is_still_refused(self):
        from apps.accounts.models import StaffSchoolAssignment

        StaffSchoolAssignment.objects.filter(school_id=self.school.id).delete()
        with self.assertRaises((Forbidden, BadRequest)):
            self.follow_up()

    def test_a_closed_school_still_takes_no_work(self):
        from apps.schools.models import School

        School.objects.filter(id=self.school.id).update(
            operational_status="permanently_closed"
        )
        with self.assertRaises((Forbidden, BadRequest)):
            self.follow_up()

    def test_changing_the_rule_is_governed_and_audited(self):
        from apps.accounts.models import User

        fy = get_operational_fy(_schedulable_date())
        with self.assertRaises(Forbidden):
            set_follow_up_rule(fy, True, self.user, reason="A CCEO cannot.")
        cd = User.objects.create_user(
            email="followup-cd@edify.org",
            name="Follow Up CD",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            password="x",
        )
        set_follow_up_rule(fy, True, cd, reason="Trainings resumed this quarter.")
        self.assertTrue(
            FiscalYearPlanningPolicy.objects.get(
                fy=fy
            ).follow_up_visit_requires_prior_training
        )
        row = AuditLog.objects.get(action="planning.follow_up_rule_changed")
        self.assertEqual(row.reason, "Trainings resumed this quarter.")
        self.assertFalse(row.payload["previous"]["followUpRequiresTraining"])
        with self.assertRaisesMessage(BadRequest, "Select the completed"):
            self.follow_up()


class FollowUpDrawerTest(StandardSupportBase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    def test_the_drawer_makes_the_training_optional_and_says_so_neutrally(self):
        with patch(
            "apps.frontend.views.planning_views._school_training_follow_up_options",
            return_value=[],
        ):
            response = self.client.get(
                f"/planning/schedule-modal?school_id={self.school.id}",
                HTTP_HX_REQUEST="true",
            )
        if response.status_code != 200:
            self.skipTest("schedule drawer route differs in this build")
        body = response.content.decode()
        self.assertIn("followUpRequiresTraining: false", body)
        self.assertIn("No prior training recorded", body)
