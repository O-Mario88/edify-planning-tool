"""The morning notices: each CCEO's day, and each Programme Lead's team.

Owner, 2026-09-24: "Notifications also should notify the CCEO of the
activities of that day. Notification for PL should be to monitor all the
plans."
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.activities.models import Activity
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.notifications.models import Notification
from apps.realtime import jobs
from apps.schools.models import School


def _staff(email, name, role):
    user = User.objects.create(
        email=email,
        name=name,
        roles=[role.value],
        active_role=role.value,
        is_active=True,
        status="active",
    )
    return user, StaffProfile.objects.create(user=user, title=name, country="Uganda")


class DailyPlanFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        region = Region.objects.create(name="Daily Region")
        district = District.objects.create(name="Daily District", region=region)
        cls.school = School.objects.create(
            school_id="DP-1", name="Sunrise Primary", region=region, district=district
        )
        cls.other_school = School.objects.create(
            school_id="DP-2", name="Hillside Primary", region=region, district=district
        )
        cls.lead_user, cls.lead = _staff(
            "dp-pl@t.test", "Lead Lena", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.busy_user, cls.busy = _staff("dp-busy@t.test", "Busy Ben", EdifyRole.CCEO)
        cls.idle_user, cls.idle = _staff("dp-idle@t.test", "Idle Ida", EdifyRole.CCEO)
        for officer in (cls.busy, cls.idle):
            StaffSupervisorAssignment.objects.create(
                supervisee=officer, supervisor=cls.lead
            )

        make = cls._activity
        # Ben's day: two to do (one written in each id space), one already
        # delivered this morning, one released — only the two are his plan.
        make(cls.busy.id, cls.school, "school_visit")
        make(cls.busy_user.id, cls.other_school, "follow_up_visit")
        make(cls.busy.id, cls.school, "coaching_visit", status="submitted_to_pl")
        make(cls.busy.id, cls.school, "school_visit", status="cancelled")
        # Past due, and a completion waiting on the lead.
        make(
            cls.idle.id,
            cls.school,
            "school_visit",
            planned=cls.today - timedelta(days=3),
        )

    @classmethod
    def _activity(cls, owner, school, kind, *, status="scheduled", planned=None):
        planned = planned or cls.today
        return Activity.objects.create(
            activity_type=kind,
            school=school,
            responsible_staff_id=owner,
            fy="2026",
            planned_date=planned,
            planned_month=planned.month,
            status=status,
        )

    def notices(self, user, event):
        return Notification.objects.filter(
            recipient_id=user.id, source_event_type=event
        )


class TheOfficerIsToldTheirDayTest(DailyPlanFixture):
    def test_a_cceo_gets_one_notice_naming_today_s_work(self):
        jobs._do_daily_plan_notifications()
        notice = self.notices(self.busy_user, jobs.DAILY_PLAN_TODAY_EVENT).get()
        self.assertEqual(notice.title, "Your plan today: 2 activities")
        self.assertIn("Sunrise Primary", notice.body)
        self.assertIn("Hillside Primary", notice.body)
        self.assertEqual(notice.target_route, "/dashboard?view=today")
        self.assertEqual(notice.priority, "normal")

    def test_an_officer_with_nothing_today_is_not_nagged(self):
        jobs._do_daily_plan_notifications()
        self.assertFalse(
            self.notices(self.idle_user, jobs.DAILY_PLAN_TODAY_EVENT).exists()
        )


class TheLeadIsToldWhatToMonitorTest(DailyPlanFixture):
    def test_the_lead_gets_the_team_s_day_in_one_notice(self):
        jobs._do_daily_plan_notifications()
        notice = self.notices(self.lead_user, jobs.PL_TEAM_DAILY_EVENT).get()
        self.assertEqual(notice.title, "Monitor your team's plans today")
        # Both of today's activities are Ben's — one officer, whichever id
        # space wrote each of them.
        self.assertIn("2 activities planned today by 1 officer;", notice.body)
        self.assertIn("1 past due", notice.body)
        self.assertIn("1 completion waiting on you", notice.body)
        self.assertEqual(notice.target_route, "/team-planning-oversight/")

    def test_a_lead_is_not_told_about_another_team(self):
        rival_user, rival = _staff(
            "dp-rival@t.test", "Rival Rob", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        jobs._do_daily_plan_notifications()
        self.assertFalse(
            self.notices(rival_user, jobs.PL_TEAM_DAILY_EVENT).exists(),
            "a lead with no officers has no team plans to monitor",
        )


class OncePerDayTest(DailyPlanFixture):
    def test_a_same_day_rerun_sends_nothing_even_after_archiving(self):
        first = jobs._do_daily_plan_notifications()
        self.assertEqual(first, 2)  # Ben and the lead
        Notification.objects.filter(recipient_id=self.busy_user.id).update(
            status="archived"
        )
        self.assertEqual(jobs._do_daily_plan_notifications(), 0)

    def test_tomorrow_closes_yesterday_s_notice(self):
        jobs._do_daily_plan_notifications()
        yesterday = self.notices(self.busy_user, jobs.DAILY_PLAN_TODAY_EVENT).get()
        jobs._do_daily_plan_notifications(today=self.today + timedelta(days=1))
        yesterday.refresh_from_db()
        self.assertIsNotNone(yesterday.resolved_at)
        self.assertEqual(yesterday.status, "archived")

    @override_settings(ENABLE_BACKGROUND_JOBS=False)
    def test_the_job_is_gated_like_every_other(self):
        jobs.daily_plan_notifications_job()
        self.assertFalse(
            Notification.objects.filter(
                source_event_type__in=(
                    jobs.DAILY_PLAN_TODAY_EVENT,
                    jobs.PL_TEAM_DAILY_EVENT,
                )
            ).exists()
        )


class TheSchedulerKnowsTheJobTest(TestCase):
    def test_it_is_registered_with_a_function(self):
        from apps.realtime.registry import JOB_REGISTRY

        names = {spec.name for spec in JOB_REGISTRY}
        self.assertIn("daily_plan_notifications", names)
        self.assertTrue(callable(jobs.daily_plan_notifications_job))
