"""Core School Intelligence: one read of every Core school's performance.

Owner, 2026-10-17, the Core School Intelligence brief; the figures are
defined in docs/core-school-intelligence-metrics.md. These hold the brief's
acceptance tests that the engine answers: a change only between two
comparable confirmed assessments, never a fabricated one; assigned partner
work is not delivered support; attendance on a real denominator; teacher and
leader figures as headcounts; and every total reconciling to its schools.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from django.test import TestCase

from apps.accounts.models import StaffSchoolAssignment
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.clusters.models import Cluster
from apps.clusters.test_cluster_oversight_views import _create_user
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.core_schools import intelligence
from apps.core_schools.models import CorePlan
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.schools.models import School, SchoolEnrollmentHistory
from apps.ssa.change_rules import DECLINED, IMPROVED, NOT_COMPARABLE
from apps.ssa.models import SsaRecord, SsaScore

AREAS = ("leadership", "financial_health", "teaching_environment")


class _CoreCase(TestCase):
    def setUp(self):
        self.fy = get_operational_fy()
        self.prev_fy = str(int(self.fy) - 1)
        self.region = Region.objects.create(name="Core intel region")
        self.north = District.objects.create(name="North", region=self.region)
        self.south = District.objects.create(name="South", region=self.region)
        self.james = _create_user("james@core-intel.test", EdifyRole.CCEO)
        self.mary = _create_user("mary@core-intel.test", EdifyRole.CCEO)
        self.cluster = Cluster.objects.create(
            name="Core intel cluster", region=self.region, district=self.north
        )

        self.rising = self._school("CI-1", self.james, self.north)
        self.single = self._school("CI-2", self.james, self.north)
        self.falling = self._school("CI-3", self.mary, self.south)

        self._ssa(self.rising, self.prev_fy, dict.fromkeys(AREAS, 5.0))
        self._ssa(
            self.rising,
            self.fy,
            {"leadership": 7.0, "financial_health": 8.0, "teaching_environment": 6.0},
        )
        self._ssa(self.single, self.fy, dict.fromkeys(AREAS, 4.0))
        self._ssa(self.falling, self.prev_fy, dict.fromkeys(AREAS, 7.0))
        self._ssa(self.falling, self.fy, dict.fromkeys(AREAS, 5.0))

        self._plan(self.rising, visits=4, trainings=4)
        self._plan(self.single, visits=1, trainings=0)

    def _school(self, code, owner, district) -> School:
        school = School.objects.create(
            school_id=code,
            name=f"Core school {code}",
            school_type="core",
            region=self.region,
            district=district,
            cluster_id=str(self.cluster.id),
            account_owner_id=owner.staff_profile.id,
        )
        # A CCEO's portfolio is their assignments, as on the live platform.
        StaffSchoolAssignment.objects.get_or_create(
            staff=owner.staff_profile, school_id=school.id
        )
        return school

    def _ssa(self, school, fy, scores):
        record = SsaRecord.objects.create(
            school=school,
            fy=fy,
            quarter="Q1",
            average_score=round(sum(scores.values()) / len(scores), 2),
            verification_status="confirmed",
            date_of_ssa=datetime(int(fy) - 1, 11, 1, tzinfo=timezone.utc),
            uploaded_by="test",
        )
        for area, score in scores.items():
            SsaScore.objects.create(ssa_record=record, intervention=area, score=score)

    def _plan(self, school, *, visits, trainings):
        return CorePlan.objects.create(
            id=f"cplan-{school.school_id}-{self.fy}",
            school_id=school.school_id,
            fy=self.fy,
            visits_completed=visits,
            trainings_completed=trainings,
        )

    def _read(self, schools=None):
        return intelligence.performance(
            schools or [self.rising, self.single, self.falling], fy=self.fy
        )


class SsaTest(_CoreCase):
    def test_two_comparable_assessments_give_the_change_and_its_verdict(self):
        row = self._read()[self.rising.id]

        self.assertEqual((row.ssa_before, row.ssa_now), (5.0, 7.0))
        self.assertEqual(row.ssa_change, 2.0)
        self.assertEqual(row.trajectory, IMPROVED)
        self.assertEqual(row.trajectory_label, "Improved")
        self.assertEqual(row.weakest_label, "Teacher's Environment")
        self.assertEqual(row.weakest_score, 6.0)

    def test_one_assessment_has_no_fabricated_change(self):
        row = self._read()[self.single.id]

        self.assertEqual(row.ssa_now, 4.0)
        self.assertIsNone(row.ssa_before)
        self.assertIsNone(row.ssa_change)
        self.assertEqual(row.trajectory, NOT_COMPARABLE)
        self.assertEqual(row.trajectory_label, "Not Compared")

    def test_a_decline_and_a_critical_area_are_flagged(self):
        rows = self._read()

        self.assertEqual(rows[self.falling.id].trajectory, DECLINED)
        self.assertIn("SSA declined", rows[self.falling.id].attention)
        # 4.0 is in the platform's Critical band (below 5).
        self.assertIn("Critical SSA area", rows[self.single.id].attention)

    def test_no_current_year_ssa_is_said_not_zero(self):
        newcomer = self._school("CI-4", self.james, self.north)

        row = self._read([newcomer])[newcomer.id]

        self.assertIsNone(row.ssa_now)
        self.assertFalse(row.has_current_ssa)
        self.assertIn("No current-year SSA", row.attention)

    def test_an_unconfirmed_record_is_not_read(self):
        SsaRecord.objects.filter(school=self.single).update(
            verification_status="pending"
        )

        self.assertIsNone(self._read()[self.single.id].ssa_now)


class PackageAndSupportTest(_CoreCase):
    def test_the_package_reads_the_plan_and_its_targets(self):
        rows = self._read()

        self.assertTrue(rows[self.rising.id].package_complete)
        self.assertEqual(rows[self.rising.id].package_pct, 100)
        self.assertEqual(
            (rows[self.single.id].visits_done, rows[self.single.id].visits_target),
            (1, 4),
        )
        self.assertFalse(rows[self.single.id].package_complete)
        self.assertIsNone(rows[self.falling.id].package_complete)
        self.assertEqual(rows[self.falling.id].package_label, "No package")

    def test_an_assigned_hand_over_is_a_commitment_not_support(self):
        partner = Partner.objects.create(name="Core intel partner")
        PartnerAssignment.objects.create(
            school=self.single,
            partner=partner,
            expected_activity_type="partner_activity",
        )

        row = self._read()[self.single.id]

        self.assertEqual(row.handovers_assigned, 1)
        self.assertEqual(row.handovers_completed, 0)
        self.assertIn("Partner hand-over not scheduled", row.attention)


class ParticipationTest(_CoreCase):
    def setUp(self):
        super().setUp()
        held = date(int(self.fy) - 1, 11, 20)
        for teachers, single_invited in ((5, True), (3, False)):
            session = Activity.objects.create(
                activity_type="cluster_meeting",
                cluster=self.cluster,
                fy=self.fy,
                planned_date=held,
                status="ia_verified",
            )
            ClusterActivityAttendance.objects.create(
                activity=session,
                school=self.rising,
                invited=True,
                attended=True,
                teachers=teachers,
                leaders=1,
            )
            if single_invited:
                ClusterActivityAttendance.objects.create(
                    activity=session, school=self.single, invited=True, attended=False
                )
        # A planned session has no register to read.
        planned = Activity.objects.create(
            activity_type="cluster_meeting",
            cluster=self.cluster,
            fy=self.fy,
            planned_date=held,
            status="scheduled",
        )
        ClusterActivityAttendance.objects.create(
            activity=planned, school=self.falling, invited=True, attended=False
        )
        Activity.objects.create(
            activity_type="in_school_training",
            school=self.rising,
            fy=self.fy,
            planned_date=held,
            status="ia_verified",
            teachers_attended=4,
            leaders_attended=1,
        )

    def test_attendance_is_on_delivered_sessions_the_school_was_invited_to(self):
        rows = self._read()

        self.assertEqual(
            (rows[self.rising.id].invited, rows[self.rising.id].attended), (2, 2)
        )
        self.assertEqual(rows[self.rising.id].attendance_rate, 100)
        self.assertEqual(rows[self.single.id].attendance_rate, 0)
        # Invited only to a session not yet held: no rate, not 0%.
        self.assertIsNone(rows[self.falling.id].attendance_rate)

    def test_teachers_and_leaders_are_headcounts(self):
        rows = self._read()

        self.assertEqual(rows[self.rising.id].teacher_attendances, 5 + 3 + 4)
        self.assertEqual(rows[self.rising.id].leader_attendances, 1 + 1 + 1)
        self.assertIsNone(rows[self.falling.id].teacher_attendances)


class OutcomesAndChampionTest(_CoreCase):
    def test_enrolment_change_needs_both_years(self):
        recorded = datetime(int(self.fy) - 1, 11, 1, tzinfo=timezone.utc)
        for fy, value in ((self.prev_fy, 200), (self.fy, 220)):
            SchoolEnrollmentHistory.objects.create(
                school=self.rising, fy=fy, enrollment=value, recorded_at=recorded
            )
        SchoolEnrollmentHistory.objects.create(
            school=self.single, fy=self.fy, enrollment=90, recorded_at=recorded
        )

        rows = self._read()

        self.assertEqual(rows[self.rising.id].enrol_change, 20)
        self.assertEqual(rows[self.rising.id].enrol_growth_pct, 10.0)
        self.assertIsNone(rows[self.single.id].enrol_change)

    def test_champion_readiness_never_comes_from_a_score_alone(self):
        rows = self._read()

        # Improving with the rule still open.
        self.assertEqual(rows[self.rising.id].champion, "Progressing")
        # No Core plan to judge.
        self.assertEqual(rows[self.falling.id].champion, "Insufficient Evidence")
        self.assertEqual(School.objects.get(id=self.rising.id).school_type, "core")


class SummaryAndGroupsTest(_CoreCase):
    def test_the_summary_reconciles_to_its_schools_with_denominators(self):
        summary = intelligence.summarise(self._read().values())

        self.assertEqual(summary["schools"], 3)
        self.assertEqual(summary["with_current_ssa"], 3)
        self.assertEqual(summary["compared"], 2)
        self.assertEqual((summary["improved"], summary["declined"]), (1, 1))
        self.assertEqual(summary["avg_change"], 0.0)
        self.assertEqual(summary["avg_latest"], round((7.0 + 4.0 + 5.0) / 3, 1))
        self.assertEqual((summary["with_plan"], summary["package_complete"]), (2, 1))

    def test_groups_split_by_cceo_and_by_the_schools_own_district(self):
        rows = list(self._read().values())

        by_cceo = {
            g["label"]: g["summary"]["schools"]
            for g in intelligence.groups(rows, "cceo")
        }
        by_district = {
            g["label"]: g["summary"]["schools"]
            for g in intelligence.groups(rows, "district")
        }

        self.assertEqual(sorted(by_cceo.values()), [1, 2])
        self.assertEqual(by_district, {"North": 2, "South": 1})
