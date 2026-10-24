"""Tests for past-due 'What needs you now' service and notification dispatch."""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase, Client
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.my_plan import past_due_service
from apps.my_plan import services as my_plan_services
from apps.notifications.models import Notification
from apps.schools.models import School


class PastDueServiceTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        cls.region = Region.objects.create(id="r1_pd", name="Central Region")
        cls.district = District.objects.create(
            id="d1_pd", name="Wakiso", region=cls.region
        )
        cls.pl_user, cls.pl = cls._create_staff(
            "pl_pd@test.com", "Patricia Lead", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.cceo_user, cls.cceo = cls._create_staff(
            "cceo_pd@test.com", "Charles CCEO", EdifyRole.CCEO
        )
        StaffSupervisorAssignment.objects.create(supervisee=cls.cceo, supervisor=cls.pl)

        cls.school = School.objects.create(
            school_id="sch_pd_1",
            name="St. Jude Primary",
            district=cls.district,
            region=cls.region,
        )

        today = timezone.localdate()
        # 1. CCEO past-due school visit
        cls.cceo_past_due_visit = Activity.objects.create(
            activity_type="school_visit",
            status="scheduled",
            planned_date=today - timedelta(days=3),
            school=cls.school,
            responsible_staff_id=cls.cceo.id,
            fy=cls.fy,
        )

        # 2. CCEO upcoming school visit
        cls.cceo_upcoming_visit = Activity.objects.create(
            activity_type="school_visit",
            status="scheduled",
            planned_date=today + timedelta(days=2),
            school=cls.school,
            responsible_staff_id=cls.cceo.id,
            fy=cls.fy,
        )

        # 3. PL own past-due cluster meeting
        cls.pl_past_due_meeting = Activity.objects.create(
            activity_type="cluster_meeting",
            status="scheduled",
            planned_date=today - timedelta(days=5),
            responsible_staff_id=cls.pl.id,
            fy=cls.fy,
        )

    @classmethod
    def _create_staff(cls, email, name, role):
        user = User.objects.create(
            email=email,
            name=name,
            roles=[role.value],
            active_role=role.value,
            status="active",
            is_active=True,
        )
        user.set_password("edify")
        user.save()
        profile = StaffProfile.objects.create(user=user, title=name)
        return user, profile

    def test_cceo_dashboard_past_due_contains_only_own_past_due(self):
        ctx = past_due_service.get_past_due_dashboard_context(self.cceo_user)
        self.assertFalse(ctx["is_pl"])
        self.assertEqual(ctx["past_due_total_count"], 1)
        self.assertEqual(len(ctx["past_due_school_visits"]), 1)
        self.assertEqual(
            ctx["past_due_school_visits"][0]["id"], self.cceo_past_due_visit.id
        )
        self.assertTrue(ctx["past_due_school_visits"][0]["is_own"])

    def test_pl_dashboard_past_due_contains_both_own_and_team_past_due(self):
        ctx = past_due_service.get_past_due_dashboard_context(self.pl_user)
        self.assertTrue(ctx["is_pl"])
        self.assertEqual(ctx["past_due_total_count"], 2)
        self.assertEqual(ctx["pl_own_past_due_count"], 1)
        self.assertEqual(ctx["pl_team_past_due_count"], 1)

        # PL's own meeting
        self.assertEqual(len(ctx["past_due_cluster_meetings"]), 1)
        self.assertEqual(
            ctx["past_due_cluster_meetings"][0]["id"], self.pl_past_due_meeting.id
        )
        self.assertTrue(ctx["past_due_cluster_meetings"][0]["is_own"])

        # CCEO's visit under PL's team
        self.assertEqual(len(ctx["past_due_school_visits"]), 1)
        self.assertEqual(
            ctx["past_due_school_visits"][0]["id"], self.cceo_past_due_visit.id
        )
        self.assertFalse(ctx["past_due_school_visits"][0]["is_own"])
        self.assertEqual(ctx["past_due_school_visits"][0]["owner"], "Charles CCEO")
        self.assertEqual(
            ctx["past_due_school_visits"][0]["owner_first_name"], "Charles"
        )

    def test_a_lead_can_open_only_their_own_past_due_plans(self):
        """Home's "My Overdue Plans" opens the table on the Lead's own plans
        alone (owner, 2026-10-24), read on the server so every page of the
        table holds only theirs."""
        ctx = past_due_service.get_past_due_dashboard_context(self.pl_user, scope="own")
        self.assertEqual(ctx["past_due_scope"], "own")
        rows = [
            *ctx["past_due_school_visits"],
            *ctx["past_due_cluster_trainings"],
            *ctx["past_due_cluster_meetings"],
        ]
        self.assertEqual([r["id"] for r in rows], [self.pl_past_due_meeting.id])
        self.assertEqual(ctx["past_due_visits_count"], 0)
        self.assertEqual(ctx["past_due_meetings_count"], 1)
        # The whose-plans tabs still say how many each holds.
        self.assertEqual(ctx["past_due_total_count"], 2)
        self.assertEqual(ctx["pl_own_past_due_count"], 1)
        self.assertEqual(ctx["pl_team_past_due_count"], 1)

    def test_a_lead_can_open_only_their_cceos_past_due_plans(self):
        ctx = past_due_service.get_past_due_dashboard_context(
            self.pl_user, scope="team"
        )
        self.assertEqual(ctx["past_due_scope"], "team")
        rows = [
            *ctx["past_due_school_visits"],
            *ctx["past_due_cluster_trainings"],
            *ctx["past_due_cluster_meetings"],
        ]
        self.assertEqual([r["id"] for r in rows], [self.cceo_past_due_visit.id])
        self.assertEqual(ctx["past_due_meetings_count"], 0)

    def test_an_unknown_scope_or_a_cceo_reads_every_plan(self):
        ctx = past_due_service.get_past_due_dashboard_context(
            self.pl_user, scope="everyone-else"
        )
        self.assertEqual(ctx["past_due_scope"], "")
        self.assertEqual(len(ctx["past_due_school_visits"]), 1)
        self.assertEqual(len(ctx["past_due_cluster_meetings"]), 1)
        # A CCEO's plans are all their own: there is no team to narrow away.
        own = past_due_service.get_past_due_dashboard_context(
            self.cceo_user, scope="team"
        )
        self.assertEqual(own["past_due_scope"], "")
        self.assertEqual(len(own["past_due_school_visits"]), 1)

    def test_the_leads_dashboard_opens_the_narrowed_table(self):
        client = Client()
        client.force_login(self.pl_user)
        html = client.get("/dashboard?view=week&plans=own").content.decode()
        # The folded "All overdue plans" opens, on My Plans, and the team's
        # past-due popup does not cover it.
        self.assertRegex(html, r"<details[^>]*data-pl-backlog[^>]*\bopen\b")
        self.assertIn("activeScope: 'own'", html)
        self.assertNotIn("edifyPastDuePopupDue", html)
        table = html[html.index('id="what-needs-you-now"') :]
        table = table[: table.index("</details>")]
        self.assertNotIn("Send to Charles", table)

        plain = client.get("/dashboard?view=week").content.decode()
        self.assertIn("Send to Charles", plain)
        self.assertNotRegex(plain, r"<details[^>]*data-pl-backlog[^>]*\bopen\b")
        self.assertIn("activeScope: 'all'", plain)

    def test_my_plan_excludes_past_due_and_shows_upcoming(self):
        # When CCEO views My Plan for the FY, only upcoming visit should be present in category tables
        ctx = my_plan_services.get_frontend_context(
            self.cceo_user, {"period": "fy", "fy": self.fy}
        )
        visit_ids = [v["id"] for v in ctx["school_visits"]]
        self.assertIn(self.cceo_upcoming_visit.id, visit_ids)
        self.assertNotIn(self.cceo_past_due_visit.id, visit_ids)

    def test_notify_past_due_activity_endpoint(self):
        client = Client()
        client.force_login(self.pl_user)

        response = client.post(
            f"/dashboard/notify-past-due/{self.cceo_past_due_visit.id}/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Sent to Charles", response.content.decode("utf-8"))

        # Verify notification in database
        notif = Notification.objects.filter(
            context_type="activity",
            context_id=self.cceo_past_due_visit.id,
            source_event_type="pl_activity_overdue_reminder",
        ).first()
        self.assertIsNotNone(notif)
        self.assertEqual(notif.priority, "high")
        self.assertIn("Action Required", notif.title)
        self.assertIn("past due", notif.body)
        self.assertEqual(notif.target_route, f"/my-plan/{self.cceo_past_due_visit.id}")
