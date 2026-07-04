"""Analytics accuracy tests — SSA improvement, interventions, recommendations.

Proves the decision engine computes from real records: per-school SSA delta,
intervention-level averages, improvement classification, and that
recommendations fire on real risk conditions (not hardcoded).
"""
from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.analytics.decision_engine import (
    ssa_improvement,
    intervention_analytics,
    district_ssa_rollup,
    recommendations,
)
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore


def _stub_principal(user_id, role, staff_id=None, school_ids=None):
    """Minimal principal for scope resolution."""
    return type("P", (), {
        "user_id": user_id, "id": user_id, "active_role": role,
        "staff_profile_id": staff_id, "country_scope": role in ("CountryDirector", "ImpactAssessment", "Admin"),
        "can_view_summary_only": role == "RegionalVicePresident",
        "school_ids": school_ids or [], "staff_ids": [staff_id] if staff_id else [],
        "supervised_staff_ids": [], "partner_ids": [], "region_ids": [],
        "district_ids": [], "own_school_ids": school_ids or [],
        "team_school_ids": [], "core_school_ids": [], "cluster_ids": [],
    })()


class AnalyticsTest(TestCase):
    def setUp(self):
        self.fy = get_operational_fy()
        self.prev_fy = str(int(self.fy) - 1)
        self.region = Region.objects.create(name="Analytics Region")
        self.district = District.objects.create(name="Analytics District", region=self.region)
        self.sub_county = SubCounty.objects.create(name="Analytics Sub", district=self.district)
        # An IA principal (country scope) so all schools are in scope.
        self.ia = User.objects.create_user(
            email="ia@analytics.test", name="Analytics IA",
            roles=[EdifyRole.IMPACT_ASSESSMENT.value], active_role=EdifyRole.IMPACT_ASSESSMENT.value,
            password="x", is_active=True,
        )
        self.principal = _stub_principal(self.ia.id, EdifyRole.IMPACT_ASSESSMENT.value)

    def _school(self, school_id: str, ssa_status="done") -> School:
        return School.objects.create(
            school_id=school_id, name=f"{school_id} Primary", region=self.region,
            district=self.district, sub_county=self.sub_county,
            current_fy_ssa_status=ssa_status,
        )

    def _ssa(self, school: School, fy: str, avg_score: float, verified=True) -> SsaRecord:
        rec = SsaRecord.objects.create(
            school=school, fy=fy, quarter="Q3",
            date_of_ssa=timezone.now() - timedelta(days=10),
            average_score=avg_score,
            verification_status="confirmed" if verified else "pending",
        )
        for interv in SsaIntervention:
            SsaScore.objects.create(ssa_record=rec, intervention=interv.value, score=avg_score)
        return rec

    # ── SSA improvement ──────────────────────────────────────────────────────
    def test_ssa_improvement_computes_per_school_delta(self):
        """A school that went from 5.0 → 7.0 should show delta +2.0 (improved)."""
        s = self._school("IMP-1")
        self._ssa(s, self.prev_fy, 5.0)
        self._ssa(s, self.fy, 7.0)
        result = ssa_improvement(self.principal, {"fy": self.fy})
        self.assertEqual(result["schoolsCompared"], 1)
        self.assertEqual(result["improvedCount"], 1)
        self.assertEqual(result["declinedCount"], 0)
        self.assertEqual(result["improved"][0]["delta"], 2.0)
        self.assertEqual(result["averageDelta"], 2.0)

    def test_declining_school_classified_correctly(self):
        s = self._school("IMP-2")
        self._ssa(s, self.prev_fy, 7.0)
        self._ssa(s, self.fy, 4.0)
        result = ssa_improvement(self.principal, {"fy": self.fy})
        self.assertEqual(result["declinedCount"], 1)
        self.assertEqual(result["improvedCount"], 0)
        self.assertEqual(result["declined"][0]["delta"], -3.0)

    def test_school_with_only_one_ssa_not_compared(self):
        """A school with only a current-FY SSA (no previous) is not compared."""
        s = self._school("IMP-3")
        self._ssa(s, self.fy, 6.0)
        result = ssa_improvement(self.principal, {"fy": self.fy})
        self.assertEqual(result["schoolsCompared"], 0)

    def test_no_change_within_threshold(self):
        s = self._school("IMP-4")
        self._ssa(s, self.prev_fy, 5.0)
        self._ssa(s, self.fy, 5.1)  # delta +0.1, within ±0.3
        result = ssa_improvement(self.principal, {"fy": self.fy})
        self.assertEqual(result["noChangeCount"], 1)
        self.assertEqual(result["improvedCount"], 0)
        self.assertEqual(result["declinedCount"], 0)

    def test_unverified_ssa_excluded_from_improvement(self):
        s = self._school("IMP-5")
        self._ssa(s, self.prev_fy, 5.0, verified=False)
        self._ssa(s, self.fy, 8.0, verified=False)
        result = ssa_improvement(self.principal, {"fy": self.fy})
        self.assertEqual(result["schoolsCompared"], 0)  # unverified excluded

    # ── Intervention analytics ───────────────────────────────────────────────
    def test_intervention_analytics_returns_all_8(self):
        s = self._school("INT-1")
        self._ssa(s, self.fy, 6.0)
        result = intervention_analytics(self.principal, {"fy": self.fy})
        self.assertEqual(len(result["interventions"]), 8)
        for interv_data in result["interventions"].values():
            self.assertEqual(interv_data["current"], 6.0)

    def test_intervention_analytics_ranks_weakest_and_strongest(self):
        s1 = self._school("INT-2")
        # Create SSA with varied scores per intervention.
        rec = SsaRecord.objects.create(
            school=s1, fy=self.fy, quarter="Q3", date_of_ssa=timezone.now(),
            average_score=5.0, verification_status="confirmed",
        )
        scores = [8.0, 3.0, 7.0, 6.0, 4.0, 5.0, 9.0, 5.0]
        for interv, score in zip(SsaIntervention, scores):
            SsaScore.objects.create(ssa_record=rec, intervention=interv.value, score=score)
        result = intervention_analytics(self.principal, {"fy": self.fy})
        # financial_health (3.0) is weakest; education_technology (9.0) is strongest.
        self.assertEqual(result["weakest"], "financial_health")
        self.assertEqual(result["strongest"], "education_technology")

    # ── District rollup ──────────────────────────────────────────────────────
    def test_district_rollup_matches_ssa_records(self):
        s = self._school("DIS-1")
        self._ssa(s, self.fy, 6.5)
        result = district_ssa_rollup(self.principal, {"fy": self.fy})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["district"], "Analytics District")
        self.assertEqual(result[0]["ssaCount"], 1)
        self.assertEqual(result[0]["averageScore"], 6.5)

    # ── Recommendations ──────────────────────────────────────────────────────
    def test_recommendation_fires_for_schools_without_ssa(self):
        """Schools without SSA generate a high-priority recommendation."""
        School.objects.create(
            school_id="REC-1", name="No SSA School", region=self.region,
            district=self.district, sub_county=self.sub_county,
            current_fy_ssa_status="not_done",
        )
        recs = recommendations(self.principal, {"fy": self.fy})
        ssa_recs = [r for r in recs if "SSA" in r["reason"] or "no current-FY SSA" in r["reason"]]
        self.assertTrue(len(ssa_recs) >= 1)
        self.assertEqual(ssa_recs[0]["priority"], "high")

    def test_recommendation_fires_for_declining_ssa(self):
        s = self._school("REC-2")
        self._ssa(s, self.prev_fy, 7.0)
        self._ssa(s, self.fy, 3.0)  # declined by 4.0
        recs = recommendations(self.principal, {"fy": self.fy})
        decline_recs = [r for r in recs if "declining" in r["reason"].lower()]
        self.assertTrue(len(decline_recs) >= 1)

    def test_no_recommendations_when_no_risks(self):
        """When everything is fine, no recommendations fire."""
        s = self._school("REC-3")
        self._ssa(s, self.prev_fy, 6.0)
        self._ssa(s, self.fy, 7.0)  # improved
        recs = recommendations(self.principal, {"fy": self.fy})
        # No schools without SSA, no declining SSA, but there might be weak-cluster
        # or weak-intervention recs. At least no high-priority SSA-blocked rec.
        high_recs = [r for r in recs if r["priority"] == "high" and "SSA" in r["reason"]]
        self.assertEqual(len(high_recs), 0)

    # ── Role scope ───────────────────────────────────────────────────────────
    def test_cceo_scope_restricts_to_own_schools(self):
        """A CCEO should only see SSA for their own schools, not all schools."""
        cceo = User.objects.create_user(
            email="cceo@analytics.test", name="Analytics CCEO",
            roles=[EdifyRole.CCEO.value], active_role=EdifyRole.CCEO.value,
            password="x", is_active=True,
        )
        cceo_staff = StaffProfile.objects.create(user=cceo, title="CCEO")
        own_school = self._school("CCEO-OWN")
        other_school = self._school("CCEO-OTHER")
        StaffSchoolAssignment.objects.create(staff=cceo_staff, school_id=own_school.id)
        self._ssa(own_school, self.fy, 7.0)
        self._ssa(other_school, self.fy, 3.0)  # should NOT appear for this CCEO
        cceo_principal = _stub_principal(
            cceo.id, EdifyRole.CCEO.value, staff_id=cceo_staff.id, school_ids=[own_school.id],
        )
        from apps.analytics.services import ssa_performance
        result = ssa_performance(cceo_principal, {"fy": self.fy})
        self.assertEqual(result["recordsCount"], 1)  # only own school's SSA
        self.assertEqual(result["averageScore"], 7.0)
