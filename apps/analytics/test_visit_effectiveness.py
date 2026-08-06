"""School Visit Effectiveness — methodology guardrails (mandate §19/§20).

Only verified SSA enters; visits count only inside each school's own
baseline→follow-up window; Core/Client and staff/Partner never blur;
schools without follow-up are "not yet measurable"; scope walls hold;
language stays associational."""

from __future__ import annotations

import datetime as dt

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity
from apps.analytics.visit_effectiveness_engine import (
    LEGACY_INTERVENTION_LABELS,
    SchoolVisitEffectivenessAnalyticsService as S,
)
from apps.core.enums import SsaIntervention
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

User = get_user_model()
IVS = [c[0] for c in SsaIntervention.choices]


def _aware(y, m, d):
    return timezone.make_aware(dt.datetime(y, m, d, 10, 0))


class VisitEffectivenessTestBase(TestCase):
    def setUp(self):
        self.cd = User.objects.create_user(
            email="cd@vfx.org",
            name="CD",
            password="x",
            is_active=True,
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
        )
        StaffProfile.objects.create(user=self.cd, country="Uganda")
        self.region = Region.objects.create(name="Central")
        self.region2 = Region.objects.create(name="Northern")
        self.district = District.objects.create(
            name="Mukono", region=self.region, district_type="primary"
        )
        self.core = self._school("VFX-CORE", "Core School", "core")
        self.client_s = self._school("VFX-CL", "Client School", "client")

    def _school(self, sid, name, stype, district=None):
        return School.objects.create(
            school_id=sid,
            name=name,
            school_type=stype,
            region=self.region,
            district=district or self.district,
            enrollment=100,
        )

    def _ssa(self, school, fy, date, avg, status="confirmed", scores=None):
        r = SsaRecord.objects.create(
            school=school,
            fy=fy,
            date_of_ssa=date,
            average_score=avg,
            verification_status=status,
            collector_type="staff",
        )
        for iv in IVS:
            SsaScore.objects.create(
                ssa_record=r,
                intervention=iv,
                score=(scores or {}).get(iv, avg),
            )
        return r

    def _pair(self, school, base_avg=4.0, follow_avg=5.0, base_scores=None):
        self._ssa(school, "2024", _aware(2024, 5, 10), base_avg, scores=base_scores)
        self._ssa(school, "2026", _aware(2026, 6, 10), follow_avg)

    def _visit(
        self,
        school,
        date,
        status="ia_verified",
        delivery="staff",
        atype="school_visit",
        focus=None,
    ):
        return Activity.objects.create(
            school=school,
            activity_type=atype,
            delivery_type=delivery,
            status=status,
            fy="2026",
            quarter="Q2",
            planned_date=date,
            focus_intervention=focus,
            responsible_staff_id="staff-1",
        )


class CohortGuardrailTests(VisitEffectivenessTestBase):
    def test_only_verified_baseline_and_followup_enter(self):
        self._pair(self.core)  # valid pair
        # pending baseline → excluded
        self._ssa(self.client_s, "2024", _aware(2024, 5, 1), 4.0, status="pending")
        self._ssa(self.client_s, "2026", _aware(2026, 6, 1), 5.0)
        c = S.build_cohort(self.cd)
        self.assertEqual(list(c.schools["id"]), [self.core.id])

    def test_school_without_followup_is_not_yet_measurable_never_labelled(self):
        self._ssa(self.core, "2024", _aware(2024, 5, 1), 4.0)
        c = S.build_cohort(self.cd)
        self.assertEqual(len(c.schools), 0)
        self.assertEqual(c.excluded["missing_followup_ssa"], 1)

    def test_duplicate_confirmed_records_resolve_to_latest_and_school_counts_once(self):
        self._pair(self.core)
        self._ssa(self.core, "2024", _aware(2024, 9, 1), 6.5)  # later duplicate
        c = S.build_cohort(self.cd)
        self.assertEqual(len(c.schools), 1)
        self.assertEqual(float(c.schools.iloc[0]["baseline_avg"]), 6.5)

    def test_fy2025_is_blocked_by_methodology(self):
        d = S.build_dashboard(self.cd, {"baseline_fy": "2025"})
        self.assertEqual(d["methodology"]["baseline_fy"], "FY2024")
        self.assertIn("FY2025", d["methodology"]["excluded_fys"])

    def test_legacy_labels_map_onto_all_eight_canonical_keys(self):
        self.assertEqual(len(LEGACY_INTERVENTION_LABELS), 8)
        self.assertEqual(set(LEGACY_INTERVENTION_LABELS.values()), set(IVS))
        self.assertEqual(
            LEGACY_INTERVENTION_LABELS["Teaching Environment"],
            SsaIntervention.TEACHING_ENVIRONMENT,
        )
        self.assertEqual(
            LEGACY_INTERVENTION_LABELS["Fees/Budget/Accounts"],
            SsaIntervention.FINANCIAL_HEALTH,
        )


class VisitWindowTests(VisitEffectivenessTestBase):
    def setUp(self):
        super().setUp()
        self._pair(self.core)

    def test_visits_outside_the_window_and_cancelled_never_count(self):
        c = S.build_cohort(self.cd)
        self._visit(self.core, dt.date(2024, 4, 1))  # before baseline
        self._visit(self.core, dt.date(2026, 7, 1))  # after follow-up
        self._visit(self.core, dt.date(2025, 5, 1), status="cancelled")
        inside = self._visit(self.core, dt.date(2025, 5, 1))
        v = S.visit_frame(c)
        self.assertEqual(list(v["id"]), [inside.id])

    def test_scheduled_is_not_delivered(self):
        c = S.build_cohort(self.cd)
        self._visit(self.core, dt.date(2025, 5, 1), status="scheduled")
        self._visit(self.core, dt.date(2025, 6, 1), status="ia_verified")
        d = S.build_dashboard(self.cd, {})
        self.assertEqual(d["coverage"]["delivered_visits"], 1)
        self.assertEqual(d["coverage"]["scheduled_only_visits"], 1)

    def test_staff_and_partner_delivery_never_blur(self):
        c = S.build_cohort(self.cd)  # noqa: F841 — cohort must exist first
        self._visit(self.core, dt.date(2025, 5, 1), delivery="staff")
        self._visit(
            self.core,
            dt.date(2025, 5, 2),
            delivery="partner",
            atype="partner_ssa_collection",
        )
        self._visit(
            self.core, dt.date(2025, 5, 3), delivery="partner", atype="school_visit"
        )
        d = S.build_dashboard(self.cd, {})
        self.assertEqual(d["coverage"]["staff_visits"], 1)
        self.assertEqual(d["coverage"]["partner_visits"], 2)
        self.assertEqual(d["coverage"]["partner_data_collection_share"], 0.5)

    def test_core_and_client_stay_separate(self):
        self._pair(self.client_s, base_avg=4.0, follow_avg=4.2)
        d = S.build_dashboard(self.cd, {})
        by = d["ssa_change"]["by_school_type"]
        self.assertEqual(by["core"]["n"], 1)
        self.assertEqual(by["client"]["n"], 1)
        self.assertAlmostEqual(by["core"]["avg_delta"], 1.0, places=2)
        self.assertAlmostEqual(by["client"]["avg_delta"], 0.2, places=2)
        d_core = S.build_dashboard(self.cd, {"school_type": "core"})
        self.assertEqual(d_core["cohort"]["comparable_schools"], 1)


class AlignmentAndLanguageTests(VisitEffectivenessTestBase):
    def test_alignment_requires_hitting_a_weakest_baseline_intervention(self):
        weak_scores = {iv: 6.0 for iv in IVS}
        weak_scores[SsaIntervention.LEADERSHIP] = 2.0
        weak_scores[SsaIntervention.ENROLMENT] = 2.5
        self._pair(self.core, base_scores=weak_scores)
        c = S.build_cohort(self.cd)
        aligned = self._visit(
            self.core, dt.date(2025, 5, 1), focus=SsaIntervention.LEADERSHIP
        )
        unaligned = self._visit(
            self.core, dt.date(2025, 5, 2), focus=SsaIntervention.FINANCIAL_HEALTH
        )
        v = S._alignment(c, S.visit_frame(c))
        row = v.set_index("id")
        self.assertTrue(bool(row.loc[aligned.id, "aligned"]))
        self.assertFalse(bool(row.loc[unaligned.id, "aligned"]))

    def test_small_samples_are_flagged_and_language_is_associational(self):
        self._pair(self.core)
        d = S.build_dashboard(self.cd, {})
        self.assertEqual(d["cohort"]["sample_quality"], "very limited")
        self.assertEqual(d["association"]["verdict"], "insufficient sample")
        self.assertIn("not causation", d["association"]["note"])
        joined = " ".join(d["method_notes"]).lower()
        self.assertIn("association", joined)
        self.assertNotIn("caused", joined)


class ScopeAndSnapshotTests(VisitEffectivenessTestBase):
    def test_role_without_school_scope_sees_nothing(self):
        self._pair(self.core)
        cceo = User.objects.create_user(
            email="cceo@vfx.org",
            name="C",
            password="x",
            is_active=True,
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
        )
        StaffProfile.objects.create(user=cceo, country="Uganda")
        d = S.build_dashboard(cceo, {})
        self.assertEqual(d["cohort"]["comparable_schools"], 0)

    def test_snapshot_versions_and_supersedes(self):
        self._pair(self.core)
        s1 = S.snapshot(self.cd, {})
        s2 = S.snapshot(self.cd, {})
        s1.refresh_from_db()
        self.assertEqual(s1.status, "superseded")
        self.assertEqual(s2.version, 2)
        self.assertEqual(s2.results["cohort"]["comparable_schools"], 1)
        self.assertEqual(s2.methodology_version, "v1-fy24-fy26")
