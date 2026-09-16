"""Team Oversight school coverage and derived visit status (2026-09-15 brief).

Team Oversight answers three questions about a supervisor's schools in one
period: what is planned at them, which have a cluster training or meeting, and
which have neither and why. The status of a visit is derived from the
canonical activity every time it is read — there is no editable flag.
"""

from __future__ import annotations

import datetime

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.clusters.models import Cluster
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region, SubCounty
from apps.planning import coverage_service
from apps.planning.coverage_todos import missing_training_todos
from apps.schools.models import School
from apps.schools.school_status import (
    NO_VISIT_PLANNED,
    SCHEDULED_FOR_VISIT,
    cluster_training_coverage,
    visit_statuses,
)

FY = get_operational_fy()


def _fy_day(month, day):
    """A date inside the operational fiscal year."""
    year = int(FY) - 1 if month >= 10 else int(FY)
    return datetime.date(year, month, day)


class CoverageFixture(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Coverage Region")
        self.district = District.objects.create(
            name="Coverage District", region=self.region
        )
        self.sub_county = SubCounty.objects.create(
            name="Coverage SC", district=self.district
        )
        self.pl_user = User.objects.create_user(
            email="cov-pl@edify.org",
            name="Coverage PL",
            roles=["Program Lead"],
            active_role="Program Lead",
            password="x",
        )
        self.pl = StaffProfile.objects.create(user=self.pl_user, country="Uganda")
        self.cceo_user = User.objects.create_user(
            email="cov-cceo@edify.org",
            name="Coverage CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
        )
        self.cceo = StaffProfile.objects.create(user=self.cceo_user, country="Uganda")
        StaffSupervisorAssignment.objects.create(
            supervisee=self.cceo, supervisor=self.pl
        )
        self.ia_user = User.objects.create_user(
            email="cov-ia@edify.org",
            name="Coverage IA",
            roles=["ImpactAssessment"],
            active_role="ImpactAssessment",
            password="x",
        )
        StaffProfile.objects.create(user=self.ia_user, country="Uganda")

        self.cluster = Cluster.objects.create(
            name="Coverage Cluster",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            status="active",
            responsible_staff_id=self.cceo.id,
        )
        self.covered = self._school("COV-1", "Covered Primary", cluster=self.cluster)
        self.uncovered = self._school(
            "COV-2", "Uncovered Primary", cluster=self.cluster
        )
        self.unclustered = self._school("COV-3", "Unclustered Primary")
        self.closed = self._school("COV-4", "Closed Primary", cluster=self.cluster)
        School.objects.filter(id=self.closed.id).update(
            operational_status="permanently_closed"
        )

    def _school(self, code, name, cluster=None):
        # A school in the cluster's sub-county is clustered by School.save's
        # geography rule, so a deliberately unclustered one carries none.
        school = School.objects.create(
            school_id=code,
            name=name,
            region=self.region,
            district=self.district,
            sub_county=self.sub_county if cluster is not None else None,
            school_type="client",
            account_owner_id=self.cceo.id,
        )
        StaffSchoolAssignment.objects.create(staff=self.cceo, school_id=school.id)
        if cluster is not None:
            School.objects.filter(id=school.id).update(
                cluster_id=cluster.id, cluster_status="clustered"
            )
            school.refresh_from_db()
        return school

    def _session(self, day, *, schools, status="scheduled", kind="cluster_training"):
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
            activity_name_snapshot="School Leadership",
        )
        for school in schools:
            ClusterActivityAttendance.objects.create(
                activity=session, school=school, invited=True
            )
        return session

    def _visit(self, school, day, status="scheduled"):
        return Activity.objects.create(
            activity_type="school_visit",
            school=school,
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


class VisitStatusTest(CoverageFixture):
    def test_every_state_is_derived_from_the_activity(self):
        day = _fy_day(11, 10)
        cases = {
            "planned": "visit_planned",
            "scheduled": SCHEDULED_FOR_VISIT,
            "partner_scheduled": SCHEDULED_FOR_VISIT,
            "completion_started": "visit_in_progress",
            "submitted_to_pl": "visit_submitted",
            "ia_verified": "visit_verified",
            "completed": "visit_completed",
            "cancelled": "visit_canceled",
        }
        for status, expected in cases.items():
            with self.subTest(status=status):
                Activity.objects.filter(school=self.covered).delete()
                self._visit(self.covered, day, status=status)
                state = visit_statuses([self.covered.id], fy=FY)[self.covered.id]
                self.assertEqual(state.key, expected)
                self.assertEqual(state.next_date, day)

    def test_a_school_with_nothing_planned_says_so(self):
        state = visit_statuses([self.uncovered.id], fy=FY)[self.uncovered.id]
        self.assertEqual(state.key, NO_VISIT_PLANNED)
        self.assertEqual(state.label, "No Visit Planned")
        self.assertIsNone(state.next_date)

    def test_the_next_scheduled_visit_wins_and_rescheduling_moves_it(self):
        first = self._visit(self.covered, _fy_day(11, 10))
        self._visit(self.covered, _fy_day(12, 12))
        state = visit_statuses([self.covered.id], fy=FY)[self.covered.id]
        self.assertTrue(state.is_scheduled)
        self.assertEqual(state.next_date, _fy_day(11, 10))
        Activity.objects.filter(id=first.id).update(planned_date=_fy_day(12, 20))
        state = visit_statuses([self.covered.id], fy=FY)[self.covered.id]
        self.assertEqual(state.next_date, _fy_day(12, 12))
        # Cancelling both leaves the school with no live plan.
        Activity.objects.filter(school=self.covered).update(status="cancelled")
        self.assertEqual(
            visit_statuses([self.covered.id], fy=FY)[self.covered.id].key,
            "visit_canceled",
        )

    def test_a_visit_awaiting_the_owners_approval_is_not_a_plan(self):
        self._visit(self.covered, _fy_day(11, 10), status="awaiting_owner_approval")
        self.assertEqual(
            visit_statuses([self.covered.id], fy=FY)[self.covered.id].key,
            NO_VISIT_PLANNED,
        )

    def test_the_directory_row_shows_the_derived_status(self):
        self._visit(self.covered, _fy_day(11, 10))
        from apps.frontend.view_models import SchoolDirectoryViewModel

        row = SchoolDirectoryViewModel.from_school(
            self.covered, self.cceo_user, {self.cluster.id: self.cluster.name}, False
        )
        self.assertEqual(row["visit_plan_status_label"], "Scheduled for Visit")
        self.assertTrue(row["is_scheduled_for_visit"])
        self.assertEqual(row["next_visit_date"], _fy_day(11, 10))


class TrainingCoverageTest(CoverageFixture):
    def test_only_an_explicit_attachment_counts(self):
        self._session(_fy_day(11, 5), schools=[self.covered])
        coverage = cluster_training_coverage(
            [self.covered, self.uncovered, self.unclustered], fy=FY
        )
        self.assertTrue(coverage[self.covered.id].planned)
        self.assertEqual(coverage[self.covered.id].label, "Training Planned")
        # In the same cluster, but not attached by the planning record.
        self.assertFalse(coverage[self.uncovered.id].planned)
        self.assertEqual(
            coverage[self.uncovered.id].reason, "No cluster training planned"
        )
        self.assertEqual(
            coverage[self.unclustered.id].reason, "School not attached to a cluster"
        )

    def test_a_cancelled_or_returned_session_is_not_a_plan(self):
        session = self._session(
            _fy_day(11, 5), schools=[self.covered], status="cancelled"
        )
        coverage = cluster_training_coverage([self.covered], fy=FY)
        self.assertFalse(coverage[self.covered.id].planned)
        self.assertEqual(coverage[self.covered.id].reason, "Existing plan canceled")
        Activity.objects.filter(id=session.id).update(status="returned_by_ia")
        coverage = cluster_training_coverage([self.covered], fy=FY)
        self.assertEqual(coverage[self.covered.id].reason, "Existing plan returned")

    def test_a_cluster_meeting_counts_and_is_named(self):
        self._session(_fy_day(11, 5), schools=[self.covered], kind="cluster_meeting")
        coverage = cluster_training_coverage([self.covered], fy=FY)
        self.assertTrue(coverage[self.covered.id].planned)
        self.assertEqual(coverage[self.covered.id].label, "Cluster Meeting Planned")


class CoverageTablesTest(CoverageFixture):
    def test_the_pl_sees_their_teams_schools_split_by_coverage(self):
        self._session(_fy_day(11, 5), schools=[self.covered])
        result = coverage_service.training_coverage(self.pl_user, fy=FY, period="fy")
        planned = {row["school_id"] for row in result["planned_rows"]}
        missing = {row["school_id"] for row in result["missing_rows"]}
        self.assertEqual(planned, {self.covered.id})
        self.assertIn(self.uncovered.id, missing)
        self.assertIn(self.unclustered.id, missing)
        # A closed school takes no work and is not "missing training".
        self.assertNotIn(self.closed.id, missing | planned)
        self.assertEqual(result["missing_count"], 2)
        # Each row names the CCEO who owns the school; supervision is not
        # ownership.
        self.assertEqual(
            {row["owner_name"] for row in result["missing_rows"]}, {"Coverage CCEO"}
        )

    def test_impact_assessment_reads_the_same_country_scope(self):
        self._session(_fy_day(11, 5), schools=[self.covered])
        result = coverage_service.training_coverage(self.ia_user, fy=FY, period="fy")
        self.assertIn(
            self.uncovered.id, {row["school_id"] for row in result["missing_rows"]}
        )

    def test_planned_schools_group_by_the_selected_period(self):
        from apps.planning import oversight_service as oversight

        self._visit(self.covered, _fy_day(11, 10))
        self._visit(self.uncovered, _fy_day(12, 14))
        items = oversight.build_items(self.pl_user, fy=FY)
        for period, expected_groups in (("fy", 1), ("quarter", 2)):
            with self.subTest(period=period):
                groups, totals = coverage_service.planned_schools(items, period=period)
                self.assertEqual(totals["schools"], 2)
                self.assertEqual(totals["activities"], 2)
                self.assertEqual(sum(g.count for g in groups), 2)
                self.assertGreaterEqual(len(groups), 1)
        # Week and month group the same rows more finely; the totals reconcile.
        for period in ("week", "month"):
            groups, totals = coverage_service.planned_schools(items, period=period)
            self.assertEqual(sum(g.count for g in groups), totals["activities"])

    def test_the_page_renders_the_three_tables(self):
        self._session(_fy_day(11, 5), schools=[self.covered])
        self._visit(self.covered, _fy_day(11, 10))
        self.client.force_login(self.pl_user)
        page = self.client.get("/team-planning-oversight/?view=coverage")
        self.assertContains(page, "Planned Schools")
        self.assertContains(page, "Schools with Planned Cluster Training or Meeting")
        self.assertContains(page, "Schools with No Training Planned")
        self.assertContains(page, "Uncovered Primary")
        self.assertContains(page, "Scheduled for Visit")
        # And the lens is offered as a tab to the person who acts on it.
        self.assertContains(page, "Schools &amp; Coverage")

    def test_the_lens_belongs_to_the_people_who_act_on_it(self):
        """The Accountant reaches Team Oversight for the money in the plan.

        They are not named anywhere in the coverage brief and have no part in
        planning a cluster training, so they are offered no tab — and a
        `?view=coverage` typed into the address bar answers with the planning
        lens rather than a refusal. This also keeps their first table row above
        the desktop fold, which a tab strip of one had pushed below it.
        """
        accountant = User.objects.create_user(
            email="coverage-accountant@edify.org",
            name="Coverage Accountant",
            roles=["Accountant"],
            active_role="Accountant",
            password="x",
        )
        StaffProfile.objects.create(user=accountant, country="Uganda")
        self.client.force_login(accountant)
        page = self.client.get("/team-planning-oversight/?view=coverage")
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "Schools &amp; Coverage")
        self.assertNotContains(page, "Schools with No Training Planned")


class MissingTrainingTodoTest(CoverageFixture):
    def test_the_action_reaches_the_pl_and_ia_and_closes_when_resolved(self):
        today = timezone.localdate()
        for user, role in (
            (self.pl_user, "Program Lead"),
            (self.ia_user, "ImpactAssessment"),
        ):
            with self.subTest(role=role):
                rows = missing_training_todos(user, role, today)
                self.assertEqual(len(rows), 1)
                self.assertIn("No Cluster Training", rows[0]["title"])
                self.assertEqual(
                    rows[0]["action_url"], "/team-planning-oversight/?view=coverage"
                )
        # A CCEO's own queue does not carry the supervisor's review row.
        self.assertEqual(missing_training_todos(self.cceo_user, "CCEO", today), [])

        # Plan a session for every school that lacked one: the row closes.
        self._session(
            _fy_day(11, 5),
            schools=[self.covered, self.uncovered, self.unclustered],
        )
        self.assertEqual(
            missing_training_todos(self.pl_user, "Program Lead", today), []
        )
        self.assertEqual(
            missing_training_todos(self.ia_user, "ImpactAssessment", today), []
        )
