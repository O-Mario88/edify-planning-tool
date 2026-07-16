"""CD Executive Command Center — the 13 mandated tests (mandate §23).

Fixture: 2 PLs each supervising 1 CCEO across 2 regions, verified SSA cycle,
completed/planned activities with and without Activity SF IDs, an escalated
weekly fund request, a disbursed-but-incomplete advance, a monthly country
budget at a CD stage, and a core plan behind schedule.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import Resolver404, resolve
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    StaffTargetProfile,
)
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.analytics.cd_dashboard_service import CDDashboardService as S
from apps.core.rbac import EdifyRole
from apps.core_schools.models import CorePlan
from apps.fund_requests.models import AdvanceRequest, WeeklyFundRequest
from apps.geography.models import District, Region
from apps.monthly_work_plan.models import MonthlyWorkPlanBudget
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

User = get_user_model()
FY = "2026"


class CDCommandCenterTest(TestCase):
    def setUp(self):
        self.region_a = Region.objects.create(name="Central Region")
        self.region_b = Region.objects.create(name="Northern Region")
        self.dist_a = District.objects.create(
            name="Dist A", region=self.region_a, district_type="primary"
        )
        self.dist_b = District.objects.create(
            name="Dist B", region=self.region_b, district_type="primary"
        )

        self.cd, _ = self._staff("cd@t.org", "CD", EdifyRole.COUNTRY_DIRECTOR.value)
        self.pl_a, self.pl_a_sp = self._staff(
            "pla@t.org", "PL Ada", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.a1, self.a1_sp = self._staff("a1@t.org", "CCEO A1", EdifyRole.CCEO.value)
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_a_sp, supervisee=self.a1_sp
        )
        self.pl_b, self.pl_b_sp = self._staff(
            "plb@t.org", "PL Bola", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.b1, self.b1_sp = self._staff("b1@t.org", "CCEO B1", EdifyRole.CCEO.value)
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_b_sp, supervisee=self.b1_sp
        )

        self.sch_a = self._school("A", self.region_a, self.dist_a, ssa_done=True)
        self.sch_a2 = self._school("A2", self.region_a, self.dist_a, ssa_done=False)
        self.sch_b = self._school("B", self.region_b, self.dist_b, ssa_done=False)
        StaffSchoolAssignment.objects.create(staff=self.a1_sp, school_id=self.sch_a.id)
        StaffSchoolAssignment.objects.create(staff=self.a1_sp, school_id=self.sch_a2.id)
        StaffSchoolAssignment.objects.create(staff=self.b1_sp, school_id=self.sch_b.id)

        self._ssa(self.sch_a, FY, 7.5, {"leadership": 7.0, "enrolment": 6.0})

        # Region A: 2 completed (1 with SF ID, 1 without) → 50% compliance.
        self._act(self.a1_sp.id, self.sch_a, "school_visit", "ia_verified", sf="SV-1")
        self._act(self.a1_sp.id, self.sch_a, "training", "completed", sf="")
        # Region B: planned only → 0% regional achievement.
        self._act(self.b1_sp.id, self.sch_b, "school_visit", "scheduled")

        StaffTargetProfile.objects.create(
            staff=self.a1_sp, fy=FY, visits_target=2, trainings_target=1
        )
        StaffTargetProfile.objects.create(staff=self.b1_sp, fy=FY, visits_target=4)

        self.wfr = WeeklyFundRequest.objects.create(
            fy=FY,
            week_start_date=date(2026, 7, 13),
            week_end_date=date(2026, 7, 19),
            responsible_user=self.pl_a.id,
            total_amount=300_000,
            status="submitted_to_cd",
        )
        MonthlyWorkPlanBudget.objects.create(
            fy=FY,
            month_key="2026-08",
            status="cd_review",
            total_amount=5_000_000,
        )
        # Disbursed advance on a still-scheduled (funded-not-completed) activity.
        self.act_funded = self._act(
            self.b1_sp.id, self.sch_b, "school_visit", "scheduled"
        )
        line = ActivityScheduleCostLine.objects.create(
            activity=self.act_funded,
            cost_setting_key="transport",
            label="Transport",
            unit_cost=80_000,
            amount=80_000,
        )
        AdvanceRequest.objects.create(
            activity=self.act_funded,
            budget_line=line,
            responsible_user_id=self.b1.id,
            fy=FY,
            quarter="Q4",
            planned_date=date(2026, 7, 1),
            amount=80_000,
            status="disbursed",
            disbursed_amount=80_000,
        )
        CorePlan.objects.create(
            id="cplan-test-1",
            school_id=self.sch_a.school_id,
            fy=FY,
            status="Active",
            baseline_average=5.5,
            visits_completed=0,
            trainings_completed=0,
        )

    # ── fixtures ─────────────────────────────────────────────────────────────
    def _staff(self, email, name, role):
        u = User.objects.create_user(
            email=email,
            name=name,
            roles=[role],
            active_role=role,
            password="x",
            is_active=True,
        )
        return u, StaffProfile.objects.create(user=u, title=role)

    def _school(self, sid, region, district, ssa_done):
        return School.objects.create(
            school_id=f"S-{sid}",
            name=f"School {sid}",
            region=region,
            district=district,
            enrollment=100,
            current_fy_ssa_status="done" if ssa_done else "not_done",
        )

    def _ssa(self, school, fy, avg, scores):
        rec = SsaRecord.objects.create(
            school=school,
            fy=fy,
            quarter="Q1",
            average_score=avg,
            verification_status="confirmed",
            date_of_ssa=date(2025, 11, 1),
            uploaded_by="t",
        )
        for k, v in scores.items():
            SsaScore.objects.create(ssa_record=rec, intervention=k, score=v)

    def _act(self, sp_id, school, atype, status, sf=""):
        return Activity.objects.create(
            school=school,
            activity_type=atype,
            delivery_type="staff",
            status=status,
            responsible_staff_id=sp_id,
            fy=FY,
            quarter="Q3",
            planned_date=date(2026, 4, 10),
            scheduled_date=timezone.make_aware(timezone.datetime(2026, 4, 10, 9, 0)),
            salesforce_activity_id=sf,
        )

    def _dash(self):
        return S.get_dashboard(self.cd, fy=FY)

    def _kpis(self, d=None):
        d = d or self._dash()
        return {k["label"]: k for k in d["kpi_strip_items"]}

    # 1 ─ country scope
    def test_cd_dashboard_country_scope(self):
        d = self._dash()
        pl_names = {r["name"] for r in d["pl_performance"]["rows"]}
        self.assertEqual(pl_names, {"PL Ada", "PL Bola"})
        region_names = {r["name"] for r in d["regional_performance"]["rows"]}
        self.assertEqual(region_names, {"Central Region", "Northern Region"})

    # 2 ─ no field execution actions
    def test_cd_dashboard_does_not_show_field_execution_actions(self):
        d = self._dash()
        banned = (
            "schedule visit",
            "schedule school",
            "start activity",
            "upload evidence",
            "enter sf",
            "my plan",
        )
        for q in d["quick_actions"]:
            text = (q["label"] + " " + q["helper"]).lower()
            self.assertFalse(any(b in text for b in banned), q["label"])
        for c in d["leadership_attention"]:
            self.assertFalse(any(b in c["action"].lower() for b in banned), c["action"])

    # 3 ─ KPIs dynamic
    def test_cd_kpis_dynamic(self):
        by = self._kpis()
        self.assertEqual(
            by["Active Schools Served"]["value"], "1"
        )  # only sch_a completed
        before = by["Active Schools Served"]["value"]
        self._act(self.b1_sp.id, self.sch_b, "school_visit", "ia_verified", sf="SV-B")
        after = self._kpis()["Active Schools Served"]["value"]
        self.assertNotEqual(before, after)  # recomputed, not static

    # 4 ─ Activity SF ID compliance calculation
    def test_cd_activity_sf_id_compliance_calculation(self):
        by = self._kpis()
        # 2 completed requiring SF IDs, 1 has one → 50%.
        self.assertEqual(by["Activity SF ID Compliance"]["value"], "50%")

    # 5 ─ pending fund requests calculation
    def test_cd_pending_fund_requests_calculation(self):
        by = self._kpis()
        # 1 escalated weekly + 1 monthly budget in cd_review = 2.
        self.assertEqual(by["Pending Fund Requests"]["value"], "2")
        WeeklyFundRequest.objects.filter(id=self.wfr.id).update(
            status="confirmed_for_advance"
        )
        MonthlyWorkPlanBudget.objects.all().update(status="submitted_to_rvp")
        self.assertEqual(self._kpis()["Pending Fund Requests"]["value"], "0")

    # 6 ─ budget utilization calculation
    def test_cd_budget_utilization_calculation(self):
        by = self._kpis()
        # One advance: requested 80k, disbursed 80k → 100%.
        self.assertEqual(by["Budget Utilization"]["value"], "100%")

    # 7 ─ high-risk team detection
    def test_cd_high_risk_team_detection(self):
        d = self._dash()
        bola = next(r for r in d["pl_performance"]["rows"] if r["name"] == "PL Bola")
        # B1: 0 of 4 visit target + un-SSA'd school → high risk band.
        self.assertIn(bola["risk"], ("High Risk", "Critical"))
        by = self._kpis(d)
        self.assertGreaterEqual(int(by["High-Risk Teams"]["value"]), 1)

    # 8 ─ leadership attention from real data
    def test_cd_leadership_attention_cards_generated_from_real_data(self):
        d = self._dash()
        titles = " ".join(c["title"] for c in d["leadership_attention"])
        self.assertIn("Region", titles)  # Northern Region at 0% < threshold
        self.assertIn("Pending", titles)  # escalated fund items
        # Resolve the fund items → the card disappears.
        WeeklyFundRequest.objects.filter(id=self.wfr.id).update(
            status="confirmed_for_advance"
        )
        MonthlyWorkPlanBudget.objects.all().update(status="submitted_to_rvp")
        titles2 = " ".join(c["title"] for c in self._dash()["leadership_attention"])
        self.assertNotIn("Pending", titles2)

    # 9 ─ SSA matrix uses the backend eight interventions
    def test_cd_cluster_ssa_uses_backend_eight_interventions(self):
        d = self._dash()
        self.assertEqual(
            d["ssa_matrix"]["codes"],
            ["CB", "WOG", "FH", "Lship", "GR", "LE", "TE", "Erlm't"],
        )
        central = next(
            r for r in d["ssa_matrix"]["rows"] if r["label"] == "Central Region"
        )
        self.assertEqual(len(central["cells"]), 8)
        lship_idx = d["ssa_matrix"]["codes"].index("Lship")
        self.assertEqual(central["cells"][lship_idx]["pct"], 70.0)  # 7.0/10 → 70%

    # 10 ─ priority schools from real workflow gaps
    def test_cd_priority_school_list_generated_from_real_workflow_gaps(self):
        d = self._dash()
        rows = {p["school"]: p for p in d["priority_schools"]}
        self.assertIn("School B", rows)  # no visit+training+SSA
        self.assertIn("No SSA", rows["School B"]["issues"])
        self.assertNotIn("School A", rows)  # visited+trained+SSA done

    # 11 ─ quick actions route to real pages
    def test_cd_quick_actions_route_to_real_pages(self):
        for q in S.quick_actions():
            path = q["url"].split("?")[0]
            try:
                resolve(path)
            except Resolver404:
                self.fail(f"Quick action route does not resolve: {path}")

    # 12 ─ finance snapshot uses the finance workflow
    def test_cd_finance_snapshot_uses_finance_workflow(self):
        d = self._dash()
        fs = d["finance_snapshot"]
        self.assertEqual(fs["pending_count"], 1)
        self.assertEqual(fs["pending_rows"][0]["team"], "PL Ada")
        self.assertEqual(fs["pending_rows"][0]["stage"], "CD Review")
        fnc = fs["funded_not_completed"]
        self.assertEqual(fnc["activities"], 1)  # disbursed, still scheduled
        self.assertEqual(fnc["amount"], "UGX 80K")
        self.assertEqual(d["budget_stage"]["label"], "In CD Review")

    # 13 ─ CD To-Dos for leadership actions
    def test_cd_todos_generated_for_leadership_actions(self):
        from apps.analytics.cd_analytics_service import CDAnalyticsService

        titles = {t["title"] for t in CDAnalyticsService.cd_todos(self.cd, fy=FY)}
        self.assertIn("Approve PL Weekly Fund Request", titles)
        WeeklyFundRequest.objects.filter(id=self.wfr.id).update(
            status="confirmed_for_advance"
        )
        titles2 = {t["title"] for t in CDAnalyticsService.cd_todos(self.cd, fy=FY)}
        self.assertNotIn("Approve PL Weekly Fund Request", titles2)  # auto-closes

    # HTTP smoke — command center renders with the executive sections.
    def test_command_center_renders_over_http(self):
        c = Client()
        c.force_login(self.cd)
        resp = c.get("/dashboard")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        for marker in (
            "Country Target Progress",
            "Activity SF ID Compliance",
            "Regional Performance",
            "Funded Not Completed",
            "Quick Leadership Actions",
        ):
            self.assertIn(marker, body)


class CDTargetCreditConvergenceTest(TestCase):
    """Regression coverage for the 'did this activity earn target credit'
    divergence: the KPI strip's Country Target Progress and the PL
    performance table's per-row target % must read the SAME validated-
    ledger + weighted-area math, and that ledger must never be stale
    (mandate: CD/RVP-level rollups must trigger their own rebuild, exactly
    like My/Team Targets already do on page load).

    Single PL supervising a single CCEO — country scope and the PL's team
    scope are identical, so the KPI and the row are provably the same
    number under the fix (and were NOT under the old, independent
    unweighted-StaffTargetProfile per-row computation)."""

    def setUp(self):
        self.region = Region.objects.create(name="Solo Region")
        self.district = District.objects.create(
            name="Solo District", region=self.region, district_type="primary"
        )
        self.cd, _ = self._staff(
            "cd-solo@t.org", "CD Solo", EdifyRole.COUNTRY_DIRECTOR.value
        )
        self.pl, self.pl_sp = self._staff(
            "pl-solo@t.org", "PL Solo", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.cceo, self.cceo_sp = self._staff(
            "cceo-solo@t.org", "CCEO Solo", EdifyRole.CCEO.value
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_sp, supervisee=self.cceo_sp
        )
        self.school = School.objects.create(
            school_id="S-SOLO",
            name="Solo School",
            region=self.region,
            district=self.district,
            current_fy_ssa_status="done",
        )
        StaffSchoolAssignment.objects.create(
            staff=self.cceo_sp, school_id=self.school.id
        )
        StaffTargetProfile.objects.create(staff=self.cceo_sp, fy=FY, visits_target=4)
        # 2 completed visits with an Activity SF ID (validated) + 1 without
        # (provisional — must never silently count, unlike the old raw
        # completed-status count which counted all 3).
        self._act(
            self.cceo_sp.id, self.school, "school_visit", "ia_verified", sf="SV-1"
        )
        self._act(
            self.cceo_sp.id, self.school, "school_visit", "ia_verified", sf="SV-2"
        )
        self._act(self.cceo_sp.id, self.school, "school_visit", "completed", sf="")

    def _staff(self, email, name, role):
        u = User.objects.create_user(
            email=email,
            name=name,
            roles=[role],
            active_role=role,
            password="x",
            is_active=True,
        )
        return u, StaffProfile.objects.create(user=u, title=role)

    def _act(self, sp_id, school, atype, status, sf=""):
        return Activity.objects.create(
            school=school,
            activity_type=atype,
            delivery_type="staff",
            status=status,
            responsible_staff_id=sp_id,
            fy=FY,
            quarter="Q3",
            planned_date=date(2026, 4, 10),
            scheduled_date=timezone.make_aware(timezone.datetime(2026, 4, 10, 9, 0)),
            salesforce_activity_id=sf,
        )

    def test_kpi_strip_and_pl_row_agree_and_ledger_is_never_stale(self):
        from apps.targets.models import TargetAchievementLedger

        # Never called TargetAchievementService.rebuild() manually — the
        # ledger starts empty for this CCEO.
        self.assertFalse(
            TargetAchievementLedger.objects.filter(user_id=self.cceo.id).exists()
        )

        d = S.get_dashboard(self.cd, fy=FY)

        # (b) the dashboard read must have triggered its own rebuild.
        self.assertTrue(
            TargetAchievementLedger.objects.filter(
                user_id=self.cceo.id, fy=FY, validation_status="validated"
            ).exists()
        )

        # (a) the KPI strip and the PL row now read the identical math for
        # the identical (single-PL, single-CCEO) scope, so they must match
        # exactly — not just be close.
        kpi = {k["label"]: k["value"] for k in d["kpi_strip_items"]}
        row = next(r for r in d["pl_performance"]["rows"] if r["name"] == "PL Solo")
        self.assertEqual(kpi["Country Target Progress"], f"{row['target_pct']}%")
        # 2 validated of 4 targeted visits → 50%; a raw completed-status
        # count (the old per-row method) would have silently counted the
        # SF-ID-less third visit too and shown 75%.
        self.assertEqual(row["target_pct"], 50)
        self.assertEqual(kpi["Country Target Progress"], "50%")

    def test_cd_analytics_kpi_and_pl_oversight_row_agree(self):
        """Same convergence, on the CD Analytics cockpit (/analytics/country-
        director) — the other page the mandate calls out as showing two
        different numbers on one page."""
        from apps.analytics.cd_analytics_service import CDAnalyticsService

        d = CDAnalyticsService.get_dashboard(self.cd, fy=FY)
        kpi = {k["label"]: k["value"] for k in d["kpi_strip_items"]}
        row = next(r for r in d["pl_oversight"]["rows"] if r["name"] == "PL Solo")
        self.assertEqual(kpi["Overall Target Achievement"], f"{row['target_pct']}%")
        self.assertEqual(row["target_pct"], 50)
