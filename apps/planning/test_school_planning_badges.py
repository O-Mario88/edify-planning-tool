"""Visit and Training planning badges (owner brief, 2026-09-22).

The Planning page school list and the Cluster School List — and only those —
show per school how many visits and trainings are planned, awaiting
verification and IA-verified. Both read one server-side calculation, the
counts are derived from the canonical activities every time, and the badge
never stops a school being planned again.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import (
    Activity,
    ActivityScheduleCostLine,
    ClusterActivityAttendance,
)
from apps.budget.models import ActivityCostSnapshot
from apps.clusters.models import Cluster
from apps.core.exceptions import BadRequest
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy
from apps.fund_requests.models import FundRequestItem
from apps.geography.models import District, Region, SubCounty
from apps.planning.school_planning_badges import (
    SchoolPlanningBadgeService,
    existing_plan_warning,
)
from apps.planning.test_standard_support_scheduling import (
    StandardSupportBase,
    _at,
    _schedulable_date,
)
from apps.schools.models import School
from apps.targets.models import TargetAchievementLedger

FY = get_operational_fy()


def _fy_day(month, day):
    year = int(FY) - 1 if month >= 10 else int(FY)
    return datetime.date(year, month, day)


def _chips(html: str) -> list[tuple[str, str]]:
    return re.findall(
        r'class="school-planning-badge" data-planning-tone="([a-z]+)"[^>]*>([^<]+)<',
        html,
    )


class BadgeFixture(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Badge Region")
        self.district = District.objects.create(
            name="Badge District", region=self.region
        )
        self.sub_county = SubCounty.objects.create(
            name="Badge SC", district=self.district
        )
        self.user = User.objects.create_user(
            email="badge-cceo@edify.org",
            name="Badge CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
        )
        self.cceo = StaffProfile.objects.create(user=self.user, country="Uganda")
        self.cluster = Cluster.objects.create(
            name="Badge Cluster",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            status="active",
            responsible_staff_id=self.cceo.id,
        )
        self.hope = self._school("BDG-1", "Hope Primary")
        self.grace = self._school("BDG-2", "Grace Academy")
        self.victory = self._school("BDG-3", "Victory School")

    def _school(self, code, name):
        school = School.objects.create(
            school_id=code,
            name=name,
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            school_type="client",
            account_owner_id=self.cceo.id,
        )
        StaffSchoolAssignment.objects.create(staff=self.cceo, school_id=school.id)
        School.objects.filter(id=school.id).update(
            cluster_id=self.cluster.id, cluster_status="clustered"
        )
        school.refresh_from_db()
        return school

    def _activity(
        self, school, kind="school_visit", status="scheduled", day=None, **kw
    ):
        day = day or _fy_day(11, 10)
        return Activity.objects.create(
            activity_type=kind,
            school=school,
            fy=kw.pop("fy", FY),
            quarter="Q1",
            planned_date=day,
            scheduled_date=timezone.make_aware(
                datetime.datetime.combine(day, datetime.time(9))
            ),
            status=status,
            responsible_staff_id=self.cceo.id,
            delivery_type="staff",
            **kw,
        )

    def _session(
        self, *, invited=(), attended=(), status="scheduled", kind="cluster_training"
    ):
        day = _fy_day(11, 20)
        session = Activity.objects.create(
            activity_type=kind,
            cluster=self.cluster,
            fy=FY,
            quarter="Q1",
            planned_date=day,
            scheduled_date=timezone.make_aware(
                datetime.datetime.combine(day, datetime.time(9))
            ),
            status=status,
            responsible_staff_id=self.cceo.id,
            delivery_type="staff",
        )
        for school in invited:
            ClusterActivityAttendance.objects.create(
                activity=session,
                school=school,
                invited=True,
                attended=school in attended,
            )
        return session

    def badges(self, *schools):
        return SchoolPlanningBadgeService.get_for_schools(
            [s.id for s in schools], financial_year=FY
        )


class CountsTest(BadgeFixture):
    def test_the_example_rows(self):
        # Hope Primary: 2 Planned · 1 Complete visits, 1 Planned training.
        self._activity(self.hope)
        self._activity(self.hope, status="planned", day=_fy_day(12, 1))
        self._activity(self.hope, status="ia_verified")
        self._activity(self.hope, kind="in_school_training")
        # Grace Academy: 1 Complete visit, no training.
        self._activity(self.grace, status="closed")
        # Victory School: no visit, 2 Complete · 1 Planned trainings.
        self._activity(self.victory, kind="in_school_training", status="ia_verified")
        self._activity(
            self.victory, kind="in_school_training", status="accountant_confirmed"
        )
        self._activity(self.victory, kind="in_school_training", status="planned")

        b = self.badges(self.hope, self.grace, self.victory)
        self.assertEqual(
            [c["label"] for c in b[self.hope.id].visit_chips],
            ["2 Planned", "1 Complete"],
        )
        self.assertEqual(
            [c["label"] for c in b[self.hope.id].training_chips], ["1 Planned"]
        )
        self.assertEqual(
            [c["label"] for c in b[self.grace.id].visit_chips], ["1 Complete"]
        )
        self.assertEqual(
            b[self.grace.id].training_chips, [{"label": "Not Planned", "tone": "none"}]
        )
        self.assertEqual(
            b[self.victory.id].visit_chips, [{"label": "Not Planned", "tone": "none"}]
        )
        self.assertEqual(
            [c["label"] for c in b[self.victory.id].training_chips],
            ["1 Planned", "2 Complete"],
        )
        self.assertEqual(b[self.hope.id].visits.next_date, _fy_day(11, 10))
        self.assertEqual(
            b[self.hope.id].as_dict()["visits"],
            {
                "planned_count": 2,
                "awaiting_verification_count": 0,
                "verified_count": 1,
                "needs_replanning_count": 0,
                "next_date": _fy_day(11, 10).isoformat(),
            },
        )

    def test_visits_and_trainings_are_planned_side_by_side(self):
        self._activity(self.hope)
        self._activity(self.hope, kind="in_school_training")
        b = self.badges(self.hope)[self.hope.id]
        self.assertEqual(b.visits.planned_count, 1)
        self.assertEqual(b.trainings.planned_count, 1)

    def test_a_submitted_activity_is_blue_not_green(self):
        for status in (
            "evidence_uploaded",
            "submitted_to_pl",
            "awaiting_ia_verification",
            "completed",  # legacy, never IA-verified
        ):
            with self.subTest(status=status):
                Activity.objects.all().delete()
                self._activity(self.hope, status=status)
                v = self.badges(self.hope)[self.hope.id].visits
                self.assertEqual(v.awaiting_verification_count, 1)
                self.assertEqual(v.verified_count, 0)
                self.assertEqual(
                    self.badges(self.hope)[self.hope.id].visit_chips,
                    [{"label": "1 Awaiting Verification", "tone": "awaiting"}],
                )

    def test_only_ia_verified_work_is_green(self):
        for status in ("ia_verified", "accountant_confirmed", "closed"):
            with self.subTest(status=status):
                Activity.objects.all().delete()
                self._activity(self.hope, status=status)
                self.assertEqual(
                    self.badges(self.hope)[self.hope.id].visit_chips,
                    [{"label": "1 Complete", "tone": "verified"}],
                )

    def test_cancelled_and_returned_work_stops_counting_as_a_plan(self):
        for status in ("cancelled", "rejected", "deferred", "awaiting_owner_approval"):
            self._activity(self.hope, status=status)
        self._activity(self.grace, status="returned_by_pl")
        self._activity(self.grace, status="returned_by_ia")
        b = self.badges(self.hope, self.grace)
        self.assertEqual(b[self.hope.id].visits.total, 0)
        self.assertEqual(b[self.hope.id].visit_chips[0]["label"], "Not Planned")
        self.assertEqual(b[self.grace.id].visits.planned_count, 0)
        self.assertEqual(
            b[self.grace.id].visit_chips,
            [{"label": "2 Needs Replanning", "tone": "replan"}],
        )

    def test_another_year_and_deleted_rows_do_not_count(self):
        self._activity(self.hope, fy=str(int(FY) - 1))
        gone = self._activity(self.hope)
        Activity.objects.filter(id=gone.id).update(deleted_at=timezone.now())
        self.assertEqual(self.badges(self.hope)[self.hope.id].visits.total, 0)

    def test_a_period_narrows_the_count(self):
        self._activity(self.hope, day=_fy_day(11, 10))
        self._activity(self.hope, day=_fy_day(3, 10))
        b = SchoolPlanningBadgeService.get_for_schools(
            [self.hope.id],
            financial_year=FY,
            period=(_fy_day(10, 1), _fy_day(12, 31)),
        )
        self.assertEqual(b[self.hope.id].visits.planned_count, 1)


class ClusterRuleTest(BadgeFixture):
    def test_cluster_membership_alone_is_not_training(self):
        # A live session in the cluster that names only Hope.
        self._session(invited=[self.hope])
        b = self.badges(self.hope, self.grace)
        self.assertEqual(b[self.hope.id].trainings.planned_count, 1)
        self.assertEqual(b[self.grace.id].trainings.total, 0)

    def test_a_school_absent_from_a_cluster_training_is_not_complete(self):
        self._session(
            invited=[self.hope, self.grace], attended=[self.hope], status="ia_verified"
        )
        b = self.badges(self.hope, self.grace)
        self.assertEqual(b[self.hope.id].trainings.verified_count, 1)
        self.assertEqual(b[self.grace.id].trainings.total, 0)
        self.assertEqual(b[self.grace.id].training_chips[0]["label"], "Not Planned")

    def test_attendance_recorded_on_the_session_counts_once(self):
        session = self._session(
            invited=[self.hope], attended=[self.hope], status="ia_verified"
        )
        Activity.objects.filter(id=session.id).update(
            attended_school_ids=[self.hope.id, self.victory.id]
        )
        b = self.badges(self.hope, self.victory)
        self.assertEqual(b[self.hope.id].trainings.verified_count, 1)
        self.assertEqual(b[self.victory.id].trainings.verified_count, 1)

    def test_a_cluster_meeting_is_named_and_is_not_training(self):
        self._session(invited=[self.hope], kind="cluster_meeting")
        self._session(
            invited=[self.grace],
            attended=[self.grace],
            kind="cluster_meeting",
            status="ia_verified",
        )
        b = self.badges(self.hope, self.grace)
        self.assertEqual(b[self.hope.id].trainings.total, 0)
        self.assertEqual(
            b[self.hope.id].cluster_meeting_chips,
            [{"label": "1 Cluster Meeting Planned", "tone": "planned"}],
        )
        self.assertEqual(
            b[self.grace.id].cluster_meeting_chips,
            [{"label": "1 Cluster Meeting Complete", "tone": "verified"}],
        )

    def test_a_meeting_counts_as_training_only_when_its_mapping_says_so(self):
        from apps.activity_catalogue.models import ActivityCatalogueItem

        item = (
            ActivityCatalogueItem.objects.filter(
                workflow_kind="cluster_meeting"
            ).first()
            or ActivityCatalogueItem.objects.first()
        )
        ActivityCatalogueItem.objects.filter(id=item.id).update(
            counts_toward_client_training=True, is_training_course=False
        )
        session = self._session(invited=[self.hope], kind="cluster_meeting")
        Activity.objects.filter(id=session.id).update(catalogue_item=item)
        b = self.badges(self.hope)[self.hope.id]
        self.assertEqual(b.trainings.planned_count, 1)
        self.assertEqual(b.cluster_meetings.total, 0)


class QueryCountTest(BadgeFixture):
    def test_query_count_does_not_grow_with_the_list(self):
        few = [self.hope, self.grace]
        many = few + [self._school(f"BDG-Q{i}", f"Q School {i}") for i in range(25)]
        for school in many:
            self._activity(school)
            self._activity(school, kind="in_school_training", status="ia_verified")
        self._session(invited=many, attended=many, status="ia_verified")

        def cost(schools):
            with CaptureQueriesContext(connection) as ctx:
                SchoolPlanningBadgeService.get_for_schools(
                    [s.id for s in schools], financial_year=FY
                )
            return len(ctx.captured_queries)

        self.assertEqual(cost(few), cost(many))
        self.assertLessEqual(cost(many), 3)


class PagesTest(BadgeFixture):
    def setUp(self):
        super().setUp()
        self._activity(self.hope)
        self._activity(self.hope, status="planned", day=_fy_day(12, 1))
        self._activity(self.hope, status="ia_verified")
        self._activity(self.hope, kind="in_school_training", status="submitted_to_pl")
        self._session(invited=[self.hope, self.grace], kind="cluster_meeting")
        self.client.force_login(self.user)

    def _planning_row(self, html, school):
        start = html.index(f'id="select-planning-school-{school.id}"')
        end = html.find("</tr>", start)
        return html[start:end]

    def _planning_html(self):
        # Hope has scheduled work, so it is on the Scheduled tab; the other
        # two are on the default tab. Every tab renders the same row.
        return "".join(
            self.client.get(f"/planning?tab={tab}&fy={FY}&per_page=50").content.decode()
            for tab in ("client", "scheduled")
        )

    def test_planning_and_cluster_list_show_the_same_badges(self):
        from apps.planning.planning_service import PlanningDashboardService

        planning_rows = {}
        for tab in ("client", "scheduled"):
            for row in PlanningDashboardService.get_dashboard_data(
                self.user, {"fy": FY, "tab": tab, "page": 1, "per_page": 50}
            )["schools"]:
                planning_rows[row["id"]] = row["planningBadges"].as_dict()

        detail = self.client.get(f"/clusters/{self.cluster.id}")
        self.assertEqual(detail.status_code, 200)
        partial = self.client.get(f"/partials/clusters/{self.cluster.id}/schools")
        self.assertEqual(partial.status_code, 200)
        for response in (detail, partial):
            cluster_rows = {
                row["id"]: row["planningBadges"].as_dict()
                for row in response.context["schools"]
            }
            for school in (self.hope, self.grace, self.victory):
                self.assertEqual(planning_rows[school.id], cluster_rows[school.id])

        # And the rendered chips agree, row for row.
        planning_html = self._planning_html()
        detail_html = detail.content.decode()
        partial_html = partial.content.decode()
        hope_planning = _chips(self._planning_row(planning_html, self.hope))
        self.assertEqual(
            hope_planning,
            [
                ("planned", "2 Planned"),
                ("verified", "1 Complete"),
                ("awaiting", "1 Awaiting Verification"),
                ("planned", "1 Cluster Meeting Planned"),
            ],
        )
        detail_row = detail_html[detail_html.index(f'href="/schools/{self.hope.id}"') :]
        detail_row = detail_row[: detail_row.index("</tr>")]
        self.assertEqual(_chips(detail_row), hope_planning)
        partial_row = partial_html[
            partial_html.index(f"cluster-school-details-{self.hope.id}") :
        ]
        partial_row = partial_row[: partial_row.index("</tr>")]
        self.assertEqual(_chips(partial_row), hope_planning)

    def test_schools_with_plans_stay_selectable_and_plannable(self):
        html = self._planning_html()
        row = self._planning_row(html, self.hope)
        self.assertIn(
            'type="checkbox"',
            html[html.index(f'id="select-planning-school-{self.hope.id}"') - 200 :],
        )
        self.assertIn(
            f'hx-get="/planning/schedule-modal?school_id={self.hope.school_id}', row
        )
        self.assertNotIn('data-visit-locked="true"', row)
        detail = self.client.get(f"/clusters/{self.cluster.id}").content.decode()
        self.assertIn(
            f'hx-get="/planning/schedule-modal?school_id={self.hope.school_id}"', detail
        )
        self.assertNotIn('data-visit-locked="true"', detail)

    def test_no_badges_anywhere_else(self):
        for url in (
            "/my-plan",
            "/schools",
            f"/schools/{self.hope.id}",
            "/team-planning-oversight/",
            "/",
        ):
            with self.subTest(url=url):
                response = self.client.get(url, follow=True)
                self.assertNotIn(b"data-planning-badges", response.content)
                self.assertNotIn(b"school-planning-badge", response.content)
        # The cluster API is not a list people plan from.
        api = self.client.get(f"/api/clusters/{self.cluster.id}/schools")
        if api.status_code == 200:
            self.assertNotIn(b"planningBadges", api.content)

    def test_only_the_two_lists_include_the_component(self):
        # The two planning lists, plus the core-schools lifecycle table
        # (7586e32), whose Visit/Training plan status columns are the same
        # server-side badges for programme schools.
        root = Path(settings.BASE_DIR) / "templates"
        including = sorted(
            str(path.relative_to(root))
            for path in root.rglob("*.html")
            if "components/school_planning_badges.html" in path.read_text()
            and path.name != "school_planning_badges.html"
        )
        self.assertEqual(
            including,
            [
                "pages/clusters/detail.html",
                "partials/clusters/cluster_schools_table.html",
                "partials/core_schools/programme_table.html",
                "partials/planning/school_row.html",
            ],
        )
        callers = sorted(
            str(path.relative_to(settings.BASE_DIR))
            for path in (Path(settings.BASE_DIR) / "apps").rglob("*.py")
            if "SchoolPlanningBadgeService" in path.read_text()
            and not path.name.startswith("test")
            and path.name != "school_planning_badges.py"
        )
        self.assertEqual(
            callers,
            [
                "apps/core_schools/lifecycle.py",
                "apps/frontend/views/cluster_views.py",
                "apps/planning/planning_service.py",
            ],
        )

    def test_reading_the_badges_writes_nothing(self):
        tables = (
            Activity,
            ActivityScheduleCostLine,
            ActivityCostSnapshot,
            TargetAchievementLedger,
            FundRequestItem,
            ClusterActivityAttendance,
        )
        before = {model: model.objects.count() for model in tables}
        self._planning_html()
        self.client.get(f"/clusters/{self.cluster.id}")
        self.client.get(f"/partials/clusters/{self.cluster.id}/schools")
        self.client.get(f"/planning/schedule-modal?school_id={self.hope.school_id}")
        self.assertEqual(before, {model: model.objects.count() for model in tables})

    def test_the_drawer_warns_without_blocking(self):
        response = self.client.get(
            f"/planning/schedule-modal?school_id={self.hope.school_id}"
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("data-existing-plan-warning", html)
        self.assertIn(
            "This school already has 2 planned visits, 1 completed visit and 1 "
            "training awaiting verification. You may continue if this is another "
            "required visit, follow-up, intervention, or project activity.",
            html,
        )
        for action in (
            "View Existing Plans",
            "Continue Planning",
            "Plan as Follow-Up",
            "Cancel",
        ):
            self.assertIn(action, html)
        # The form is all there and submits as it always has.
        self.assertIn('hx-post="/planning/schedule-action"', html)
        self.assertIn('name="purpose_of_visit"', html)

        quiet = self.client.get(
            f"/planning/schedule-modal?school_id={self.victory.school_id}"
        ).content.decode()
        self.assertNotIn("data-existing-plan-warning", quiet)

    def test_the_warning_lists_the_existing_plans(self):
        warning = existing_plan_warning(self.hope.id, financial_year=FY)
        self.assertEqual(len(warning["plans"]), 4)
        self.assertEqual(
            [p["status_label"] for p in warning["plans"]].count("Planned"), 2
        )


class FurtherPlanningIsNeverBlockedTest(StandardSupportBase):
    """Through the real scheduling service: the badge refuses nothing."""

    def _visit(self, day):
        return self.schedule(
            schoolId=self.school.school_id,
            catalogueItemId=self.item("STANDARD_SCHOOL_VISIT").id,
            focusIntervention=SsaIntervention.FINANCIAL_HEALTH,
            scheduledDate=_at(day).isoformat(),
        )

    def _counts(self):
        return SchoolPlanningBadgeService.get_for_schools(
            [self.school.id], financial_year=get_operational_fy()
        )[self.school.id]

    def _next_day(self, day):
        day += datetime.timedelta(days=1)
        while day.weekday() == 6:
            day += datetime.timedelta(days=1)
        return day

    def test_a_school_with_planned_visits_can_receive_another(self):
        day = _schedulable_date()
        self._visit(day)
        self.assertEqual(self._counts().visits.planned_count, 1)
        day = self._next_day(day)
        self._visit(day)
        self._visit(self._next_day(day))
        self.assertEqual(self._counts().visits.planned_count, 3)

    def test_a_school_with_completed_training_can_receive_another(self):
        Activity.objects.create(
            activity_type="in_school_training",
            school=self.school,
            fy=get_operational_fy(),
            quarter="Q1",
            planned_date=timezone.localdate() - datetime.timedelta(days=20),
            status="ia_verified",
            delivery_type="staff",
            responsible_staff_id=self.staff.id,
        )
        self.assertEqual(self._counts().trainings.verified_count, 1)
        self.schedule(
            schoolId=self.school.school_id,
            catalogueItemId=self.item("STANDARD_IN_SCHOOL_TRAINING").id,
            focusIntervention=SsaIntervention.FINANCIAL_HEALTH,
            teachersAttended=6,
        )
        counts = self._counts().trainings
        self.assertEqual((counts.planned_count, counts.verified_count), (1, 1))

    def test_an_exact_double_click_is_still_refused(self):
        day = _schedulable_date()
        self._visit(day)
        before = Activity.objects.count()
        with self.assertRaises(BadRequest):
            self._visit(day)
        self.assertEqual(Activity.objects.count(), before)
        self.assertEqual(self._counts().visits.planned_count, 1)
