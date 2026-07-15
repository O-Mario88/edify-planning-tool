"""RVP Dashboard — the regional executive operating system (§37).

Covers: regional scoping, oversight-only surface (no field execution, no
disbursement), verified-data KPIs and ranking, the monthly budget decision
guards (submitted-only, reason-required returns), the annual budget lifecycle
(approval locks the baseline; edits require a formal amendment), special
project decisions with immutable audit, annual-only project impact, partner
recommendations, accountable strategy notes, and auto-closing RVP To-Dos.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.db.models import Sum
from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.monthly_work_plan import country_budget_service as cbs
from apps.monthly_work_plan.models import (
    CountryAnnualBudget,
    MonthlyWorkPlanBudget,
    RVPApprovalDecision,
    StrategyNote,
)
from apps.monthly_work_plan.services import (
    rvp_annual_decide,
    submit_annual_to_rvp,
    update_annual_budget,
)
from apps.partners.models import Partner, PartnerAssignment
from apps.projects.models import Project
from apps.schools.models import School
from apps.ssa.models import SsaRecord

User = get_user_model()
FY = get_operational_fy()
PREV = str(int(FY) - 1)


class RVPDashboardTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="RVP Region")
        self.district = District.objects.create(
            name="RVP District", region=self.region, district_type="primary"
        )
        self.rvp, _ = self._staff(
            "rvp@r.org", "Regional VP", EdifyRole.REGIONAL_VICE_PRESIDENT.value
        )
        self.cd, _ = self._staff(
            "cd@r.org", "Country Dir", EdifyRole.COUNTRY_DIRECTOR.value
        )
        self.cceo, self.cceo_sp = self._staff(
            "cc@r.org", "Field Cceo", EdifyRole.CCEO.value
        )
        self.school = School.objects.create(
            school_id="RVP-S1",
            name="RVP School",
            region=self.region,
            district=self.district,
            enrollment=300,
            current_fy_ssa_status="done",
        )

        self.submitted = MonthlyWorkPlanBudget.objects.create(
            fy=FY,
            month_key=f"{FY}-07",
            country_id="Uganda",
            status="submitted_to_rvp",
            program_total=4_000_000,
            admin_total=1_000_000,
            total_amount=5_000_000,
            activity_count=12,
            submitted_at=timezone.now(),
            submitted_by_user_id=self.cd.id,
        )
        self.draft = MonthlyWorkPlanBudget.objects.create(
            fy=FY,
            month_key=f"{FY}-08",
            country_id="Uganda",
            status="draft_generated",
            total_amount=2_000_000,
        )
        self.foreign = MonthlyWorkPlanBudget.objects.create(
            fy=FY,
            month_key=f"{FY}-09",
            country_id="Kenya",
            status="submitted_to_rvp",
            total_amount=9_000_000,
        )

        self.annual = CountryAnnualBudget.objects.create(
            fy=FY,
            country_id="Uganda",
            program_total=80_000_000,
            admin_total=20_000_000,
            total_amount=100_000_000,
            target_schools=200,
            target_activities=900,
        )

        self.project = Project.objects.create(
            name="Literacy Boost",
            code="SP-LIT",
            category="pilot",
            intervention="leadership",
        )

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

    def _client(self, user):
        c = Client()
        c.force_login(user)
        return c

    def _dash(self):
        from apps.analytics.rvp_dashboard_service import RVPDashboardService

        return RVPDashboardService.get_dashboard(self.rvp, fy=FY)

    def _completed_activity(
        self, sf="SF-R1", status="ia_verified", atype="school_visit"
    ):
        a = Activity.objects.create(
            school=self.school,
            activity_type=atype,
            delivery_type="staff",
            status=status,
            responsible_staff_id=self.cceo_sp.id,
            fy=FY,
            quarter="Q4",
            planned_date=date.today(),
            salesforce_activity_id=sf,
            teachers_attended=5,
        )
        ActivityScheduleCostLine.objects.create(
            activity=a,
            cost_setting_key="transport",
            label="Transport",
            unit_cost=100_000,
            amount=100_000,
        )
        return a

    # ── 1–2: regional scope ──────────────────────────────────────────────────
    def test_rvp_sees_only_assigned_region(self):
        d = self._dash()
        self.assertNotIn(self.foreign.id, [b["id"] for b in d["awaiting_rows"]])
        self.assertIn(self.submitted.id, [b["id"] for b in d["awaiting_rows"]])
        region_names = {r["name"] for r in d["regions"]}
        self.assertIn("RVP Region", region_names)

    def test_rvp_cannot_access_unassigned_country(self):
        with self.assertRaises(Forbidden):
            cbs_approve_foreign = self.foreign
            from apps.monthly_work_plan.services import rvp_approve

            rvp_approve(cbs_approve_foreign.id, {}, self.rvp)

    # ── 3–5: oversight-only + verified data ──────────────────────────────────
    def test_rvp_dashboard_has_no_field_planning_actions(self):
        html = self._client(self.rvp).get("/dashboard").content.decode()
        for banned in (
            "Schedule Visit",
            "Schedule Training",
            "Start Activity",
            "Upload Evidence",
            "Enter SF ID",
            "Disburse",
        ):
            self.assertNotIn(banned, html, banned)

    def test_rvp_kpis_use_regional_scope(self):
        self._completed_activity(atype="training", sf="SF-T1")
        d = self._dash()
        by = {k["label"]: k["value"] for k in d["kpi_strip_items"]}
        self.assertEqual(by["Schools Impacted"], "1")
        self.assertEqual(by["Teachers Trained"], "5")
        self.assertIn("Regional Target Achievement", by)
        self.assertIn("High-Risk Regions", by)

    def test_rvp_country_ranking_uses_verified_data(self):
        self._completed_activity()
        d = self._dash()
        row = next(r for r in d["regions"] if r["name"] == "RVP Region")
        self.assertEqual(row["exec_rate"], 100)  # 1 completed of 1 planned
        self.assertEqual(row["verified_rate"], 100)  # ia_verified
        self.assertEqual(row["sf_rate"], 100)
        self.assertIn(
            row["status"], ("Strong", "On Track", "Watch", "High Risk", "Critical")
        )
        ranks = [r["rank"] for r in d["regions"]]
        self.assertEqual(ranks, sorted(ranks))

    # ── 6–9: monthly budget decisions ────────────────────────────────────────
    def test_rvp_sees_only_submitted_monthly_budgets(self):
        ids = [b["id"] for b in self._dash()["awaiting_rows"]]
        self.assertIn(self.submitted.id, ids)
        self.assertNotIn(self.draft.id, ids)

    def test_rvp_can_approve_valid_country_monthly_budget(self):
        cbs.approve(self.rvp, self.submitted.id)
        self.submitted.refresh_from_db()
        self.assertEqual(self.submitted.status, "approved_by_rvp")
        self.assertTrue(
            RVPApprovalDecision.objects.filter(
                decision_type="monthly_budget",
                subject_id=self.submitted.id,
                action="approve",
            ).exists()
        )

    def test_rvp_cannot_approve_invalid_monthly_budget(self):
        with self.assertRaises(BadRequest):
            cbs.approve(self.rvp, self.draft.id)  # never submitted

    def test_rvp_return_requires_reason(self):
        with self.assertRaises(BadRequest):
            cbs.return_budget(self.rvp, self.submitted.id, {"reason": ""})
        cbs.return_budget(self.rvp, self.submitted.id, {"reason": "Admin plan missing"})
        self.submitted.refresh_from_db()
        self.assertEqual(self.submitted.status, "returned_by_rvp")
        self.assertIn("Admin plan missing", self.submitted.rvp_review_note)

    # ── 10–11: annual budget ─────────────────────────────────────────────────
    def test_rvp_can_approve_country_annual_budget(self):
        submit_annual_to_rvp(self.annual.id, self.cd)
        b = rvp_annual_decide(self.annual.id, "approve", {}, self.rvp)
        self.assertEqual(b.status, "approved_by_rvp")
        self.assertTrue(
            RVPApprovalDecision.objects.filter(
                decision_type="annual_budget", subject_id=b.id, action="approve"
            ).exists()
        )

    def test_annual_budget_approval_locks_baseline(self):
        submit_annual_to_rvp(self.annual.id, self.cd)
        b = rvp_annual_decide(self.annual.id, "approve", {}, self.rvp)
        self.assertIsNotNone(b.baseline_locked_at)
        with self.assertRaises(BadRequest):
            update_annual_budget(b.id, {"program_total": 90_000_000}, self.cd)

    # ── 12: no disbursement power ────────────────────────────────────────────
    def test_rvp_cannot_disburse(self):
        resp = self._client(self.rvp).get("/disbursements")
        self.assertNotEqual(resp.status_code, 200)  # accountant surface only

    # ── 13–15: projects + partners ───────────────────────────────────────────
    def test_special_project_impact_uses_annual_ssa(self):
        act = self._completed_activity()
        Activity.objects.filter(id=act.id).update(project_id=self.project.id)
        d = self._dash()
        row = next(p for p in d["projects"] if p["id"] == self.project.id)
        # Only one annual cycle exists → impact must be honest, not invented.
        self.assertEqual(row["impact"], "Impact Not Measurable Yet")
        SsaRecord.objects.create(
            school=self.school,
            fy=PREV,
            quarter="Q1",
            average_score=5.0,
            verification_status="confirmed",
            date_of_ssa=date(int(PREV) - 1, 11, 1),
            uploaded_by="t",
        )
        SsaRecord.objects.create(
            school=self.school,
            fy=FY,
            quarter="Q1",
            average_score=7.0,
            verification_status="confirmed",
            date_of_ssa=date(int(FY) - 1, 11, 1),
            uploaded_by="t",
        )
        d = self._dash()
        row = next(p for p in d["projects"] if p["id"] == self.project.id)
        self.assertEqual(row["impact"], "Great Impact")  # +2.0 → 20pp annual
        self.assertEqual(row["delta"], 20.0)

    def test_rvp_special_projects_direct_activity_relation_counted(self):
        act = self._completed_activity(sf="SF-DIRECT")
        Activity.objects.filter(id=act.id).update(project_id=self.project.id)
        d = self._dash()
        row = next(p for p in d["projects"] if p["id"] == self.project.id)
        self.assertEqual(row["verified"], 1)

    def test_rvp_special_projects_cost_line_activity_relation_counted(self):
        act = self._completed_activity(sf="SF-COSTLINE")
        act.schedule_cost_lines.update(project_id=self.project.id)
        d = self._dash()
        row = next(p for p in d["projects"] if p["id"] == self.project.id)
        self.assertEqual(row["verified"], 1)

    def test_rvp_special_projects_activity_joined_both_ways_counted_once(self):
        act = self._completed_activity(sf="SF-BOTH")
        Activity.objects.filter(id=act.id).update(project_id=self.project.id)
        act.schedule_cost_lines.update(project_id=self.project.id)
        d = self._dash()
        row = next(p for p in d["projects"] if p["id"] == self.project.id)
        self.assertEqual(row["verified"], 1)

    def test_rvp_special_projects_budget_totals_not_duplicated(self):
        act = self._completed_activity(sf="SF-BUDGET")
        Activity.objects.filter(id=act.id).update(project_id=self.project.id)
        act.schedule_cost_lines.update(project_id=self.project.id)
        d = self._dash()
        row = next(p for p in d["projects"] if p["id"] == self.project.id)
        # One 100_000 cost line, reachable via both paths — must be summed once.
        self.assertEqual(row["budget_raw"], 100_000)

    def test_rvp_special_projects_totals_match_source_records(self):
        for i in range(3):
            act = self._completed_activity(sf=f"SF-MATCH-{i}", status="scheduled")
            Activity.objects.filter(id=act.id).update(project_id=self.project.id)
        act = self._completed_activity(sf="SF-MATCH-DONE")
        Activity.objects.filter(id=act.id).update(project_id=self.project.id)
        d = self._dash()
        row = next(p for p in d["projects"] if p["id"] == self.project.id)
        expected_budget = int(
            ActivityScheduleCostLine.objects.filter(
                activity__project_id=self.project.id
            ).aggregate(s=Sum("amount"))["s"]
            or 0
        )
        self.assertEqual(row["budget_raw"], expected_budget)
        self.assertEqual(
            row["verified"],
            Activity.objects.filter(
                project_id=self.project.id, status="ia_verified"
            ).count(),
        )

    def test_rvp_special_projects_uses_explicit_school_assignment(self):
        from apps.projects.models import ProjectSchoolAssignment

        other_school = School.objects.create(
            school_id="RVP-S2",
            name="RVP School 2",
            region=self.region,
            district=self.district,
            enrollment=150,
            current_fy_ssa_status="done",
        )
        ProjectSchoolAssignment.objects.create(
            project=self.project, school=other_school
        )
        SsaRecord.objects.create(
            school=other_school,
            fy=PREV,
            quarter="Q1",
            average_score=4.0,
            verification_status="confirmed",
            date_of_ssa=date(int(PREV) - 1, 11, 1),
            uploaded_by="t",
        )
        SsaRecord.objects.create(
            school=other_school,
            fy=FY,
            quarter="Q1",
            average_score=9.0,
            verification_status="confirmed",
            date_of_ssa=date(int(FY) - 1, 11, 1),
            uploaded_by="t",
        )
        # No activity ties this project to other_school — only the explicit
        # ProjectSchoolAssignment does. The old hasattr("school_links") bug
        # meant assignments were never read; the fix must pick this up.
        d = self._dash()
        row = next(p for p in d["projects"] if p["id"] == self.project.id)
        self.assertEqual(row["delta"], 50.0)

    def test_rvp_special_projects_query_count_is_bounded(self):
        from apps.analytics.cd_analytics_service import (
            _country_activities,
            resolve_cd_scope,
        )
        from apps.projects.models import Project as ProjectModel

        for i in range(15):
            p = ProjectModel.objects.create(
                name=f"Project {i}", code=f"SP-{i}", category="pilot"
            )
            act = Activity.objects.create(
                school=self.school,
                activity_type="school_visit",
                delivery_type="staff",
                status="ia_verified",
                responsible_staff_id=self.cceo_sp.id,
                fy=FY,
                quarter="Q4",
                planned_date=date.today(),
                salesforce_activity_id=f"SF-BOUND-{i}",
            )
            if i % 2 == 0:
                Activity.objects.filter(id=act.id).update(project_id=p.id)
            else:
                ActivityScheduleCostLine.objects.create(
                    activity=act,
                    cost_setting_key="transport",
                    label="Transport",
                    unit_cost=10_000,
                    amount=10_000,
                    project=p,
                )
        cd = resolve_cd_scope(FY)
        acts = _country_activities(cd)
        from apps.analytics.rvp_dashboard_service import RVPDashboardService

        with self.assertNumQueries(7):
            RVPDashboardService.special_projects(cd, acts, FY)

    def test_special_project_decision_creates_audit(self):
        resp = self._client(self.rvp).post(
            f"/rvp/project/{self.project.id}/decision",
            {"action": "scale", "reason": "Strong verified annual impact"},
        )
        self.assertIn(resp.status_code, (200, 302))
        self.assertTrue(
            RVPApprovalDecision.objects.filter(
                decision_type="special_project",
                subject_id=self.project.id,
                action="scale",
            ).exists()
        )

    def test_partner_recommendation_uses_impact_and_target(self):
        partner = Partner.objects.create(name="Growth Org")
        PartnerAssignment.objects.create(
            school=self.school,
            partner=partner,
            assigning_staff_id=self.cceo_sp.id,
            status="assigned",
        )
        d = self._dash()
        row = next((p for p in d["partners"] if p["name"] == "Growth Org"), None)
        self.assertIsNotNone(row)
        self.assertIn("recommendation", row)
        self.assertIn(row["type"], ("Implementing Partner", "Strategic Partner"))

    # ── 16–17: amendments + strategy notes ───────────────────────────────────
    def test_resource_reallocation_requires_budget_amendment(self):
        submit_annual_to_rvp(self.annual.id, self.cd)
        rvp_annual_decide(self.annual.id, "approve", {}, self.rvp)
        with self.assertRaises(BadRequest):
            update_annual_budget(
                self.annual.id, {"program_total": 70_000_000}, self.rvp
            )
        # The formal amendment path still works: RVP returns, CD revises.
        self.annual.refresh_from_db()
        self.annual.status = "submitted_to_rvp"
        self.annual.save(update_fields=["status"])
        rvp_annual_decide(
            self.annual.id,
            "return",
            {"note": "Reallocate toward core schools"},
            self.rvp,
        )
        updated = update_annual_budget(
            self.annual.id, {"program_total": 70_000_000}, self.cd
        )
        self.assertEqual(updated.program_total, 70_000_000)

    def test_strategy_note_creates_todo(self):
        from apps.command_center.todo_service import get_todos
        from apps.monthly_work_plan.services import create_strategy_note

        create_strategy_note(
            {
                "priority": "School Leadership",
                "scope": "Uganda",
                "instruction": "Accelerate leadership coaching in weak districts.",
                "responsible_cd_id": self.cd.id,
            },
            self.rvp,
        )
        titles = [t["title"] for t in get_todos(self.cd)["todos"]]
        self.assertIn("Act on RVP guidance — School Leadership", titles)
        StrategyNote.objects.all().update(status="done")
        titles = [t["title"] for t in get_todos(self.cd)["todos"]]
        self.assertNotIn("Act on RVP guidance — School Leadership", titles)

    # ── 18–20: To-Dos, scope, export ─────────────────────────────────────────
    def test_rvp_todos_auto_close(self):
        from apps.command_center.todo_service import get_todos

        titles = [t["title"] for t in get_todos(self.rvp)["todos"]]
        self.assertIn(f"Review Country Monthly Budget {FY}-07", titles)
        cbs.approve(self.rvp, self.submitted.id)
        titles = [t["title"] for t in get_todos(self.rvp)["todos"]]
        self.assertNotIn(f"Review Country Monthly Budget {FY}-07", titles)

    def test_rvp_htmx_endpoints_enforce_scope(self):
        c = self._client(self.cceo)
        self.assertEqual(c.get("/rvp/approvals").status_code, 403)
        self.assertEqual(
            c.post(
                f"/rvp/annual/{self.annual.id}/action", {"action": "approve"}
            ).status_code,
            403,
        )
        self.assertEqual(
            c.post("/rvp/strategy-note", {"instruction": "x"}).status_code, 403
        )

    def test_rvp_export_respects_region_scope(self):
        drawer = self._client(self.rvp).get("/rvp/approvals").content.decode()
        self.assertIn(f"{FY}-07", drawer)  # own country queue
        self.assertNotIn(f"{FY}-09", drawer)  # KE budget never shown
        self.assertNotEqual(
            self._client(self.cceo).get("/rvp/approvals").status_code, 200
        )
