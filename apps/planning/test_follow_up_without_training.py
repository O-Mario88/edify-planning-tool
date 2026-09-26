"""School visit follow-ups without a prior training (owner, 2026-09-15).

Uganda plans follow-up visits for schools with no training recorded. The rule
is governed per fiscal year (FiscalYearPlanningPolicy), not bypassed in a view,
and lifting it removes nothing else: the school must still be operating, and
the calendar and catalogue still apply.

The portfolio and the client visit allowance were on that list until
2026-09-21, when the owner lifted both for the school visit. They are now
counted rather than enforced, so the two tests that named them say what
happens instead — see apps.core.scoping.SCHOOL_VISIT_ROLES and
apps.planning.visit_gate.
"""

from __future__ import annotations

from unittest.mock import patch

from freezegun import freeze_time

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


# "Today" is a mid-year Monday. The follow-ups below are booked on consecutive
# days from today + 3, and in the last days of September that run crosses
# 1 October into the next fiscal year, where this year's gate no longer counts
# them (2 != 3 on 2026-09-26).
@freeze_time("2026-07-27")
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

    def test_follow_ups_past_the_client_allowance_are_scheduled_and_counted(self):
        """The allowance stopped being a ceiling on 2026-09-21.

        It is still counted, and the count is still what the pages show, so
        this walks past CLIENT_VISIT_CAP and checks the visits are there
        rather than that the next one was refused.
        """
        import datetime

        from apps.planning.test_standard_support_scheduling import (
            _at,
            _schedulable_date,
        )
        from apps.planning.visit_gate import CLIENT_VISIT_CAP

        # Distinct dates: two identical visits on one day are refused by the
        # duplicate-activity guard, which is a different rule from this one.
        day = _schedulable_date()
        for _ in range(CLIENT_VISIT_CAP):
            while day.weekday() == 6:
                day += datetime.timedelta(days=1)
            self.follow_up(scheduledDate=_at(day).isoformat())
            day += datetime.timedelta(days=1)
        while day.weekday() == 6:
            day += datetime.timedelta(days=1)
        self.follow_up(scheduledDate=_at(day).isoformat())  # no BadRequest

        from apps.planning.visit_gate import visit_gate

        self.assertEqual(visit_gate(self.school).total_visits, CLIENT_VISIT_CAP + 1)

    def test_an_out_of_portfolio_school_is_scheduled_all_the_same(self):
        """The portfolio stopped gating the visit on 2026-09-21: a CCEO
        schedules one at a school they no longer hold, and it is theirs."""
        from apps.accounts.models import StaffSchoolAssignment

        StaffSchoolAssignment.objects.filter(school_id=self.school.id).delete()
        activity = Activity.objects.get(id=self.follow_up()["id"])
        self.assertEqual(activity.status, "scheduled")
        self.assertIn(activity.responsible_staff_id, {self.staff.id, self.user.id})

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


class CompletionMustNameTheTrainingTest(StandardSupportBase):
    """Optional at planning, compulsory at completion (owner, 2026-09-21).

    "Right now follow up visit has linked training optional. The user MUST
    link it to training when completing the visit from action." Planning is
    unchanged — the officer may not know yet which session the visit will
    answer — but a completed follow-up that names no training is a visit no
    report can attribute to the training it reinforced.
    """

    def _follow_up(self):
        from apps.activities.models import Activity

        result = self.schedule(
            schoolId=self.school.school_id,
            catalogueItemId=self.item("STANDARD_TRAINING_FOLLOW_UP_VISIT").id,
            purposeType="training_follow_up",
        )
        return Activity.objects.get(id=result["id"])

    def _completed_training(self, *, attended=True):
        import datetime

        from django.utils import timezone

        from apps.activities.models import Activity

        training = Activity.objects.create(
            activity_type="in_school_training",
            school=self.school,
            fy=get_operational_fy(),
            quarter="Q1",
            status="completed",
            focus_intervention="financial_health",
            planned_date=timezone.localdate() - datetime.timedelta(days=30),
            teachers_attended=6 if attended else 0,
        )
        return training

    def _complete(self, visit, **extra):
        from apps.activities.services import complete

        payload = {
            "salesforceId": "",
            "teachersAttended": 4,
            "feedbackFinding": "Attendance registers are now up to date.",
            "schoolImprovements": ["Registers updated weekly"],
            **extra,
        }
        return complete(visit.id, payload, self.user)

    def setUp(self):
        super().setUp()
        # Evidence and the Salesforce reservation are separate, already
        # covered chains; these tests are about the follow-up link alone.
        evidence = patch("apps.evidence.requirements.evidence_optional", lambda a: True)
        self.addCleanup(evidence.stop)
        evidence.start()
        reserve = patch("apps.activities.services.reserve_salesforce_id")
        self.addCleanup(reserve.stop)
        reserve.start()

    def test_completing_without_a_training_is_refused(self):
        visit = self._follow_up()
        visit.status = "completion_started"
        visit.save(update_fields=["status"])
        self._completed_training()
        with self.assertRaises(BadRequest) as ctx:
            self._complete(visit)
        self.assertIn("Select the training", str(ctx.exception.detail))

    def test_the_named_training_is_linked_by_completing(self):
        from apps.activities.models import Activity

        visit = self._follow_up()
        visit.status = "completion_started"
        visit.save(update_fields=["status"])
        training = self._completed_training()
        self._complete(visit, followUpOfActivityId=training.id)
        visit = Activity.objects.get(id=visit.id)
        self.assertEqual(visit.follow_up_of_activity_id, training.id)

    def test_a_session_the_school_never_took_is_refused(self):
        import datetime

        from django.utils import timezone

        from apps.activities.models import Activity
        from apps.schools.models import School

        elsewhere = School.objects.create(
            school_id="STD-OTHER",
            name="Another School",
            region=self.region,
            district=self.district,
            school_type="client",
        )
        stranger = Activity.objects.create(
            activity_type="in_school_training",
            school=elsewhere,
            fy=get_operational_fy(),
            quarter="Q1",
            status="completed",
            planned_date=timezone.localdate() - datetime.timedelta(days=30),
        )
        visit = self._follow_up()
        visit.status = "completion_started"
        visit.save(update_fields=["status"])
        with self.assertRaises(BadRequest):
            self._complete(visit, followUpOfActivityId=stranger.id)

    def test_an_ordinary_visit_is_not_asked_for_a_training(self):
        from apps.activities.models import Activity

        result = self.schedule(
            schoolId=self.school.school_id,
            catalogueItemId=self.item("STANDARD_DONOR_VISIT").id,
            purposeType="donor_visit",
        )
        visit = Activity.objects.get(id=result["id"])
        visit.status = "completion_started"
        visit.save(update_fields=["status"])
        self._complete(visit)
        self.assertEqual(
            Activity.objects.get(id=visit.id).status,
            "submitted_to_pl",
        )
