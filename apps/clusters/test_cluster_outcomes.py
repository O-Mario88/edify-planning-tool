"""Cluster outcomes: enrolment, learning results, loans, stories; the Cluster
Oversight columns; and the absent-schools To-Do.

Owner brief, 2026-10-08 (Cluster Management), second round: "attendance and
SSA-change columns on the Cluster Oversight table, then Students, Loans and
Stories tabs, then a To-Do for the CCEO when a school reaches three misses."

What is held:

* growth is like for like — a school with a figure in only one year is in no
  total, so a school that joined is never read as growth;
* a loan is shown to a reader only as far as the loan register shows it, and
  the Loans tab is not offered to a role the register is closed to;
* a draft story is its author's own, and only an approved story is counted as
  approved;
* a figure on the Cluster Oversight table is the figure its link opens;
* the To-Do is one row per cluster, for the officer who holds it, and goes
  when the schools attend again.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from apps.accounts.models import StaffSupervisorAssignment
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.business_transformation.models import (
    LoanPurpose,
    MfiLoan,
    MfiOrganization,
    TransformationCase,
)
from apps.clusters import followups, outcomes
from apps.clusters.oversight_service import cluster_oversight_table_data
from apps.clusters.test_cluster_oversight_views import _create_user
from apps.clusters.test_cluster_profile_tabs import _ClusterCase
from apps.core.rbac import EdifyRole
from apps.impact.models import LearningAssessmentResult
from apps.schools.models import School, SchoolEnrollmentHistory
from apps.ssa.models import SsaRecord, SsaScore
from apps.targets.models import MostSignificantChangeStory


class EnrolmentTest(_ClusterCase):
    def setUp(self):
        super().setUp()
        self.grew = self._school(0, enrollment=420)
        self.shrank = self._school(1, enrollment=180)
        self.new = self._school(2, enrollment=300)
        self.unknown = self._school(3)
        for school, before, after in (
            (self.grew, 300, 420),
            (self.shrank, 200, 180),
            (self.new, None, 300),
        ):
            for fy, figure in ((self.last_fy, before), (self.fy, after)):
                if figure is not None:
                    SchoolEnrollmentHistory.objects.create(
                        school=school,
                        fy=fy,
                        enrollment=figure,
                        recorded_at=datetime(int(fy) - 1, 11, 1, tzinfo=timezone.utc),
                    )

    def test_growth_counts_only_schools_with_a_figure_in_both_years(self):
        summary = outcomes.cluster_enrolment(self.cluster, fy=self.fy)

        # 300 + 200 against 420 + 180; the school first counted this year
        # is in neither total.
        self.assertEqual(summary.compared, 2)
        self.assertEqual((summary.before, summary.after), (500, 600))
        self.assertEqual(summary.change, 100)
        self.assertEqual(summary.growth_pct, 20.0)
        rows = {r["code"]: r for r in summary.rows}
        self.assertEqual(rows["TAB-000"]["growth_pct"], 40.0)
        self.assertEqual(rows["TAB-001"]["change"], -20)
        self.assertIsNone(rows["TAB-002"]["change"])
        self.assertIsNone(rows["TAB-003"]["latest"])
        # The latest figures are every school's, whatever its history.
        self.assertEqual((summary.latest_total, summary.with_latest), (900, 3))

    def test_no_pair_is_no_growth_figure(self):
        SchoolEnrollmentHistory.objects.filter(fy=self.last_fy).delete()

        summary = outcomes.cluster_enrolment(self.cluster, fy=self.fy)

        self.assertEqual(summary.compared, 0)
        self.assertIsNone(summary.change)
        self.assertIsNone(summary.growth_pct)

    def test_the_tab_lists_each_school_and_says_how_growth_is_counted(self):
        body = self._page(tab="students").content.decode()

        self.assertIn('data-cluster-profile-panel="students"', body)
        self.assertIn("500 to 600 learners (+20.0%)", body)
        self.assertIn("2 of 4 schools compared", body)
        self.assertEqual(body.count("data-enrolment-school="), 4)
        self.assertIn(">School ID</th>", body)
        self.assertIn(f'href="/schools/{self.grew.id}"', body)
        self.assertIn("data-enrolment-method", body)


class LearningTest(_ClusterCase):
    def _result(self, school, fy, mean, *, learners=40, status="confirmed"):
        return LearningAssessmentResult.objects.create(
            school=school,
            fy=fy,
            recorded_by_user_id=self.cd.id,
            verification_status=status,
            assessment_type="national_exam",
            assessed_on=date(int(fy) - 1, 11, 20),
            grade_level="P7",
            subject="Mathematics",
            learners_tested=learners,
            mean_score=Decimal(str(mean)),
            max_score=Decimal("100"),
        )

    def test_a_schools_score_is_weighted_by_learners_and_compared_in_pairs(self):
        up, down, once = self._school(0), self._school(1), self._school(2)
        self._result(up, self.last_fy, 50)
        # Two classes this year: 60 learners at 70 and 20 at 50 is 65, not 60.
        self._result(up, self.fy, 70, learners=60)
        self._result(up, self.fy, 50, learners=20)
        self._result(down, self.last_fy, 60)
        self._result(down, self.fy, 55)
        self._result(once, self.fy, 90)
        # Not yet confirmed: moves no figure.
        self._result(once, self.last_fy, 10, status="pending")

        summary = outcomes.cluster_learning(self.cluster, fy=self.fy)

        rows = {r["code"]: r for r in summary.rows}
        self.assertEqual(
            (rows["TAB-000"]["before"], rows["TAB-000"]["after"]), (50.0, 65.0)
        )
        self.assertEqual(rows["TAB-000"]["change"], 15.0)
        self.assertEqual(rows["TAB-000"]["learners"], 80)
        self.assertEqual(rows["TAB-001"]["change"], -5.0)
        self.assertIsNone(rows["TAB-002"]["change"])
        self.assertEqual(summary.compared, 2)
        self.assertEqual(
            (summary.improved, summary.declined, summary.unchanged), (1, 1, 0)
        )
        self.assertEqual(
            (summary.before, summary.after, summary.change), (55.0, 60.0, 5.0)
        )

        body = self._page(tab="learning").content.decode()
        self.assertIn('data-cluster-profile-panel="learning"', body)
        self.assertIn("55.0% to 60.0% mean score", body)
        self.assertIn("1 improved, 0 unchanged, 1 declined", body)
        self.assertIn("not a measure of what any one activity caused", body)


class LoansTest(_ClusterCase):
    def setUp(self):
        super().setUp()
        self.borrower, self.other = self._school(0), self._school(1)
        self.mfi = MfiOrganization.objects.create(code="CLU_MFI", name="Cluster MFI")
        self.purpose = LoanPurpose.objects.create(
            code="CLU-CLASSROOMS", label="Classrooms"
        )

    def _loan(self, school, reference, status, disbursed="0"):
        funded = status in ("disbursed", "active", "repaid", "defaulted")
        case, _ = TransformationCase.objects.get_or_create(
            school=school, defaults={"opened_fy": self.fy}
        )
        return MfiLoan.objects.create(
            mfi=self.mfi,
            school=school,
            case=case,
            purpose=self.purpose,
            external_loan_reference=reference,
            registered_by=self.cd.id,
            approved_amount=Decimal("5000000"),
            disbursed_amount=Decimal(disbursed) if funded else None,
            status=status,
            # A disbursed loan carries its date and its confirmation.
            disbursement_date=date(int(self.fy) - 1, 10, 3) if funded else None,
            disbursement_confirmed_at=(
                datetime(int(self.fy) - 1, 10, 3, tzinfo=timezone.utc)
                if funded
                else None
            ),
        )

    def test_the_register_decides_what_a_reader_sees(self):
        self._loan(self.borrower, "L-1", "active", "5000000")
        self._loan(self.borrower, "L-2", "processing")
        self._loan(self.other, "L-3", "canceled", "100")

        summary = outcomes.cluster_loans(self.cluster, self.cd)

        # A cancelled loan is not a loan the school holds.
        self.assertEqual(summary.loan_count, 2)
        self.assertEqual(summary.school_count, 1)
        self.assertEqual(summary.funded_school_count, 1)
        self.assertEqual(summary.disbursed, Decimal("5000000"))
        self.assertEqual(dict(summary.status_counts), {"Active": 1, "Processing": 1})

        # A Programme Lead has no loan portfolio: the register shows them
        # nothing, so the cluster shows them nothing.
        lead = _create_user("lead@loans.test", EdifyRole.COUNTRY_PROGRAM_LEAD)
        self.assertEqual(outcomes.cluster_loans(self.cluster, lead).loan_count, 0)

    def test_the_tab_is_offered_only_to_a_role_the_register_is_open_to(self):
        self._loan(self.borrower, "L-1", "active", "5000000")

        body = self._page(tab="loans").content.decode()
        self.assertIn('data-cluster-profile-panel="loans"', body)
        self.assertIn("1 loan at 1 school", body)
        self.assertIn("UGX 5,000,000 disbursed", body)
        self.assertIn("Cluster MFI", body)
        self.assertIn(f'href="/clusters/{self.cluster.id}?tab=loans"', body)

        lead = _create_user("lead@loans.test", EdifyRole.COUNTRY_PROGRAM_LEAD)
        cceo = _create_user("cceo@loans.test", EdifyRole.CCEO)
        StaffSupervisorAssignment.objects.create(
            supervisor=lead.staff_profile, supervisee=cceo.staff_profile
        )
        type(self.cluster).objects.filter(id=self.cluster.id).update(
            responsible_staff_id=cceo.staff_profile.id
        )
        self.client.force_login(lead)
        response = self.client.get(f"/clusters/{self.cluster.id}", {"tab": "loans"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["profile_tab"], "overview")
        self.assertNotIn("?tab=loans", response.content.decode())


class StoriesTest(_ClusterCase):
    def _story(self, title, status, *, school=None, cluster=False, day=None):
        return MostSignificantChangeStory.objects.create(
            user_id=self.cd.id,
            school=school,
            cluster_id=self.cluster.id if cluster else None,
            title=title,
            narrative="What changed.",
            story_date=day or date(int(self.fy) - 1, 10, 5),
            status=status,
            intervention="leadership" if status == "approved" else "",
            evidence_uri="story.pdf" if status == "approved" else None,
        )

    def test_a_clusters_stories_are_its_schools_and_its_own(self):
        member = self._school(0)
        elsewhere = School.objects.create(
            name="Elsewhere",
            school_id="ELS-1",
            region=self.region,
            district=self.district,
        )
        self._story("Books kept", "approved", school=member)
        self._story("Leaders meet monthly", "submitted", cluster=True)
        self._story("Half written", "draft", school=member)
        self._story("Another cluster", "approved", school=elsewhere)

        summary = outcomes.cluster_stories(self.cluster)

        self.assertEqual(
            sorted(r["title"] for r in summary.rows),
            ["Books kept", "Leaders meet monthly"],
        )
        self.assertEqual((summary.approved, summary.waiting), (1, 1))
        approved = next(r for r in summary.rows if r["title"] == "Books kept")
        self.assertEqual(approved["area"], "Leadership")
        self.assertTrue(approved["has_evidence"])
        self.assertEqual(approved["author"], self.cd.name)

        body = self._page(tab="stories").content.decode()
        self.assertIn('data-cluster-profile-panel="stories"', body)
        self.assertIn("1 approved · 1 with a reviewer · 2 in all", body)
        self.assertNotIn("Half written", body)
        self.assertIn("The cluster", body)
        self.assertIn(">School ID</th>", body)


class _Sessions(_ClusterCase):
    """Three delivered sessions: one school kept every invitation, one none."""

    def setUp(self):
        super().setUp()
        self.keeps, self.absent = self._school(0), self._school(1)
        for day in (4, 11, 18):
            session = Activity.objects.create(
                activity_type="cluster_meeting",
                cluster=self.cluster,
                fy=self.fy,
                planned_date=date(int(self.fy) - 1, 10, day),
                status="ia_verified",
            )
            for school in (self.keeps, self.absent):
                ClusterActivityAttendance.objects.create(
                    activity=session,
                    school=school,
                    invited=True,
                    attended=school is self.keeps,
                )


class OversightColumnsTest(_Sessions):
    def _ssa(self, school, fy, score):
        record = SsaRecord.objects.create(
            school=school,
            fy=fy,
            quarter="Q1",
            average_score=score,
            verification_status="confirmed",
            date_of_ssa=datetime(int(fy) - 1, 11, 1, tzinfo=timezone.utc),
            uploaded_by="test",
        )
        SsaScore.objects.create(
            ssa_record=record, intervention="leadership", score=score
        )

    def _row(self, data):
        rows = [
            row
            for lead in data["leads"]
            for tab in lead["cceo_tabs"]
            for row in tab["clusters"]
        ]
        return next(r for r in rows if r["cluster_id"] == self.cluster.id)

    def test_a_row_carries_the_figures_the_profile_tabs_show(self):
        self._ssa(self.keeps, self.last_fy, 5.0)
        self._ssa(self.keeps, self.fy, 6.5)

        data = cluster_oversight_table_data(self.cd, fy=self.fy)
        row = self._row(data)

        # Three of six invitations were kept; one school missed all three.
        self.assertEqual(row["attendance_rate"], 50)
        self.assertEqual(row["absent_schools"], 1)
        self.assertEqual(row["ssa_change"], 1.5)
        self.assertEqual(row["ssa_compared"], 1)
        self.assertEqual(row["ssa_fy"], self.fy)
        self.assertEqual(data["ssa_movement_fy"], self.fy)

    def test_ssa_change_compares_the_pages_year_with_the_one_before(self):
        """Owner, 2026-10-09: "fy2026 vs fy2027 not 2025". On 1 October the
        new year has no SSA: the column is this year against last and has
        nothing to say yet, never last year against the year before."""
        before = str(int(self.last_fy) - 1)
        self._ssa(self.keeps, before, 6.0)
        self._ssa(self.keeps, self.last_fy, 5.0)

        data = cluster_oversight_table_data(self.cd, fy=self.fy)
        row = self._row(data)

        self.assertIsNone(row["ssa_change"])
        self.assertEqual(row["ssa_fy"], self.fy)
        self.assertEqual(data["ssa_movement_previous_fy"], self.last_fy)

    def test_the_page_draws_the_columns_and_each_figure_opens_its_tab(self):
        self._ssa(self.keeps, self.last_fy, 5.0)
        self._ssa(self.keeps, self.fy, 6.5)

        self.client.force_login(self.cd)
        body = self.client.get("/cluster-oversight/", {"fy": self.fy}).content.decode()

        for heading in ("Attendance", "Absent 3+ Sessions", "SSA Change"):
            self.assertIn(f">{heading}</th>", body)
        base = f"/clusters/{self.cluster.id}?tab="
        self.assertIn(f"{base}attendance&amp;fy={self.fy}", body)
        self.assertIn(f"{base}attendance&amp;fy={self.fy}&amp;show=missing", body)
        self.assertIn(f"{base}ssa&amp;fy={self.fy}", body)
        self.assertIn(">50%</a>", body)


class AbsentSchoolsTodoTest(_Sessions):
    def setUp(self):
        super().setUp()
        self.cceo = _create_user("holder@todo.test", EdifyRole.CCEO)
        type(self.cluster).objects.filter(id=self.cluster.id).update(
            responsible_staff_id=self.cceo.staff_profile.id
        )
        self.today = date(int(self.fy) - 1, 10, 20)

    def _todos(self, user):
        return followups.attendance_todos(user, user.active_role, self.today)

    def test_the_officer_who_holds_the_cluster_gets_one_row_for_it(self):
        todos = self._todos(self.cceo)

        self.assertEqual(len(todos), 1)
        todo = todos[0]
        self.assertEqual(todo["id"], f"cluster-absent-{self.cluster.id}")
        self.assertEqual(todo["title"], "Follow Up Schools Missing Cluster Sessions")
        self.assertIn(
            "1 school of Tabs cluster has missed 3 or more", todo["description"]
        )
        self.assertIn("Tabs school 1", todo["description"])
        self.assertEqual(
            todo["action_url"],
            f"/clusters/{self.cluster.id}?tab=attendance&show=missing",
        )
        self.assertEqual(todo["priority"], "high")
        # Nobody else is asked to follow up a cluster they do not hold.
        self.assertEqual(self._todos(self.cd), [])

    def test_it_goes_when_the_school_attends_again(self):
        session = Activity.objects.create(
            activity_type="cluster_meeting",
            cluster=self.cluster,
            fy=self.fy,
            planned_date=date(int(self.fy) - 1, 10, 19),
            status="ia_verified",
        )
        ClusterActivityAttendance.objects.create(
            activity=session, school=self.absent, invited=True, attended=True
        )

        self.assertEqual(self._todos(self.cceo), [])

    def test_two_misses_are_not_yet_a_follow_up(self):
        Activity.objects.filter(planned_date__day=18).delete()

        self.assertEqual(self._todos(self.cceo), [])

    def test_it_is_in_the_officers_queue_and_its_link_opens(self):
        from apps.command_center.todo_service import MODULE_TODO_BUILDERS, get_todos

        self.assertIn("apps.clusters.followups:attendance_todos", MODULE_TODO_BUILDERS)
        queue = get_todos(self.cceo)["todos"]
        mine = [t for t in queue if t["id"] == f"cluster-absent-{self.cluster.id}"]
        self.assertEqual(len(mine), 1)

        self.client.force_login(self.cceo)
        response = self.client.get(mine[0]["action_url"])
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            f'data-attendance-school="{self.absent.id}"', response.content.decode()
        )
