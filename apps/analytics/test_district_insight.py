import datetime

from django.test import TestCase

from apps.analytics.district_insight import (
    MIN_SCORES_FOR_INTERVENTION_CALL,
    district_insight,
)
from apps.clusters.models import Cluster
from apps.core_schools.models import CoreSchoolProfile
from apps.geography.models import District, Region
from apps.geography.subregions import sync
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore


class DistrictInsightTest(TestCase):
    """The hover card states facts about a district, so each must be exact."""

    def setUp(self):
        self.region = Region.objects.create(name="Northern Region")
        self.gulu = District.objects.create(name="Gulu", region=self.region)
        self.kitgum = District.objects.create(name="Kitgum", region=self.region)
        sync()
        self.cluster = Cluster.objects.create(
            name="Gulu Cluster", region=self.region, district=self.gulu
        )
        self.schools = [
            School.objects.create(
                school_id=f"G-{i}", name=f"Gulu School {i}",
                region=self.region, district=self.gulu,
            )
            for i in range(4)
        ]
        # one school in the neighbouring district, to prove counts do not leak
        School.objects.create(
            school_id="K-1", name="Kitgum School",
            region=self.region, district=self.kitgum,
        )

    def _ssa(self, school, score, fy="FY2026", status="confirmed"):
        return SsaRecord.objects.create(
            school=school, fy=fy, average_score=score,
            verification_status=status, date_of_ssa=datetime.date(2026, 3, 1),
        )

    def _gulu(self, fy=None):
        return district_insight(fy)["Gulu"]

    # ── counts ───────────────────────────────────────────────────────────────
    def test_counts_schools_and_clusters_for_the_right_district(self):
        d = self._gulu()
        self.assertEqual(d["schools"], 4)
        self.assertEqual(d["clusters"], 1)
        self.assertEqual(district_insight()["Kitgum"]["schools"], 1)

    def test_core_school_count_joins_the_business_key_and_ignores_orphans(self):
        """Two failure modes in one join, both silent.

        CoreSchoolProfile.school_id holds School.school_id (e.g. "G-1"), not
        School.id -- joining on School.id matches nothing and reports every
        district as having zero core schools while looking healthy. And
        counting from the profile side instead would include profiles whose
        school does not exist: only 103 of the 325 profiles in the development
        database resolve to a live school.
        """
        from apps.core_schools.models import CorePlan

        plan = CorePlan.objects.create(id="plan-1", school_id="G-1", fy="FY2026")
        CoreSchoolProfile.objects.create(
            id="cprof-G-1", school_id="G-1", core_plan=plan, core_start_fy="FY2026"
        )
        orphan = CorePlan.objects.create(id="plan-x", school_id="GHOST", fy="FY2026")
        CoreSchoolProfile.objects.create(
            id="cprof-GHOST", school_id="GHOST", core_plan=orphan,
            core_start_fy="FY2026",
        )
        self.assertEqual(self._gulu()["core_schools"], 1)

    # ── SSA ──────────────────────────────────────────────────────────────────
    def test_ssa_completion_counts_distinct_schools_not_records(self):
        """Two assessments for one school is one school assessed."""
        self._ssa(self.schools[0], 6.0)
        self._ssa(self.schools[0], 7.0)
        d = self._gulu()
        self.assertEqual(d["ssa_done"], 1)
        self.assertEqual(d["ssa_total"], 4)

    def test_unconfirmed_ssa_is_excluded(self):
        self._ssa(self.schools[0], 9.0, status="pending")
        d = self._gulu()
        self.assertEqual(d["ssa_done"], 0)
        self.assertIsNone(d["ssa_avg"])

    def test_district_without_confirmed_ssa_reports_none_not_zero(self):
        self.assertIsNone(self._gulu()["ssa_avg"])

    def test_cluster_average_covers_only_clustered_schools(self):
        clustered = self.schools[0]
        clustered.cluster_id = self.cluster.id
        clustered.save(update_fields=["cluster_id"])
        self._ssa(clustered, 8.0)
        self._ssa(self.schools[1], 2.0)   # not in a cluster
        d = self._gulu()
        self.assertEqual(d["ssa_avg"], 5.0)          # both schools
        self.assertEqual(d["ssa_avg_cluster"], 8.0)  # clustered only

    def test_core_average_covers_only_core_schools(self):
        from apps.core_schools.models import CorePlan

        plan = CorePlan.objects.create(id="p1", school_id="G-2", fy="FY2026")
        CoreSchoolProfile.objects.create(
            id="cprof-G-2", school_id="G-2", core_plan=plan, core_start_fy="FY2026"
        )
        self._ssa(self.schools[2], 9.0)   # the core school
        self._ssa(self.schools[3], 3.0)
        d = self._gulu()
        self.assertEqual(d["ssa_avg"], 6.0)
        self.assertEqual(d["ssa_avg_core"], 9.0)

    def test_fy_filter_scopes_the_snapshot(self):
        self._ssa(self.schools[0], 4.0, fy="FY2026")
        self._ssa(self.schools[1], 8.0, fy="FY2025")
        self.assertEqual(self._gulu("FY2026")["ssa_avg"], 4.0)
        self.assertEqual(self._gulu("FY2025")["ssa_avg"], 8.0)

    # ── interventions ────────────────────────────────────────────────────────
    def test_names_the_strongest_and_weakest_intervention(self):
        rec = self._ssa(self.schools[0], 5.0)
        for name, score in (("leadership", 9.0), ("enrolment", 2.0), ("teaching", 5.0)):
            SsaScore.objects.create(ssa_record=rec, intervention=name, score=score)
        d = self._gulu()
        self.assertEqual(d["best"]["score"], 9.0)
        self.assertEqual(d["worst"]["score"], 2.0)

    def test_withholds_the_ranking_when_there_is_too_little_evidence(self):
        """One or two scores is not a finding; the card says so instead."""
        rec = self._ssa(self.schools[0], 5.0)
        SsaScore.objects.create(ssa_record=rec, intervention="leadership", score=9.0)
        SsaScore.objects.create(ssa_record=rec, intervention="enrolment", score=2.0)
        self.assertLess(2, MIN_SCORES_FOR_INTERVENTION_CALL)
        d = self._gulu()
        self.assertIsNone(d["best"])
        self.assertIsNone(d["worst"])

    # ── coverage ─────────────────────────────────────────────────────────────
    def _activity(self, school, kind, status="completed", **kw):
        from apps.activities.models import Activity

        return Activity.objects.create(
            school=school, activity_type=kind, status=status, fy="FY2026", **kw
        )

    def test_visited_counts_distinct_schools_not_visits(self):
        self._activity(self.schools[0], "school_visit")
        self._activity(self.schools[0], "coaching_visit")
        self._activity(self.schools[1], "school_visit")
        d = self._gulu()
        self.assertEqual(d["visited"], 2)
        self.assertEqual(d["schools"], 4)

    def test_training_and_visits_are_separate_measures(self):
        self._activity(self.schools[0], "school_visit")
        self._activity(self.schools[1], "training")
        d = self._gulu()
        self.assertEqual(d["visited"], 1)
        self.assertEqual(d["trained"], 1)

    def test_scheduled_work_does_not_count_as_delivered(self):
        self._activity(self.schools[0], "school_visit", status="scheduled")
        self.assertEqual(self._gulu()["visited"], 0)

    def test_teachers_and_leaders_are_summed_over_delivered_work(self):
        self._activity(self.schools[0], "training", teachers_attended=12, leaders_attended=3)
        self._activity(self.schools[1], "training", teachers_attended=8, leaders_attended=2)
        self._activity(self.schools[2], "training", status="scheduled",
                       teachers_attended=99, leaders_attended=99)
        d = self._gulu()
        self.assertEqual(d["teachers_trained"], 20)
        self.assertEqual(d["leaders_trained"], 5)
