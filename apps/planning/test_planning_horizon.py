"""Plans dated into the next fiscal year count as planned (owner, 2026-09-23).

"Those badges are not fetching the actual data from the database. They look
like hardcoded because most of the schools planned through cluster and
scheduling should appear as planned."

They were reading the database, for one year. Pages open on the operational
year, and staff schedule forward into whichever year the date lands: in
September nearly every new plan is dated October, the next fiscal year, so the
Planning list and the Cluster School List read those schools as Not Planned.
The operational year now reads forward (``fy_policy.planning_horizon``); an
earlier year still reads alone.
"""

from __future__ import annotations

import datetime
import re

from django.utils import timezone

from apps.activities.models import Activity, ClusterActivityAttendance
from apps.planning.fy_policy import horizon_label, planning_horizon
from apps.planning.school_planning_badges import SchoolPlanningBadgeService
from apps.planning.test_school_planning_badges import FY, BadgeFixture

NEXT_FY = str(int(FY) + 1)
PREVIOUS_FY = str(int(FY) - 1)
#: The first October of the next fiscal year: the dates people plan in September.
OCTOBER = datetime.date(int(FY), 10, 20)


def _row(html: str, school) -> str:
    start = html.index(f'id="select-planning-school-{school.id}"')
    return html[start : html.find("</tr>", start)]


def _cluster_row(html: str, school) -> str:
    start = html.index(f"cluster-school-details-{school.id}")
    return html[start : html.find("</tr>", start)]


def _chip_labels(html: str) -> list[str]:
    return re.findall(r'class="school-planning-badge"[^>]*>([^<]+)<', html)


class PlanningHorizonTest(BadgeFixture):
    def test_the_operational_year_reads_forward_and_other_years_read_alone(self):
        self.assertEqual(planning_horizon(FY)[:2], (FY, NEXT_FY))
        self.assertEqual(planning_horizon(PREVIOUS_FY), (PREVIOUS_FY,))
        self.assertEqual(planning_horizon(NEXT_FY), (NEXT_FY,))
        self.assertEqual(horizon_label((FY,)), f"FY {FY}")
        self.assertEqual(horizon_label((NEXT_FY, FY)), f"FY {FY}–{NEXT_FY}")


class NextYearPlansAreBadgedTest(BadgeFixture):
    def setUp(self):
        super().setUp()
        # Hope: a visit planned in September for October (next fiscal year).
        self.visit = self._activity(self.hope, fy=NEXT_FY, day=OCTOBER)
        # Grace: invited to a Group Training the cluster planned for October.
        session = Activity.objects.create(
            activity_type="cluster_training",
            cluster=self.cluster,
            fy=NEXT_FY,
            quarter="Q1",
            planned_date=OCTOBER,
            scheduled_date=timezone.make_aware(
                datetime.datetime.combine(OCTOBER, datetime.time(9))
            ),
            status="scheduled",
            responsible_staff_id=self.cceo.id,
            delivery_type="staff",
        )
        ClusterActivityAttendance.objects.create(
            activity=session, school=self.grace, invited=True, attended=False
        )
        self.client.force_login(self.user)

    def test_the_badges_count_next_year_plans_on_the_operational_year(self):
        badges = SchoolPlanningBadgeService.get_for_schools(
            [self.hope.id, self.grace.id, self.victory.id],
            financial_year=planning_horizon(FY),
        )
        self.assertEqual(badges[self.hope.id].visits.planned_count, 1)
        self.assertEqual(badges[self.hope.id].visits.next_date, OCTOBER)
        self.assertEqual(badges[self.grace.id].trainings.planned_count, 1)
        self.assertEqual(badges[self.victory.id].visits.total, 0)

    def test_an_earlier_year_does_not_read_forward(self):
        badges = SchoolPlanningBadgeService.get_for_schools(
            [self.hope.id], financial_year=planning_horizon(PREVIOUS_FY)
        )
        self.assertEqual(badges[self.hope.id].visits.total, 0)

    def test_the_planning_list_shows_them_as_planned(self):
        html = self.client.get(f"/planning?tab=client&fy={FY}&per_page=50")
        html = html.content.decode()
        self.assertEqual(_chip_labels(_row(html, self.hope))[0], "1 Planned")
        self.assertIn("1 Planned", _chip_labels(_row(html, self.grace)))
        self.assertEqual(
            _chip_labels(_row(html, self.victory)), ["Not Planned", "Not Planned"]
        )
        # With no year chosen the page opens on the operational year and reads
        # the same way.
        default = self.client.get("/planning?tab=client&per_page=50").content.decode()
        self.assertEqual(_chip_labels(_row(default, self.hope))[0], "1 Planned")

    def test_the_cluster_school_list_matches_the_planning_list(self):
        html = self.client.get(
            f"/partials/clusters/{self.cluster.id}/schools"
        ).content.decode()
        self.assertEqual(_chip_labels(_cluster_row(html, self.hope))[0], "1 Planned")
        self.assertIn("1 Planned", _chip_labels(_cluster_row(html, self.grace)))
        planning = self.client.get(
            f"/planning?tab=client&fy={FY}&per_page=50"
        ).content.decode()
        for school in (self.hope, self.grace, self.victory):
            self.assertEqual(
                _chip_labels(_cluster_row(html, school)),
                _chip_labels(_row(planning, school)),
            )

    def test_the_schedule_drawer_warns_about_a_next_year_plan(self):
        response = self.client.get(
            f"/planning/schedule-modal?school_id={self.hope.school_id}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "This school already has 1 planned visit.", response.content.decode()
        )
