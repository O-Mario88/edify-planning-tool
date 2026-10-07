"""A closed school goes to the Closed Schools list and out of every total.

Owner, 2026-10-07: "can you make sure that if a school is closed they go to
the closed school list and total number updated."

Closing a school already moved it to the Closed Schools page and out of the
directory's totals. It stayed in most other figures: dashboards, analytics,
SSA coverage, the team roster and Programme Rollout counted every school
that was not deleted, cluster rosters and project tables listed it, and three
things went on holding it: an invitation to a group training not yet held, a
project enrolment with no work behind it, and its open data-quality issues.
"""

from __future__ import annotations

from datetime import date, timedelta
from io import StringIO

from django.core.management import call_command

from apps.accounts.models import StaffSchoolAssignment
from apps.activities.cluster_attendance import release_school_invitations
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.clusters.models import Cluster
from apps.projects.models import (
    Project,
    ProjectSchoolAssignment,
    ProjectSchoolEnrollmentHistory,
    current_enrolments,
)
from apps.schools import closed_school_settlement as settlement
from apps.schools import lifecycle_service as svc
from apps.schools.data_quality import data_quality_summary, open_issues
from apps.schools.lifecycle_service import active_schools, closed_schools
from apps.schools.models import DataQualityIssue, School
from apps.schools.test_closure import ClosureFixture


class _Fixture(ClosureFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.cluster = Cluster.objects.create(
            name="Closure Cluster",
            region=cls.region,
            district=cls.district,
            cluster_type="mixed",
            status="active",
        )
        School.objects.filter(id__in=[cls.school.id, cls.other.id]).update(
            cluster_id=cls.cluster.id, cluster_status="clustered"
        )
        cls.school.refresh_from_db()
        cls.other.refresh_from_db()
        cls.project = Project.objects.create(
            name="Closure Project",
            code="SP-CLOSE",
            category="intervention_specific",
            status="active",
        )

    def close(self, school=None, **over):
        return svc.close_school(
            (school or self.school).id, self.payload(**over), self.cceo_user
        )

    def session(self, *, days=10, status="scheduled", schools=None):
        when = date.today() + timedelta(days=days)
        activity = Activity.objects.create(
            activity_type="cluster_training",
            cluster=self.cluster,
            fy=self.fy,
            quarter="Q1",
            planned_date=when,
            planned_month=when.month,
            status=status,
            responsible_staff_id=self.cceo.id,
            teachers_per_school=2,
        )
        for school in schools or (self.school, self.other):
            ClusterActivityAttendance.objects.create(
                activity=activity, school=school, invited=True, teachers=2
            )
        return activity

    def invited(self, activity):
        return set(
            ClusterActivityAttendance.objects.filter(
                activity=activity, invited=True
            ).values_list("school__name", flat=True)
        )

    def enrol(self, school=None):
        return ProjectSchoolAssignment.objects.create(
            project=self.project,
            school=school or self.school,
            assigned_by=self.cceo_user.id,
            assigned_staff=self.cceo,
        )

    def issue(self, school=None, kind="closure_test_gap"):
        """An open issue of the test's own (a school record raises its real
        ones as it is saved)."""
        school = school or self.school
        return DataQualityIssue.objects.create(
            school=school,
            issue_type=kind,
            severity="warning",
            condition_key=f"school:{school.id}|dq:{kind}",
        )


class TheListItGoesToTest(_Fixture):
    def test_a_closed_school_is_on_the_closed_list_and_off_the_operating_one(self):
        self.close()

        self.assertEqual([s.name for s in closed_schools()], ["Alpha Primary"])
        self.assertEqual([s.name for s in active_schools()], ["Beta Primary"])

    def test_the_closed_schools_page_lists_it(self):
        self.close()
        self.client.force_login(self.cceo_user)

        page = self.client.get("/schools/closed")

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Alpha Primary")
        self.assertNotContains(page, "Beta Primary")

    def test_the_directory_no_longer_lists_it(self):
        self.close()
        self.client.force_login(self.cceo_user)

        page = self.client.get("/schools")

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Beta Primary")
        self.assertNotContains(page, "Alpha Primary")


class TotalsFollowTest(_Fixture):
    """Figures that counted every school not deleted."""

    def test_the_programme_lead_s_analytics_portfolio(self):
        from apps.analytics.pl_analytics_service import resolve_pl_scope

        self.assertEqual(len(resolve_pl_scope(self.pl_user, {}).school_ids), 2)
        self.close()

        scope = resolve_pl_scope(self.pl_user, {})

        self.assertEqual(set(scope.school_ids), {self.other.id})
        self.assertEqual(
            set(
                School.objects.filter(id__in=scope.school_ref).values_list(
                    "name", flat=True
                )
            ),
            {"Beta Primary"},
        )

    def test_the_country_s_analytics_portfolio(self):
        from apps.analytics.cd_analytics_service import resolve_cd_scope

        self.assertEqual(len(resolve_cd_scope(self.fy).school_ids), 2)
        self.close()

        self.assertEqual(set(resolve_cd_scope(self.fy).school_ids), {self.other.id})

    def test_the_team_roster(self):
        from apps.hr.team_roster import build_team_roster

        def portfolio():
            roster = build_team_roster(self.pl_user, self.fy)
            return sum(row["ssa"]["portfolio"] for row in roster["rows"])

        self.assertEqual(portfolio(), 2)
        self.close()
        self.assertEqual(portfolio(), 1)

    def test_programme_rollout(self):
        from apps.analytics.programme_rollout_service import resolve_rollout_scope

        self.assertEqual(len(resolve_rollout_scope(self.pl_user).schools), 2)
        self.close()

        scope = resolve_rollout_scope(self.pl_user)

        self.assertEqual({s["name"] for s in scope.schools.values()}, {"Beta Primary"})

    def test_the_person_s_own_portfolio_count(self):
        from apps.planning import planning_monitor

        self.close()

        person = planning_monitor.own_monitor(self.cceo_user, self.fy)

        self.assertEqual([s.name for s in person.schools], ["Beta Primary"])

    def test_the_cluster_s_roster_and_count(self):
        from apps.clusters.services import cluster_detail

        self.assertEqual(
            cluster_detail(self.cluster.id, self.cceo_user)["schoolCount"], 2
        )
        self.close()

        self.assertEqual(
            cluster_detail(self.cluster.id, self.cceo_user)["schoolCount"], 1
        )

    def test_an_assignment_row_to_a_closed_school_does_not_count(self):
        """The link row stays (the holder still opens the closed school); the
        figures read operating schools."""
        self.close()

        self.assertTrue(
            StaffSchoolAssignment.objects.filter(
                staff=self.cceo, school_id=self.school.id
            ).exists()
        )


class GroupTrainingInvitationsTest(_Fixture):
    def test_closing_takes_the_school_off_a_session_not_yet_held(self):
        session = self.session()

        self.close()

        self.assertEqual(self.invited(session), {"Beta Primary"})

    def test_the_session_is_re_counted_for_the_schools_left(self):
        session = self.session()
        from apps.activities.cluster_attendance import sync_expected_participants

        sync_expected_participants(session)
        session.refresh_from_db()
        self.assertEqual(session.expected_participants, 4)

        self.close()

        session.refresh_from_db()
        self.assertEqual(session.expected_participants, 2)

    def test_a_session_already_held_keeps_its_record(self):
        held = self.session(days=-20, status="completed")
        ClusterActivityAttendance.objects.filter(activity=held).update(attended=True)

        self.close()

        self.assertEqual(self.invited(held), {"Alpha Primary", "Beta Primary"})

    def test_attendance_recorded_is_never_removed(self):
        session = self.session()
        ClusterActivityAttendance.objects.filter(
            activity=session, school=self.school
        ).update(attended=True)

        self.close()

        self.assertEqual(self.invited(session), {"Alpha Primary", "Beta Primary"})

    def test_a_session_before_the_closure_date_is_left(self):
        session = self.session(days=5)

        left = release_school_invitations(
            self.school, on_or_after=date.today() + timedelta(days=6)
        )

        self.assertEqual(left, 0)
        self.assertEqual(self.invited(session), {"Alpha Primary", "Beta Primary"})

    def test_the_school_no_longer_counts_under_the_officer_s_training(self):
        from apps.activities.cluster_attendance import invited_head_counts

        session = self.session()
        self.close()

        pairs = [(session.id, session.cluster_id)]
        self.assertEqual(invited_head_counts(pairs).get(session.id), 2)


class ProjectEnrolmentTest(_Fixture):
    def test_closing_withdraws_an_enrolment_with_no_project_work(self):
        self.enrol()

        self.close()

        self.assertFalse(
            ProjectSchoolAssignment.objects.filter(school=self.school).exists()
        )
        history = ProjectSchoolEnrollmentHistory.objects.get(school_id=self.school.id)
        self.assertEqual(history.removal_reason, "The school closed.")

    def test_the_adder_gets_the_place_back(self):
        from apps.planning import planning_monitor

        self.enrol()
        self.enrol(self.other)
        self.assertEqual(
            planning_monitor.own_monitor(self.cceo_user, self.fy).project_added, 2
        )

        self.close()

        self.assertEqual(
            planning_monitor.own_monitor(self.cceo_user, self.fy).project_added, 1
        )

    def test_an_enrolment_with_delivered_project_work_is_kept_as_its_record(self):
        self.enrol()
        when = date.today() - timedelta(days=30)
        Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            project_id=self.project.id,
            fy=self.fy,
            quarter="Q1",
            planned_date=when,
            planned_month=when.month,
            status="completed",
            responsible_staff_id=self.cceo.id,
        )

        self.close()

        self.assertTrue(
            ProjectSchoolAssignment.objects.filter(school=self.school).exists()
        )

    def test_the_project_s_tables_list_operating_schools_only(self):
        kept = self.enrol()
        self.enrol(self.other)
        School.objects.filter(id=self.school.id).update(
            operational_status="permanently_closed"
        )

        names = set(
            current_enrolments()
            .filter(project=self.project)
            .values_list("school__name", flat=True)
        )

        self.assertEqual(names, {"Beta Primary"})
        self.assertTrue(ProjectSchoolAssignment.objects.filter(id=kept.id).exists())

    def test_the_project_page_does_not_list_a_closed_school(self):
        from apps.projects.portfolio import portfolio_rows

        self.enrol()
        self.enrol(self.other)
        School.objects.filter(id=self.school.id).update(
            operational_status="permanently_closed"
        )

        rows = portfolio_rows(self.project)

        self.assertEqual([row["school_name"] for row in rows], ["Beta Primary"])


class DataQualityQueueTest(_Fixture):
    def test_closing_settles_the_school_s_open_issues(self):
        mine = self.issue()
        theirs = self.issue(self.other)

        self.close()

        mine.refresh_from_db()
        theirs.refresh_from_db()
        self.assertEqual(mine.status, "resolved")
        self.assertIsNotNone(mine.resolved_at)
        self.assertEqual(theirs.status, "open")

    def test_the_queue_and_its_counts_are_operating_schools(self):
        self.issue()
        self.issue(self.other)
        School.objects.filter(id=self.school.id).update(
            operational_status="temporarily_closed"
        )

        self.assertEqual(
            set(open_issues().values_list("school__name", flat=True)),
            {"Beta Primary"},
        )
        self.assertEqual(
            data_quality_summary()["openIssues"],
            DataQualityIssue.objects.filter(school=self.other, status="open").count(),
        )
        self.assertTrue(
            DataQualityIssue.objects.filter(school=self.school, status="open").exists(),
            "still open in the table: only the queue leaves it out",
        )


class SchoolsClosedBeforeTest(_Fixture):
    """A school closed before closing released anything (schools 0024)."""

    def closed_the_old_way(self):
        session = self.session()
        self.enrol()
        self.issue()
        School.objects.filter(id=self.school.id).update(
            operational_status="permanently_closed",
            closure_effective_date=date.today(),
        )
        return session

    def test_it_is_found_with_what_it_still_holds(self):
        self.closed_the_old_way()

        found = settlement.find_live()

        self.assertEqual(
            [(r.name, r.invitations, r.enrolments) for r in found],
            [("Alpha Primary", 1, 1)],
        )
        self.assertGreaterEqual(found[0].issues, 1)

    def test_an_operating_school_is_never_found(self):
        self.session()
        self.enrol(self.other)
        self.issue(self.other)

        self.assertEqual(settlement.find_live(), [])

    def test_settling_releases_all_three_and_then_finds_nothing(self):
        session = self.closed_the_old_way()

        result = settlement.settle(self.school.id)

        self.assertEqual((result["invitations"], result["projects"]), (1, 1))
        self.assertGreaterEqual(result["issues"], 1)
        self.assertEqual(self.invited(session), {"Beta Primary"})
        self.assertEqual(settlement.find_live(), [])
        self.assertEqual(
            settlement.settle(self.school.id),
            {"invitations": 0, "projects": 0, "issues": 0},
        )

    def test_the_command_reports_and_changes_nothing_without_apply(self):
        session = self.closed_the_old_way()
        out = StringIO()

        call_command("settle_closed_schools", stdout=out)

        self.assertIn("Alpha Primary", out.getvalue())
        self.assertIn("--apply", out.getvalue())
        self.assertEqual(self.invited(session), {"Alpha Primary", "Beta Primary"})

    def test_the_command_applies(self):
        session = self.closed_the_old_way()
        out = StringIO()

        call_command("settle_closed_schools", "--apply", stdout=out)

        self.assertEqual(self.invited(session), {"Beta Primary"})
        self.assertIn("No closed school holds anything.", out.getvalue())

    def test_the_migration_does_the_same_from_historical_models(self):
        import importlib

        from django.apps import apps as live_apps

        session = self.closed_the_old_way()
        migration = importlib.import_module(
            "apps.schools.migrations.0024_settle_closed_schools"
        )

        migration.settle_closed_schools(live_apps, None)

        self.assertEqual(self.invited(session), {"Beta Primary"})
        self.assertEqual(settlement.find_live(), [])
