"""Phase 5: the Today workbench under test.

Pins: field roles get the page and non-field roles do not; the sections
render from real state (honest empty states included); the proposed-week
flow works end-to-end through the page's own POST endpoint; and a foreign
proposal can never be accepted through it.
"""

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.autopilot.models import ProposedPlan
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School


def _user(role, email):
    user = User.objects.create_user(
        email=email,
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        password="test-password",
        is_active=True,
    )
    staff = StaffProfile.objects.create(user=user, title=role)
    return user, staff


class TodayWorkbenchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cceo, cls.cceo_sp = _user("CCEO", "today-cceo@example.test")
        cls.accountant, _ = _user("Accountant", "today-acct@example.test")
        cls.region = Region.objects.create(name="TW Region")
        cls.district = District.objects.create(name="TW District", region=cls.region)
        cls.sub_county = SubCounty.objects.create(name="TW SC", district=cls.district)
        school = School.objects.create(
            school_id="TW-1",
            name="Today School",
            region=cls.region,
            district=cls.district,
            sub_county=cls.sub_county,
            school_type="client",
        )
        StaffSchoolAssignment.objects.create(staff=cls.cceo_sp, school_id=school.id)

    def test_the_dashboard_opens_on_today_and_the_old_door_leads_there(self):
        self.client.force_login(self.cceo)
        self.assertRedirects(
            self.client.get("/today"),
            "/dashboard?view=today",
            fetch_redirect_response=False,
        )
        response = self.client.get("/dashboard")
        self.assertEqual(response.context["dashboard_view"], "today")
        # The panel fetches the workbench once the dashboard has painted.
        self.assertContains(response, 'hx-get="/today/panel"')
        self.assertContains(self.client.get("/today/panel"), "Your next activity")

    def test_a_field_role_gets_the_workbench(self):
        self.client.force_login(self.cceo)
        response = self.client.get("/today/panel")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your next activity")
        self.assertContains(response, "Exceptions requiring attention")
        self.assertContains(response, "Your proposed week")
        # Honest empty states, never fabricated content.
        self.assertContains(response, "Nothing scheduled for today")

    def test_non_field_roles_never_see_it(self):
        self.client.force_login(self.accountant)
        response = self.client.get("/today")
        self.assertNotEqual(response.status_code, 200)

    def test_prepare_accept_week_end_to_end(self):
        self.client.force_login(self.cceo)
        response = self.client.post(
            "/today/action", {"action": "prepare_week"}, follow=True
        )
        self.assertEqual(response.status_code, 200)
        plan = ProposedPlan.objects.get(staff=self.cceo_sp)
        panel = self.client.get("/today/panel")
        self.assertContains(panel, "Today School")
        self.assertContains(panel, "Accept week")

        response = self.client.post(
            "/today/action",
            {"action": "accept_week", "plan": plan.id},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        plan.refresh_from_db()
        self.assertEqual(plan.status, "accepted")

    def test_a_foreign_proposal_cannot_be_accepted_here(self):
        other, other_sp = _user("CCEO", "today-other@example.test")
        from apps.autopilot.services import generate_week_proposal

        school = School.objects.create(
            school_id="TW-2",
            name="Other School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            school_type="client",
        )
        StaffSchoolAssignment.objects.create(staff=other_sp, school_id=school.id)
        plan = generate_week_proposal(other_sp)
        self.client.force_login(self.cceo)
        response = self.client.post(
            "/today/action", {"action": "accept_week", "plan": plan.id}
        )
        self.assertEqual(response.status_code, 403)
        plan.refresh_from_db()
        self.assertEqual(plan.status, "proposed")

    def test_todo_rows_surface_with_their_real_keys(self):
        # The seam that silently breaks: todo_service rows carry action_url/
        # description/priority/status_key. A real planned activity must
        # surface as a linked row, not an empty shell.
        from datetime import date as date_cls

        from apps.activities.models import Activity
        from apps.schools.models import School

        school = School.objects.get(school_id="TW-1")
        Activity.objects.create(
            activity_type="school_visit",
            status="planned",
            planned_date=date_cls.today(),
            fy="2027",
            school=school,
            responsible_staff_id=self.cceo_sp.id,
        )
        self.client.force_login(self.cceo)
        response = self.client.get("/today/panel")
        self.assertEqual(response.status_code, 200)
        waiting = response.context["today"]["waiting"]
        exceptions = response.context["today"]["exceptions"]
        rows = list(waiting) + list(exceptions)
        self.assertTrue(rows, "a planned activity must produce a To-Do row")
        for row in rows:
            self.assertIn("title", row)
            self.assertIn("action_url", row)
            self.assertContains(response, row["action_url"])

    def test_today_and_dashboard_are_one_sidebar_link(self):
        # Owner, 2026-09-14: "merge today and dashboard as dashboard".
        from apps.core.navigation import build_sidebar_for_user

        cceo_items = [
            item["label"]
            for section in build_sidebar_for_user(self.cceo, "/dashboard")
            for item in section["items"]
        ]
        self.assertIn("Dashboard", cceo_items)
        self.assertNotIn("Today", cceo_items)
        accountant_items = [
            item["label"]
            for section in build_sidebar_for_user(self.accountant, "/dashboard")
            for item in section["items"]
        ]
        self.assertNotIn("Today", accountant_items)


class ProgramLeadTodayTests(TestCase):
    """A Programme Lead's day is mostly other people's decisions (owner,
    2026-09-13): Today opens on what waits on the lead — leadership handoffs
    ahead of the lead's own field chores — then the team in the field, and a
    lead with no schools of their own gets one line instead of a route and a
    proposed week. The CCEO's workbench above is unchanged."""

    @classmethod
    def setUpTestData(cls):
        from apps.accounts.models import StaffSupervisorAssignment

        cls.pl, cls.pl_sp = _user("Program Lead", "today-pl@example.test")
        cls.officer, cls.officer_sp = _user("CCEO", "today-officer@example.test")
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.pl_sp, supervisee=cls.officer_sp
        )
        cls.other_pl, cls.other_pl_sp = _user("Program Lead", "today-pl2@example.test")
        cls.stranger, cls.stranger_sp = _user("CCEO", "today-stranger@example.test")
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.other_pl_sp, supervisee=cls.stranger_sp
        )
        cls.region = Region.objects.create(name="PLT Region")
        cls.district = District.objects.create(name="PLT District", region=cls.region)
        cls.team_school = School.objects.create(
            school_id="PLT-1",
            name="Team School",
            region=cls.region,
            district=cls.district,
        )
        cls.stranger_school = School.objects.create(
            school_id="PLT-2",
            name="Stranger School",
            region=cls.region,
            district=cls.district,
        )
        StaffSchoolAssignment.objects.create(
            staff=cls.officer_sp, school_id=cls.team_school.id
        )
        StaffSchoolAssignment.objects.create(
            staff=cls.stranger_sp, school_id=cls.stranger_school.id
        )

    def _activity(self, staff, school, **extra):
        from django.utils import timezone

        from apps.activities.models import Activity

        values = {
            "activity_type": "school_visit",
            "status": "scheduled",
            "planned_date": timezone.localdate(),
            "fy": "2027",
            "school": school,
            "responsible_staff_id": staff.id,
        }
        values.update(extra)
        return Activity.objects.create(**values)

    def test_waiting_on_you_comes_first_then_the_team_today(self):
        self._activity(self.officer_sp, self.team_school)
        self._activity(self.stranger_sp, self.stranger_school)
        self.client.force_login(self.pl)
        response = self.client.get("/today/panel")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertLess(html.index("data-today-waiting"), html.index("data-today-team"))
        self.assertLess(html.index("data-today-team"), html.index("Your next activity"))
        team = response.context["today"]["team_today"]
        self.assertEqual(
            [
                (g["name"], [a["where"] for a in g["activities"]])
                for g in team["groups"]
            ],
            [("today-officer", ["Team School"])],
        )
        self.assertEqual(team["activity_count"], 1)
        self.assertContains(response, "Team School")
        self.assertNotContains(response, "Stranger School")

    def test_a_lead_without_schools_gets_one_line_instead_of_route_and_week(self):
        self.client.force_login(self.pl)
        response = self.client.get("/today/panel")
        self.assertFalse(response.context["today"]["has_own_portfolio"])
        self.assertIsNone(response.context["today"]["proposal"])
        self.assertContains(response, "data-today-no-portfolio")
        self.assertNotContains(response, "Your proposed week")
        self.assertNotContains(response, "Your route ·")

    def test_a_lead_with_own_schools_keeps_route_and_week(self):
        own = School.objects.create(
            school_id="PLT-OWN", name="Own School", region=self.region
        )
        StaffSchoolAssignment.objects.create(staff=self.pl_sp, school_id=own.id)
        self.client.force_login(self.pl)
        response = self.client.get("/today/panel")
        self.assertTrue(response.context["today"]["has_own_portfolio"])
        self.assertContains(response, "Your proposed week")
        self.assertNotContains(response, "data-today-no-portfolio")

    def test_view_all_links_to_the_whole_queue(self):
        from unittest.mock import patch

        rows = [
            {
                "id": f"act-{n}",
                "title": f"Chore {n}",
                "description": "",
                "category": "Visit",
                "priority": "medium",
                "status_key": "waiting_me",
                "actionable": True,
                "action_url": "/my-plan",
            }
            for n in range(9)
        ]
        with patch(
            "apps.command_center.todo_service.get_cached_todos",
            return_value={"todos": rows, "total": 9},
        ):
            self.client.force_login(self.pl)
            response = self.client.get("/today/panel")
        self.assertContains(response, 'href="/todos"')
        self.assertContains(response, "View all 9")

    def test_leadership_handoffs_are_listed_before_the_lead_s_own_chores(self):
        from unittest.mock import patch

        from apps.frontend.views.today_views import WAITING_LIMIT, _split_todos

        def row(row_id, priority="medium", category="Visit"):
            return {
                "id": row_id,
                "title": row_id,
                "category": category,
                "priority": priority,
                "status_key": "waiting_me",
                "actionable": True,
                "action_url": "/todos",
            }

        queue = [
            row("act-1", "high"),
            row("sch-2-contact", "high"),
            row("wfr-appr-1", "medium", "Finance & Budget"),
            row("act-3"),
            row("leave-7", "low", "Team Leadership"),
        ]
        with patch(
            "apps.command_center.todo_service.get_cached_todos",
            return_value={"todos": queue, "total": len(queue)},
        ):
            lead_waiting, _exceptions, total = _split_todos(
                self.pl, leadership_first=True
            )
            officer_waiting, _e, _t = _split_todos(self.officer)
        self.assertEqual([t["id"] for t in lead_waiting][:2], ["wfr-appr-1", "leave-7"])
        self.assertEqual(total, 5)
        # The CCEO keeps the queue's own order.
        self.assertEqual(officer_waiting[0]["id"], "act-1")
        self.assertLessEqual(len(lead_waiting), WAITING_LIMIT)

    def test_the_lead_s_today_does_not_scale_with_the_team(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from apps.accounts.models import StaffSupervisorAssignment
        from apps.frontend.views.today_views import _team_today

        self._activity(self.officer_sp, self.team_school)
        with CaptureQueriesContext(connection) as captured:
            _team_today(self.pl)
        baseline = len(captured.captured_queries)
        for n in range(4):
            _officer, sp = _user("CCEO", f"today-more-{n}@example.test")
            StaffSupervisorAssignment.objects.create(
                supervisor=self.pl_sp, supervisee=sp
            )
            school = School.objects.create(
                school_id=f"PLT-M{n}", name=f"More {n}", region=self.region
            )
            self._activity(sp, school)
        with CaptureQueriesContext(connection) as captured:
            team = _team_today(self.pl)
        self.assertEqual(team["activity_count"], 5)
        self.assertLessEqual(len(captured.captured_queries), baseline)
