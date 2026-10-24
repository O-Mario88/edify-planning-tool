"""Home's Priority actions for a CCEO and a Programme Lead (owner, 2026-10-24).

The owner set each role's list: a Programme Lead's is My Overdue Plans,
Follow up with CCEOs Overdue Plans, Schools Not Clustered, Verify CCEO
Completed Activities, Schools With No Visits, Schools With No Trainings,
Schools With No SSA and My Team Performance; a CCEO's is My Overdue Plans,
Schools Not Clustered, Schools With No Visits, Schools With No Trainings,
Schools With No SSA and My Performance. Each row opens the table that lists
what it counts, and its count is read from the same service as that table,
so the two cannot disagree. Every other role keeps the To-Do queue.

Owner, 2026-10-24 (later the same day): the overdue rows open the
dashboard's overdue table, a Lead's narrowed to their own plans or their
CCEOs'; a Lead's monitor rows open the dashboard's own table; and a school
is "with no visits" (or trainings, or SSA) until one is completed — a
planned one does not take it off the list.
"""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import urlencode

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity
from apps.command_center.home_priorities import role_priorities
from apps.command_center.home_service import build_home_queue
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.my_plan.past_due_service import get_past_due_dashboard_context
from apps.planning.planning_monitor import list_schools, own_monitor, planning_monitor
from apps.schools.models import School

LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "home-priorities",
    }
}

CCEO_KEYS = [
    "my_overdue",
    "not_clustered",
    "no_visit",
    "no_training",
    "no_ssa",
    "my_performance",
]
PL_KEYS = [
    "my_overdue",
    "team_overdue",
    "not_clustered",
    "verify",
    "no_visit",
    "no_training",
    "no_ssa",
    "team_performance",
]


def _staff(email, name, role):
    user = User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    return user, StaffProfile.objects.create(user=user, title=role)


@override_settings(CACHES=LOCMEM)
class HomePrioritiesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.today = timezone.localdate()
        cls.fy = get_operational_fy()
        region = Region.objects.create(name="Priority Region")
        cls.district = District.objects.create(name="Priority District", region=region)
        cls.lead, cls.lead_sp = _staff("prio-pl@t.org", "Lena Lead", "Program Lead")
        cls.cceo, cls.cceo_sp = _staff("prio-cceo@t.org", "Cara Field", "CCEO")
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.cceo_sp, supervisor=cls.lead_sp
        )
        cls.hr, _ = _staff("prio-hr@t.org", "Hana People", "Human Resources")

        def school(code):
            # Held by Cara, and in her portfolio, as an upload leaves it.
            held = School.objects.create(
                school_id=code,
                name=f"School {code}",
                region=region,
                district=cls.district,
                school_type="client",
                account_owner_id=cls.cceo_sp.id,
                account_owner_status="matched",
            )
            StaffSchoolAssignment.objects.create(staff=cls.cceo_sp, school_id=held.id)
            return held

        cls.visited = school("PRIO-1")
        cls.unvisited = school("PRIO-2")

        def work(owner, status, days, school=None):
            return Activity.objects.create(
                school=school or cls.visited,
                activity_type="school_visit",
                delivery_type="staff",
                status=status,
                responsible_staff_id=owner.id,
                fy=cls.fy,
                quarter="Q1",
                planned_date=cls.today + timedelta(days=days),
            )

        # Cara: one visit ahead, two overdue; one completion waiting on Lena.
        work(cls.cceo_sp, "scheduled", 5)
        work(cls.cceo_sp, "scheduled", -3)
        work(cls.cceo_sp, "scheduled", -9)
        work(cls.cceo_sp, "submitted_to_pl", -1)
        # Lena: one overdue of her own.
        work(cls.lead_sp, "scheduled", -2)

    def _rows(self, user):
        return {row["key"]: row for row in role_priorities(user)}

    def test_a_cceo_gets_the_owners_six_rows_in_order(self):
        rows = role_priorities(self.cceo)
        self.assertEqual([row["key"] for row in rows], CCEO_KEYS)
        # Each school row leads with its count, as the owner wrote them.
        for row, rest in zip(
            rows[1:5],
            ("Not Clustered", "With No Visits", "With No Trainings", "With No SSA"),
        ):
            with self.subTest(key=row["key"]):
                self.assertRegex(row["title"], rf"^\d[\d,]* Schools? {rest}$")

    def test_a_programme_lead_gets_the_owners_eight_rows_in_order(self):
        rows = role_priorities(self.lead)
        self.assertEqual([row["key"] for row in rows], PL_KEYS)
        titles = {row["key"]: row["title"] for row in rows}
        self.assertEqual(titles["team_overdue"], "Follow up with CCEOs Overdue Plans")
        self.assertEqual(titles["verify"], "Verify CCEO Completed Activities")
        self.assertEqual(titles["team_performance"], "My Team Performance")

    def test_any_other_role_keeps_the_todo_queue(self):
        self.assertIsNone(role_priorities(self.hr))
        self.assertIsNone(build_home_queue(self.hr)["role_rows"])

    def _on_dashboard(self, query: str, anchor: str) -> str:
        """A Lead's monitor table, carried on their dashboard."""
        return "/dashboard?" + urlencode({"fy": self.fy, "pm": query}) + f"#{anchor}"

    def test_each_cceo_row_opens_the_table_that_lists_what_it_counts(self):
        cceo = self._rows(self.cceo)
        # The dashboard's own overdue table, "What needs you now".
        self.assertEqual(
            cceo["my_overdue"]["url"], "/dashboard?view=week#what-needs-you-now"
        )
        self.assertEqual(
            cceo["not_clustered"]["url"], "/my-plan?list=not_clustered#plan-list"
        )
        self.assertEqual(cceo["no_visit"]["url"], "/my-plan?list=not_visited#plan-list")
        self.assertEqual(
            cceo["no_training"]["url"], "/my-plan?list=not_trained#plan-list"
        )
        self.assertEqual(cceo["no_ssa"]["url"], "/schools?gap=no_ssa")
        self.assertEqual(cceo["my_performance"]["url"], "/team-performance/")

    def test_each_lead_row_opens_the_dashboard_table_that_lists_it(self):
        lead = self._rows(self.lead)
        # The dashboard's overdue table, narrowed to whose plans the row names.
        self.assertEqual(
            lead["my_overdue"]["url"],
            "/dashboard?view=week&plans=own#what-needs-you-now",
        )
        self.assertEqual(
            lead["team_overdue"]["url"],
            "/dashboard?view=week&plans=team#what-needs-you-now",
        )
        # The Planning Monitor's tables, where the dashboard carries them,
        # opened at the table itself rather than the top of the monitor.
        fy = self.fy
        for key, gap in (
            ("not_clustered", "not_clustered"),
            ("no_visit", "not_visited"),
            ("no_training", "not_trained"),
            ("no_ssa", "no_ssa"),
        ):
            with self.subTest(key=key):
                self.assertEqual(
                    lead[key]["url"],
                    self._on_dashboard(
                        f"view=planning&fy={fy}&gap={gap}", "monitor-list"
                    ),
                )
        self.assertEqual(
            lead["verify"]["url"],
            self._on_dashboard(f"view=execution&fy={fy}", "completion-reviews"),
        )

    def test_a_leads_dashboard_links_open_the_table_they_name(self):
        """The dashboard draws the anchor each link names, once its monitor
        and overdue table are in."""
        self.client.force_login(self.lead)
        lead = self._rows(self.lead)
        dashboard = self.client.get(lead["my_overdue"]["url"]).content.decode()
        self.assertIn('id="what-needs-you-now"', dashboard)
        # Cara's past-due plans would open the team popup on a plain visit;
        # a link to one table is not covered by it.
        self.assertIn(
            "edifyPastDuePopupDue", self.client.get("/dashboard").content.decode()
        )
        for key in ("my_overdue", "team_overdue", "not_clustered", "verify"):
            with self.subTest(popup=key):
                html = self.client.get(lead[key]["url"]).content.decode()
                self.assertNotIn("edifyPastDuePopupDue", html)
        embed = {"HTTP_X_EDIFY_EMBED": "dashboard"}
        for key, anchor in (
            ("not_clustered", "monitor-list"),
            ("verify", "completion-reviews"),
        ):
            with self.subTest(key=key):
                from urllib.parse import parse_qs, urlsplit

                carried = parse_qs(urlsplit(lead[key]["url"]).query)["pm"][0]
                html = self.client.get(f"/planning-monitor/?{carried}", **embed)
                self.assertIn(f'id="{anchor}"', html.content.decode())

    def test_a_cceos_counts_are_their_own(self):
        cceo = self._rows(self.cceo)
        self.assertEqual(cceo["not_clustered"]["count"], 2)
        # A planned visit is not a completed one: both schools are still
        # without a visit (owner, 2026-10-24).
        self.assertEqual(cceo["no_visit"]["count"], 2)
        self.assertEqual(cceo["no_visit"]["title"], "2 Schools With No Visits")
        self.assertEqual(cceo["no_training"]["count"], 2)
        self.assertEqual(cceo["no_ssa"]["count"], 2)
        # A page to open, nothing to count.
        self.assertIsNone(cceo["my_performance"]["count"])

    def test_a_cceos_overdue_count_is_the_dashboard_tables(self):
        cceo = self._rows(self.cceo)
        table = get_past_due_dashboard_context(self.cceo)
        self.assertEqual(cceo["my_overdue"]["count"], table["past_due_total_count"])
        self.assertGreaterEqual(cceo["my_overdue"]["count"], 2)

    def test_a_cceos_school_counts_match_the_my_plan_list_they_open(self):
        officer = own_monitor(self.cceo, str(self.fy))
        cceo = self._rows(self.cceo)
        for key, listed in (
            ("not_clustered", "not_clustered"),
            ("no_visit", "not_visited"),
            ("no_training", "not_trained"),
        ):
            with self.subTest(key=key):
                self.assertEqual(
                    cceo[key]["count"], len(list_schools([officer], listed))
                )

    def test_only_completed_work_takes_a_school_off_the_list(self):
        """A visit, a training or an SSA counts once it is done and approved;
        planned, under way or waiting on the Lead, the school stays listed."""
        from apps.ssa.models import SsaRecord

        def listed():
            officer = own_monitor(self.cceo, str(self.fy))
            return {
                key: [s.name for s in list_schools([officer], key)]
                for key in ("not_visited", "not_trained", "no_ssa")
            }

        def done(school, activity_type):
            Activity.objects.create(
                school=school,
                activity_type=activity_type,
                delivery_type="staff",
                status="ia_verified",
                responsible_staff_id=self.cceo_sp.id,
                fy=self.fy,
                quarter="Q1",
                planned_date=self.today - timedelta(days=20),
            )

        both = ["School PRIO-1", "School PRIO-2"]
        # PRIO-1's visits are planned, not done: both schools are listed.
        self.assertEqual(
            listed(), {"not_visited": both, "not_trained": both, "no_ssa": both}
        )

        done(self.visited, "school_visit")
        SsaRecord.objects.create(
            school=self.visited,
            date_of_ssa=timezone.now(),
            fy=str(self.fy),
            quarter="Q1",
            verification_status="confirmed",
        )
        self.assertEqual(
            listed(),
            {
                "not_visited": ["School PRIO-2"],
                "not_trained": both,
                "no_ssa": ["School PRIO-2"],
            },
        )
        cceo = self._rows(self.cceo)
        self.assertEqual(cceo["no_visit"]["count"], 1)
        self.assertEqual(cceo["no_training"]["count"], 2)

        # An in-school training is a training, and a visit the school counts
        # (apps.planning.country_oversight.rules.counted_visit_q).
        done(self.unvisited, "in_school_training")
        self.assertEqual(
            listed(),
            {
                "not_visited": [],
                "not_trained": ["School PRIO-1"],
                "no_ssa": ["School PRIO-2"],
            },
        )

    def test_a_leads_counts_separate_their_own_work_from_their_cceos(self):
        lead = self._rows(self.lead)
        table = get_past_due_dashboard_context(self.lead)
        # Lena's one overdue visit, and Cara's two: the dashboard's My Plans
        # and Team Plans.
        self.assertEqual(lead["my_overdue"]["count"], 1)
        self.assertEqual(lead["my_overdue"]["count"], table["pl_own_past_due_count"])
        self.assertEqual(lead["team_overdue"]["count"], 2)
        self.assertEqual(lead["team_overdue"]["count"], table["pl_team_past_due_count"])
        self.assertEqual(lead["verify"]["count"], 1)
        # The team's schools: Cara holds both, and neither has a completed
        # visit, training or SSA.
        self.assertEqual(lead["not_clustered"]["count"], 2)
        self.assertEqual(lead["no_visit"]["count"], 2)
        self.assertEqual(lead["no_training"]["count"], 2)
        self.assertEqual(lead["no_ssa"]["count"], 2)

    def test_a_leads_school_counts_match_the_monitor_lists_they_open(self):
        officers = list(planning_monitor(self.lead, fy=str(self.fy))["totals"].officers)
        lead = self._rows(self.lead)
        for key, listed in (
            ("not_clustered", "not_clustered"),
            ("no_visit", "not_visited"),
            ("no_training", "not_trained"),
            ("no_ssa", "no_ssa"),
        ):
            with self.subTest(key=key):
                self.assertEqual(
                    lead[key]["count"], len(list_schools(officers, listed))
                )

    def test_outstanding_work_reads_critical_and_none_reads_clear(self):
        cceo = self._rows(self.cceo)
        self.assertEqual(cceo["my_overdue"]["status_label"], "Critical")
        self.assertEqual(cceo["my_overdue"]["status_tone"], "alert")
        Activity.objects.filter(planned_date__lt=self.today).update(status="cancelled")
        cleared = self._rows(self.cceo)["my_overdue"]
        self.assertEqual(cleared["count"], 0)
        self.assertEqual(cleared["status_label"], "All clear")
        self.assertEqual(cleared["status_tone"], "good")

    def test_a_figure_that_fails_shows_a_dash_not_zero(self):
        from unittest import mock

        with mock.patch(
            "apps.command_center.home_priorities._ssa_gap_count",
            side_effect=RuntimeError("boom"),
        ):
            row = self._rows(self.cceo)["no_ssa"]
        self.assertIsNone(row["count"])
        self.assertEqual(row["title"], "Schools With No SSA")
        self.assertEqual(row["status_label"], "")

    def test_the_rows_arrive_without_waiting_for_the_todo_queue(self):
        """A Lead's To-Do queue reads the team's whole target page (seven
        seconds on a seeded database, 2026-10-24): their rows do not need
        it, so the queue's figures arrive in a request of their own."""
        from unittest import mock

        self.client.force_login(self.lead)
        with mock.patch(
            "apps.command_center.todo_service.get_cached_todos",
            side_effect=AssertionError("the rows waited for the To-Do queue"),
        ):
            html = self.client.get("/home/queue").content.decode()
        self.assertIn('data-home-priority="verify"', html)
        self.assertIn('hx-get="/home/todo-figures"', html)

        figures = self.client.get("/home/todo-figures").content.decode()
        self.assertIn('id="home-figure-waiting_me"', figures)
        self.assertIn('hx-swap-oob="true"', figures)
        self.assertNotIn("data-home-priority", figures)

    def test_another_roles_queue_still_carries_its_figures(self):
        self.client.force_login(self.hr)
        html = self.client.get("/home/queue").content.decode()
        self.assertIn('id="home-figure-waiting_me"', html)
        self.assertNotIn("/home/todo-figures", html)

    def test_the_queue_fragment_draws_the_rows_with_their_links(self):
        self.client.force_login(self.cceo)
        html = self.client.get("/home/queue").content.decode()
        self.assertIn('data-home-priority="no_ssa"', html)
        self.assertIn('href="/schools?gap=no_ssa"', html)
        self.assertIn("2 Schools With No SSA", html)
        self.assertNotIn('data-home-empty="priority"', html)
