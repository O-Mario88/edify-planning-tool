"""Impact Analytics engine + page tests.

World built inline (no fixtures): two districts of paired-SSA schools, a
treated arm with focused executed visits and accepted spend, an untreated
arm with neither. The treated arm improves sharply on Teacher's Environment;
the untreated arm barely moves — every analysis family has a known right
answer against that construction.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffGeographyAssignment,
    StaffProfile,
    User,
)
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.analytics import impact_engine
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.core.navigation import build_sidebar_for_user
from apps.core.rbac import EdifyRole
from apps.debriefs.models import DailyDebrief, DailyDebriefChallenge
from apps.fund_requests.finance_models import PartnerPayment
from apps.fund_requests.models import AdvanceRequest
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

FOCUS = SsaIntervention.TEACHING_ENVIRONMENT.value


def _user(email: str, role: str) -> User:
    return User.objects.create_user(
        email=email,
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        password="password123",
        is_active=True,
    )


def _paired_ssa(school: School, fy: str, prev_scores: dict, curr_scores: dict):
    """A confirmed SSA in the previous FY and one in the selected FY."""
    prev_fy = str(int(fy) - 1)
    now = timezone.now()
    for cycle_fy, days_ago, scores in (
        (prev_fy, 300, prev_scores),
        (fy, 10, curr_scores),
    ):
        record = SsaRecord.objects.create(
            school=school,
            fy=cycle_fy,
            quarter=get_quarter_for_date(),
            date_of_ssa=now - timedelta(days=days_ago),
            verification_status="confirmed",
        )
        for intervention in SsaIntervention:
            SsaScore.objects.create(
                ssa_record=record,
                intervention=intervention.value,
                score=scores.get(intervention.value, 5.0),
            )


def _visit(school: School, fy: str, *, days_ago: int = 60, status: str = "ia_verified"):
    return Activity.objects.create(
        school=school,
        activity_type="school_visit",
        status=status,
        planned_date=timezone.now().date() - timedelta(days=days_ago),
        fy=fy,
        focus_intervention=FOCUS,
        delivery_type="staff",
    )


def _accepted_advance(activity: Activity, amount: int):
    line = ActivityScheduleCostLine.objects.create(
        activity=activity,
        school=activity.school,
        cost_setting_key="transport",
        label="Transport",
        line_item_type="transport",
        unit_cost=amount,
        quantity=1,
        amount=amount,
    )
    return AdvanceRequest.objects.create(
        activity=activity,
        budget_line=line,
        fy=activity.fy,
        quarter="Q1",
        amount=amount,
        status="accounted",
        accounted_amount=amount,
        disbursed_amount=amount,
    )


class ImpactEngineStatsTest(TestCase):
    """Engine mathematics on a constructed two-arm world."""

    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        region = Region.objects.create(name="Impact Region")
        cls.treated_district = District.objects.create(
            name="Treated District", region=region
        )
        cls.untreated_district = District.objects.create(
            name="Untreated District", region=region
        )
        cls.admin = _user("impact-admin@edify.test", EdifyRole.ADMIN.value)

        cls.treated, cls.untreated = [], []
        for i in range(10):
            school = School.objects.create(
                school_id=f"IMP-T{i}",
                name=f"Treated School {i}",
                region=region,
                district=cls.treated_district,
            )
            # Weak baseline (4.0) on the focus intervention; strong improvement
            # there (+2.0) and mild gains elsewhere (+0.5) so the school-level
            # mean delta clears the +0.3 improvement bar. ENROLMENT stays flat
            # in BOTH arms — the all-identical case for the geography test.
            _paired_ssa(
                school,
                cls.fy,
                {FOCUS: 4.0},
                {
                    FOCUS: 6.0,
                    **{
                        i.value: 5.5
                        for i in SsaIntervention
                        if i.value not in (FOCUS, SsaIntervention.ENROLMENT.value)
                    },
                },
            )
            visit = _visit(school, cls.fy)
            _accepted_advance(visit, 100_000)
            cls.treated.append(school)
        for i in range(10):
            school = School.objects.create(
                school_id=f"IMP-U{i}",
                name=f"Untreated School {i}",
                region=region,
                district=cls.untreated_district,
            )
            # Same weak baseline, near-zero movement, no visits, no money.
            _paired_ssa(school, cls.fy, {FOCUS: 4.0}, {FOCUS: 4.2})
            cls.untreated.append(school)

    def test_improvement_frame_pairs_confirmed_cycles_only(self):
        school_ids = [s.id for s in self.treated + self.untreated]
        imp = impact_engine.improvement_frame(school_ids, self.fy)
        self.assertEqual(imp["school_id"].nunique(), 20)
        focus_rows = imp[imp["intervention"] == FOCUS]
        treated_ids = {s.id for s in self.treated}
        for _, row in focus_rows.iterrows():
            expected = 2.0 if row["school_id"] in treated_ids else 0.2
            self.assertAlmostEqual(row["delta"], expected, places=5)

        # A school with only one cycle never enters the frame.
        lone = School.objects.create(
            school_id="IMP-LONE",
            name="Single Cycle",
            region=self.treated_district.region,
            district=self.treated_district,
        )
        record = SsaRecord.objects.create(
            school=lone,
            fy=self.fy,
            quarter="Q1",
            date_of_ssa=timezone.now(),
            verification_status="confirmed",
        )
        for intervention in SsaIntervention:
            SsaScore.objects.create(
                ssa_record=record, intervention=intervention.value, score=5.0
            )
        imp2 = impact_engine.improvement_frame(school_ids + [lone.id], self.fy)
        self.assertNotIn(lone.id, set(imp2["school_id"]))

    def test_dosage_counts_only_executed_window_activities(self):
        school = self.treated[0]
        # Outside the exposure window (before the baseline assessment).
        _visit(school, self.fy, days_ago=400)
        # Executed but merely planned status — not counted.
        _visit(school, self.fy, days_ago=50, status="planned")

        school_ids = [s.id for s in self.treated + self.untreated]
        imp = impact_engine.improvement_frame(school_ids, self.fy)
        acts = impact_engine.activity_frame(imp, school_ids)
        per_school = acts[acts["school_id"] == school.id]
        self.assertEqual(len(per_school), 1)  # only the original in-window visit

    def test_treated_effect_is_significant_in_weak_stratum(self):
        school_ids = [s.id for s in self.treated + self.untreated]
        imp = impact_engine.improvement_frame(school_ids, self.fy)
        acts = impact_engine.activity_frame(imp, school_ids)
        visits = impact_engine.dosage_impact(imp, acts, "visit")

        row = next(r for r in visits["per_intervention"] if r["key"] == FOCUS)
        self.assertEqual(row["n_treated"], 10)
        self.assertEqual(row["n_untreated"], 10)
        self.assertAlmostEqual(row["effect"], 1.8, places=2)
        self.assertEqual(row["verdict"], "significant")

        # Leadership has a weak-baseline stratum (5.0 < 7.0) but zero schools
        # received leadership-focused visits — too small a treated group.
        other = next(
            r
            for r in visits["per_intervention"]
            if r["key"] == SsaIntervention.LEADERSHIP.value
        )
        self.assertEqual(other["n_treated"], 0)
        self.assertEqual(other["verdict"], "insufficient data")

        # Dose-response: more visits ↔ more improvement.
        self.assertIsNotNone(visits["correlation"]["rho"])
        self.assertGreater(visits["correlation"]["rho"], 0)

    def test_funding_accepts_only_accountant_accepted_money(self):
        school_ids = [s.id for s in self.treated + self.untreated]
        imp = impact_engine.improvement_frame(school_ids, self.fy)

        # Disbursed-but-unaccounted advance must NOT count.
        pending_visit = _visit(self.untreated[0], self.fy, days_ago=55)
        line = ActivityScheduleCostLine.objects.create(
            activity=pending_visit,
            school=pending_visit.school,
            cost_setting_key="lunch",
            label="Lunch",
            line_item_type="lunch",
            unit_cost=50_000,
            quantity=1,
            amount=50_000,
        )
        AdvanceRequest.objects.create(
            activity=pending_visit,
            budget_line=line,
            fy=self.fy,
            quarter="Q1",
            amount=50_000,
            status="disbursed",
            disbursed_amount=50_000,
        )
        # Partner payment DOES count.
        partner_visit = _visit(self.untreated[1], self.fy, days_ago=55)
        PartnerPayment.objects.create(
            activity=partner_visit,
            partner_name="Partner X",
            amount_paid=30_000,
            payment_method="bank",
            payment_reference="REF-1",
            paid_by=self.admin.id,
        )

        acts = impact_engine.activity_frame(imp, school_ids)
        funding = impact_engine.funding_impact(imp, acts, {}, show_names=False)
        self.assertEqual(funding["total_accepted_spend"], 10 * 100_000 + 30_000)
        self.assertEqual(funding["funded_schools"], 11)  # 10 treated + partner school
        self.assertEqual(funding["funded_improved"], 10)
        self.assertIsNotNone(funding["ugx_per_point"])

    def test_geography_detects_district_difference(self):
        school_ids = [s.id for s in self.treated + self.untreated]
        imp = impact_engine.improvement_frame(school_ids, self.fy)
        districts = {s.id: s.district.name for s in self.treated + self.untreated}
        geo = impact_engine.geographic_performance(imp, districts)

        self.assertEqual(len(geo["matrix"]), 2)  # both districts have >= 8 schools
        focus_test = next(t for t in geo["tests"] if t["key"] == FOCUS)
        self.assertEqual(focus_test["verdict"], "significant")
        # ENROLMENT is identical in every school of both districts — the
        # engine must say "insufficient data", never a fabricated verdict.
        flat_test = next(
            t for t in geo["tests"] if t["key"] == SsaIntervention.ENROLMENT.value
        )
        self.assertEqual(flat_test["verdict"], "insufficient data")

    def test_field_reality_overlay_reports_debrief_signals(self):
        debrief = DailyDebrief.objects.create(
            fy=self.fy,
            date=timezone.now(),
            submitted_at=timezone.now(),
            submitted_by_user_id=self.admin.id,
            debrief_type="staff",
            kind="activity",
            status="submitted",
            title="Field reality",
            intervention_tags=[FOCUS],
            linked_school_ids=[self.untreated[0].id],
            risk_level="critical",
        )
        DailyDebriefChallenge.objects.create(
            debrief=debrief,
            challenge_type="funds_delayed",
            severity="high",
        )
        school_ids = [s.id for s in self.treated + self.untreated]
        imp = impact_engine.improvement_frame(school_ids, self.fy)
        overlay = impact_engine.field_reality_overlay(self.admin, imp, self.fy)

        row = next(r for r in overlay if r["key"] == FOCUS)
        self.assertEqual(row["debriefs"], 1)
        self.assertEqual(row["critical_debriefs"], 1)
        self.assertEqual(row["top_challenges"][0]["count"], 1)
        # Median across 10×2.0 and 10×0.2 = 1.1 → improving.
        self.assertEqual(row["direction"], "improving")

    def test_dashboard_assembles_with_json_chart_payloads(self):
        dashboard = impact_engine.build_dashboard(self.admin, {})
        self.assertEqual(dashboard["coverage"]["schools_paired"], 20)
        self.assertIsNotNone(dashboard["kpis"]["median_delta"])
        # Chart payloads must be valid JSON strings (None → null, not repr).
        import json as _json

        for key, payload in dashboard["charts"].items():
            _json.loads(payload)
        self.assertTrue(dashboard["method_notes"])


class ImpactPageTest(TestCase):
    """Page permissions, scoping flags, and honest empty state."""

    def setUp(self):
        self.fy = get_operational_fy()
        self.region = Region.objects.create(name="Page Region")
        self.district = District.objects.create(
            name="Page District", region=self.region
        )
        self.cd = _user("impact-cd@edify.test", EdifyRole.COUNTRY_DIRECTOR.value)
        self.cceo = _user("impact-cceo@edify.test", EdifyRole.CCEO.value)
        self.accountant = _user(
            "impact-acc@edify.test", EdifyRole.PROGRAM_ACCOUNTANT.value
        )

    def test_cd_gets_page_and_htmx_partial(self):
        client = Client()
        client.force_login(self.cd)
        res = client.get("/impact")
        self.assertEqual(res.status_code, 200)
        self.assertIn("dashboard", res.context)
        self.assertTemplateUsed(res, "pages/analytics/impact.html")

        res = client.get("/impact", HTTP_HX_REQUEST="true")
        self.assertEqual(res.status_code, 200)
        self.assertTemplateUsed(res, "partials/analytics/impact_workspace.html")

    def test_cceo_is_denied(self):
        client = Client()
        client.force_login(self.cceo)
        res = client.get("/impact")
        self.assertEqual(res.status_code, 302)

    def test_sidebar_visibility_follows_permissions(self):
        cd_labels = [
            item["label"]
            for group in build_sidebar_for_user(self.cd, "/impact")
            for item in group["items"]
        ]
        self.assertIn("Impact Analytics", cd_labels)
        for excluded in (self.cceo, self.accountant):
            labels = [
                item["label"]
                for group in build_sidebar_for_user(excluded, "/dashboard")
                for item in group["items"]
            ]
            self.assertNotIn("Impact Analytics", labels)

    def test_empty_state_is_honest_without_paired_cycles(self):
        client = Client()
        client.force_login(self.cd)
        res = client.get("/impact")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["dashboard"]["coverage"]["schools_paired"], 0)
        self.assertContains(res, "No paired assessment cycles yet")

    def test_rvp_aggregates_without_school_identity(self):
        rvp = _user("impact-rvp@edify.test", EdifyRole.REGIONAL_VICE_PRESIDENT.value)
        staff = StaffProfile.objects.create(user=rvp, title="RVP")
        StaffGeographyAssignment.objects.create(staff=staff, region_id=self.region.id)

        school = School.objects.create(
            school_id="IMP-RVP",
            name="RVP Region School",
            region=self.region,
            district=self.district,
        )
        _paired_ssa(school, self.fy, {FOCUS: 4.0}, {FOCUS: 5.0})
        visit = _visit(school, self.fy)
        _accepted_advance(visit, 40_000)

        dashboard = impact_engine.build_dashboard(rvp, {})
        self.assertEqual(dashboard["coverage"]["schools_paired"], 1)
        self.assertFalse(dashboard["scope"]["can_view_school_details"])
