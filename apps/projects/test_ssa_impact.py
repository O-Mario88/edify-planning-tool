"""What the platform may and may not claim about a project's effect.

The arithmetic here is subtraction. Everything worth testing is the refusal to
say more than the evidence supports: a project nobody has re-assessed has not
failed, a half-point gain is not nothing, and four schools out of six is not a
sixty-seven percent improvement rate.
"""

from __future__ import annotations

from datetime import date

from django.test import TestCase

from apps.geography.models import District, Region
from apps.projects import ssa_impact as si
from apps.projects.models import Project, ProjectSchoolAssignment
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

INTERVENTION = "christlike_behaviour"


class ImpactFixture(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Central")
        self.district = District.objects.create(
            name="Dist", region=self.region, district_type="primary"
        )
        self.project = Project.objects.create(
            name="CC-SEL", code="CCSEL", intervention=INTERVENTION
        )
        self.school = self._school("A")

    def _school(self, sid):
        return School.objects.create(
            school_id=f"S-{sid}",
            name=f"School {sid}",
            region=self.region,
            district=self.district,
            enrollment=100,
        )

    def _ssa(self, school, on, score, *, status="confirmed", intervention=INTERVENTION):
        record = SsaRecord.objects.create(
            school=school,
            fy="2026",
            quarter="Q1",
            average_score=score,
            verification_status=status,
            date_of_ssa=on,
            uploaded_by="t",
        )
        SsaScore.objects.create(
            ssa_record=record, intervention=intervention, score=score
        )
        return record


class BaselineTests(ImpactFixture):
    def test_the_baseline_is_the_last_reading_before_entry_not_the_latest(self):
        self._ssa(self.school, date(2025, 1, 10), 3.0)
        self._ssa(self.school, date(2025, 6, 10), 4.0)
        # Taken during delivery — must not become what delivery is judged on.
        self._ssa(self.school, date(2026, 6, 10), 9.0)

        baseline = si.baseline_for(
            self.school.id, INTERVENTION, before=date(2025, 12, 31)
        )

        self.assertEqual(baseline.score, 4.0)

    def test_an_unconfirmed_assessment_is_not_a_baseline(self):
        self._ssa(self.school, date(2025, 6, 10), 4.0, status="draft")

        self.assertIsNone(si.baseline_for(self.school.id, INTERVENTION))

    def test_a_score_off_the_scale_is_not_evidence(self):
        self._ssa(self.school, date(2025, 6, 10), 44.0)

        self.assertIsNone(si.baseline_for(self.school.id, INTERVENTION))

    def test_another_intervention_is_not_this_baseline(self):
        self._ssa(self.school, date(2025, 6, 10), 4.0, intervention="leadership")

        self.assertIsNone(si.baseline_for(self.school.id, INTERVENTION))


class FollowUpWindowTests(ImpactFixture):
    def test_an_assessment_too_soon_after_the_work_cannot_judge_it(self):
        delivered = date(2026, 1, 10)
        self._ssa(self.school, date(2026, 1, 20), 8.0)

        found = si.follow_up_for(
            self.school.id, INTERVENTION, after=delivered, min_days=90
        )

        self.assertIsNone(found)

    def test_an_assessment_long_after_the_work_is_no_longer_about_it(self):
        delivered = date(2026, 1, 10)
        self._ssa(self.school, date(2027, 6, 1), 9.0)

        found = si.follow_up_for(
            self.school.id, INTERVENTION, after=delivered, min_days=90, max_days=365
        )

        self.assertIsNone(found)

    def test_the_earliest_reading_inside_the_window_is_the_one_closest_to_the_work(
        self,
    ):
        delivered = date(2026, 1, 10)
        self._ssa(self.school, date(2026, 5, 1), 6.0)
        self._ssa(self.school, date(2026, 9, 1), 9.0)

        found = si.follow_up_for(
            self.school.id, INTERVENTION, after=delivered, min_days=90, max_days=365
        )

        self.assertEqual(found.score, 6.0)


class ClassificationTests(ImpactFixture):
    def _reading(self, score, on=date(2026, 1, 1)):
        from apps.core.enums import ssa_score_band

        return si.ScoreReading("r", on, score, ssa_score_band(score)[0])

    def test_a_project_nobody_reassessed_has_not_failed(self):
        verdict, change = si.classify(self._reading(4.0), None, window_open=False)

        self.assertEqual(verdict, si.Impact.NOT_YET_MEASURABLE)
        # Not zero. A zero would sit alongside schools that were measured and
        # did not move.
        self.assertIsNone(change)

    def test_no_baseline_means_no_claim(self):
        verdict, change = si.classify(None, self._reading(8.0))

        self.assertEqual(verdict, si.Impact.INSUFFICIENT_EVIDENCE)
        self.assertIsNone(change)

    def test_without_an_approved_threshold_any_movement_counts(self):
        verdict, change = si.classify(self._reading(4.0), self._reading(4.5))

        self.assertEqual(verdict, si.Impact.IMPROVED)
        self.assertEqual(change, 0.5)

    def test_an_approved_threshold_is_honoured_in_both_directions(self):
        under, _ = si.classify(
            self._reading(4.0), self._reading(4.5), min_meaningful_change=1.0
        )
        over, _ = si.classify(
            self._reading(4.0), self._reading(5.5), min_meaningful_change=1.0
        )
        down, _ = si.classify(
            self._reading(5.5), self._reading(4.0), min_meaningful_change=1.0
        )

        self.assertEqual(under, si.Impact.NO_CHANGE)
        self.assertEqual(over, si.Impact.IMPROVED)
        self.assertEqual(down, si.Impact.DECLINED)

    def test_holding_a_strong_score_is_success_where_that_was_the_goal(self):
        verdict, change = si.classify(
            self._reading(8.5),
            self._reading(8.5),
            expected_direction="maintain_strong",
        )

        self.assertEqual(verdict, si.Impact.MAINTAINED_STRONG)
        self.assertEqual(change, 0.0)

    def test_slipping_out_of_strong_is_a_decline_even_while_the_score_rose(self):
        verdict, _ = si.classify(
            self._reading(7.0),
            self._reading(7.9),
            expected_direction="maintain_strong",
        )

        self.assertEqual(verdict, si.Impact.DECLINED)


class CohortTests(ImpactFixture):
    def _enrol(self, school, *, baseline=None, follow_up=None, classification=""):
        return ProjectSchoolAssignment.objects.create(
            project=self.project,
            school=school,
            baseline_score=baseline,
            follow_up_score=follow_up,
            impact_classification=classification,
        )

    def test_a_school_without_a_baseline_is_named_not_counted_against(self):
        self._enrol(self.school)

        result = si.project_impact(self.project)

        self.assertEqual(result["pipeline"]["baseline_missing"], 1)
        self.assertEqual(result["cohort_size"], 0)
        self.assertIsNone(result["improvement_rate"])

    def test_awaiting_follow_up_is_not_a_failure(self):
        self._enrol(self.school, baseline=4.0, classification="not_yet_measurable")

        result = si.project_impact(self.project)

        self.assertEqual(result["pipeline"]["awaiting_follow_up"], 1)
        self.assertEqual(result["declined"], 0)
        self.assertEqual(result["cohort_size"], 0)

    def test_a_cohort_too_small_for_a_rate_withholds_the_rate(self):
        for i in range(3):
            self._enrol(
                self._school(f"small{i}"),
                baseline=4.0,
                follow_up=6.0,
                classification="improved",
            )

        result = si.project_impact(self.project)

        self.assertEqual(result["cohort_size"], 3)
        self.assertFalse(result["has_enough_evidence"])
        self.assertIsNone(result["improvement_rate"])
        self.assertIn("not", result["limitation"])

    def test_a_cohort_large_enough_reports_the_rate_with_its_denominator(self):
        for i in range(4):
            self._enrol(
                self._school(f"up{i}"),
                baseline=4.0,
                follow_up=6.0,
                classification="improved",
            )
        self._enrol(
            self._school("down"), baseline=6.0, follow_up=4.0, classification="declined"
        )

        result = si.project_impact(self.project)

        self.assertEqual(result["cohort_size"], 5)
        self.assertTrue(result["has_enough_evidence"])
        self.assertEqual(result["improvement_rate"], 0.8)
        self.assertEqual(result["decline_rate"], 0.2)
        # Four schools up two points, one down two: (8 - 2) / 5.
        self.assertEqual(result["average_change"], 1.2)
        self.assertIsNone(result["limitation"])


class BaselineSnapshotTests(ImpactFixture):
    """The baseline is taken once, at the door, and does not move afterwards."""

    def setUp(self):
        super().setUp()
        from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
        from apps.core.rbac import EdifyRole

        self.project.status = "active"
        self.project.target_interventions = [INTERVENTION]
        self.project.save()

        self.user = User.objects.create_user(
            email="cceo-base@t.org",
            name="CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
        )
        self.staff = StaffProfile.objects.create(
            user=self.user, title=EdifyRole.CCEO.value
        )
        StaffSchoolAssignment.objects.create(staff=self.staff, school_id=self.school.id)
        from apps.projects.models import ProjectStaffAssignment

        ProjectStaffAssignment.objects.create(
            project=self.project,
            staff=self.staff,
            fy="2026",
            responsibility="execute",
            is_active=True,
        )

    def _assign(self):
        from apps.projects.services import assign_school

        return assign_school(
            self.project.id,
            {"schoolId": self.school.school_id, "reason": "pilot cohort"},
            self.user,
        )

    def test_joining_snapshots_the_score_the_school_arrived_with(self):
        self._ssa(self.school, date(2025, 6, 1), 3.5)
        self._assign()

        row = ProjectSchoolAssignment.objects.get(
            project=self.project, school=self.school
        )
        self.assertEqual(row.baseline_score, 3.5)
        self.assertEqual(row.baseline_band, "Critical")
        self.assertIsNotNone(row.baseline_captured_at)

    def test_a_later_assessment_does_not_move_the_baseline(self):
        self._ssa(self.school, date(2025, 6, 1), 3.5)
        self._assign()
        # Taken during delivery. Letting it become the baseline would erase
        # the improvement the project is trying to demonstrate.
        self._ssa(self.school, date(2026, 6, 1), 8.0)

        row = ProjectSchoolAssignment.objects.get(
            project=self.project, school=self.school
        )
        self.assertEqual(row.baseline_score, 3.5)

    def test_a_school_with_no_confirmed_assessment_gets_no_baseline_not_a_zero(self):
        self._assign()

        row = ProjectSchoolAssignment.objects.get(
            project=self.project, school=self.school
        )
        self.assertIsNone(row.baseline_score)
        self.assertEqual(row.impact_classification, si.Impact.INSUFFICIENT_EVIDENCE)

    def test_enrolling_is_not_delivery_and_not_impact(self):
        self._ssa(self.school, date(2025, 6, 1), 3.5)
        self._assign()

        result = si.project_impact(self.project)

        self.assertEqual(result["pipeline"]["added"], 1)
        self.assertEqual(result["cohort_size"], 0)
        self.assertIsNone(result["improvement_rate"])


class FollowUpRefreshTests(BaselineSnapshotTests):
    """The window opens on verified delivery, not on a plan."""

    def _verified_activity(self, on=date(2026, 1, 10)):
        from apps.activities.models import Activity

        return Activity.objects.create(
            school=self.school,
            project_id=self.project.id,
            activity_type="training",
            delivery_type="staff",
            status="ia_verified",
            fy="2026",
            quarter="Q3",
            planned_date=on,
            actual_delivery_date=on,
        )

    def test_nothing_verified_means_nothing_to_measure_from(self):
        self._ssa(self.school, date(2025, 6, 1), 3.0)
        self._assign()
        row = ProjectSchoolAssignment.objects.get(project=self.project)

        si.refresh_follow_up(row)

        row.refresh_from_db()
        self.assertIsNone(row.follow_up_score)
        self.assertEqual(row.impact_classification, si.Impact.NOT_YET_MEASURABLE)

    def test_an_assessment_inside_the_window_produces_a_verdict(self):
        self._ssa(self.school, date(2025, 6, 1), 3.0)
        self._assign()
        self._verified_activity(date(2026, 1, 10))
        self._ssa(self.school, date(2026, 6, 1), 6.0)

        row = ProjectSchoolAssignment.objects.get(project=self.project)
        si.refresh_follow_up(row, mapping=_Mapping(min_days=90, max_days=540))

        row.refresh_from_db()
        self.assertEqual(row.follow_up_score, 6.0)
        self.assertEqual(row.impact_classification, si.Impact.IMPROVED)

    def test_an_assessment_before_the_window_opens_is_not_a_verdict(self):
        self._ssa(self.school, date(2025, 6, 1), 3.0)
        self._assign()
        self._verified_activity(date(2026, 1, 10))
        # Two weeks after a training. Nothing has had time to change.
        self._ssa(self.school, date(2026, 1, 24), 9.0)

        row = ProjectSchoolAssignment.objects.get(project=self.project)
        si.refresh_follow_up(row, mapping=_Mapping(min_days=90, max_days=540))

        row.refresh_from_db()
        self.assertIsNone(row.follow_up_score)
        self.assertNotEqual(row.impact_classification, si.Impact.IMPROVED)

    def test_running_it_twice_says_the_same_thing(self):
        self._ssa(self.school, date(2025, 6, 1), 3.0)
        self._assign()
        self._verified_activity(date(2026, 1, 10))
        self._ssa(self.school, date(2026, 6, 1), 6.0)

        row = ProjectSchoolAssignment.objects.get(project=self.project)
        mapping = _Mapping(min_days=90, max_days=540)
        si.refresh_follow_up(row, mapping=mapping)
        first = row.impact_classification
        si.refresh_follow_up(row, mapping=mapping)

        row.refresh_from_db()
        self.assertEqual(row.impact_classification, first)


class OverlapTests(ImpactFixture):
    def test_a_school_in_two_projects_for_one_intervention_is_disclosed(self):
        other = Project.objects.create(
            name="Character Camps", code="CCAMP", intervention=INTERVENTION
        )
        ProjectSchoolAssignment.objects.create(project=other, school=self.school)
        ProjectSchoolAssignment.objects.create(project=self.project, school=self.school)

        overlap = si.schools_in_other_projects(
            [self.school.id], intervention=INTERVENTION, exclude_project=self.project
        )

        # Neither project may report this school's movement as uniquely its
        # own; naming the overlap is what stops a country total counting it
        # twice.
        self.assertEqual(overlap, {self.school.id: ["Character Camps"]})

    def test_a_project_aimed_elsewhere_is_not_an_overlap(self):
        other = Project.objects.create(
            name="Books", code="BOOKS", intervention="learning_environment"
        )
        ProjectSchoolAssignment.objects.create(project=other, school=self.school)

        overlap = si.schools_in_other_projects(
            [self.school.id], intervention=INTERVENTION, exclude_project=self.project
        )

        self.assertEqual(overlap, {})


class _Mapping:
    """The measurement rules, without needing a catalogue item to hang them on."""

    def __init__(
        self, *, min_days=None, max_days=None, direction="improve", threshold=None
    ):
        self.follow_up_min_days = min_days
        self.follow_up_max_days = max_days
        self.expected_direction = direction
        self.min_meaningful_change = threshold
