"""Program Lead Analytics — role-scope + correctness tests (mandate §24).

A two-PL fixture proves strict isolation: PL-A supervises CCEO-A1 (schools in
District-A / Cluster-A); PL-B supervises CCEO-B1 (District-B). Nothing of PL-B's
portfolio may ever surface for PL-A, in any section, KPI, table, export, or
To-Do. SSA uses annual verified cycles; the risk list derives from real
workflow state.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    StaffTargetProfile,
)
from apps.activities.models import Activity
from apps.analytics.pl_analytics_service import PLAnalyticsService, resolve_pl_scope
from apps.clusters.models import Cluster
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

User = get_user_model()

INTERVENTIONS = [
    "christlike_behaviour",
    "exposure_to_word_of_god",
    "financial_health",
    "leadership",
    "learning_environment",
    "government_requirement",
    "teaching_environment",
    "enrolment",
]
FY = "2026"
PREV_FY = "2025"


class PLAnalyticsTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Region X")
        self.dist_a = District.objects.create(name="District A", region=self.region)
        self.dist_b = District.objects.create(name="District B", region=self.region)
        self.cluster_a = Cluster.objects.create(
            id="cl-a", name="Cluster A", region=self.region, district=self.dist_a
        )

        # PL-A supervises CCEO-A1; PL-B supervises CCEO-B1.
        self.pl_a, self.pl_a_sp = self._staff(
            "pla@t.org", "PL Alpha", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.cceo_a1, self.cceo_a1_sp = self._staff(
            "a1@t.org", "Ann A1", EdifyRole.CCEO.value
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_a_sp, supervisee=self.cceo_a1_sp
        )

        self.pl_b, self.pl_b_sp = self._staff(
            "plb@t.org", "PL Beta", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.cceo_b1, self.cceo_b1_sp = self._staff(
            "b1@t.org", "Ben B1", EdifyRole.CCEO.value
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_b_sp, supervisee=self.cceo_b1_sp
        )

        # Schools — A portfolio (core + client + champion), B portfolio (one).
        self.sch_a1 = self._school("A1", self.dist_a, stype="core")
        self.sch_a2 = self._school("A2", self.dist_a, stype="client", ssa_done=False)
        self.sch_a3 = self._school("A3", self.dist_a, stype="champion")
        self.sch_b1 = self._school("B1", self.dist_b, stype="core")
        # Assign cluster via update() — School.save() auto-nulls cluster_id when
        # the school's sub_county isn't covered by the cluster.
        School.objects.filter(
            id__in=[self.sch_a1.id, self.sch_a2.id, self.sch_a3.id]
        ).update(cluster_id="cl-a", cluster_status="clustered")

        StaffSchoolAssignment.objects.create(
            staff=self.cceo_a1_sp, school_id=self.sch_a1.id
        )
        StaffSchoolAssignment.objects.create(
            staff=self.cceo_a1_sp, school_id=self.sch_a2.id
        )
        StaffSchoolAssignment.objects.create(
            staff=self.cceo_a1_sp, school_id=self.sch_a3.id
        )
        StaffSchoolAssignment.objects.create(
            staff=self.cceo_b1_sp, school_id=self.sch_b1.id
        )

        # Annual SSA cycles: A1 improves 5.0 → 7.0; A3 (champion) 6.0 → 8.0.
        self._ssa(self.sch_a1, PREV_FY, 5.0)
        self._ssa(self.sch_a1, FY, 7.0)
        self._ssa(self.sch_a3, PREV_FY, 6.0)
        self._ssa(self.sch_a3, FY, 8.0)
        self._ssa(self.sch_b1, FY, 9.0)  # B's SSA must never surface for A
        # An UNVERIFIED SSA for A2 must be ignored by the annual-cycle logic.
        self._ssa(self.sch_a2, FY, 9.9, status="pending")

        # Activities — A1 completes a visit + a training (+partner) on A-schools;
        # B1 completes work on B1 (must never count for PL-A).
        self._activity(self.cceo_a1_sp.id, self.sch_a1, "school_visit", "staff")
        self._activity(
            self.cceo_a1_sp.id, self.sch_a1, "training", "staff", teachers=10, leaders=2
        )
        self.partner = Partner.objects.create(name="Partner P")
        self._activity(
            self.cceo_a1_sp.id,
            self.sch_a1,
            "partner_activity",
            "partner",
            partner_id=self.partner.id,
        )
        PartnerAssignment.objects.create(
            cluster=self.cluster_a,
            partner=self.partner,
            assigning_staff_id=self.cceo_a1_sp.id,
        )
        self._activity(self.cceo_b1_sp.id, self.sch_b1, "school_visit", "staff")

        # Targets for A1 (so target achievement is meaningful).
        StaffTargetProfile.objects.create(
            staff=self.cceo_a1_sp,
            fy=FY,
            visits_target=2,
            trainings_target=1,
            cluster_meetings_target=1,
            ssa_target=1,
        )

    # ── fixture helpers ──────────────────────────────────────────────────────
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

    def _school(self, sid, district, stype="client", ssa_done=True):
        return School.objects.create(
            school_id=f"SCH-{sid}",
            name=f"School {sid}",
            region=self.region,
            district=district,
            school_type=stype,
            enrollment=100,
            current_fy_ssa_status="done" if ssa_done else "not_done",
        )

    def _ssa(self, school, fy, avg, status="confirmed"):
        rec = SsaRecord.objects.create(
            school=school,
            date_of_ssa=timezone.now(),
            fy=fy,
            quarter="Q2",
            average_score=avg,
            verification_status=status,
        )
        for i in INTERVENTIONS:
            SsaScore.objects.create(ssa_record=rec, intervention=i, score=avg)
        return rec

    def _activity(
        self,
        responsible_sp_id,
        school,
        atype,
        delivery,
        teachers=0,
        leaders=0,
        partner_id=None,
    ):
        return Activity.objects.create(
            school=school,
            activity_type=atype,
            delivery_type=delivery,
            status="completed",
            responsible_staff_id=responsible_sp_id,
            assigned_partner_id=partner_id,
            fy=FY,
            quarter="Q3",
            planned_date=date(2026, 4, 10),
            scheduled_date=timezone.make_aware(timezone.datetime(2026, 4, 10, 9, 0)),
            evidence_status="accepted",
            teachers_attended=teachers,
            leaders_attended=leaders,
        )

    def _dash(self, user, **kw):
        return PLAnalyticsService.get_dashboard(user, fy=FY, **kw)

    # ── 1. scope: only supervised CCEOs ──────────────────────────────────────
    def test_pl_analytics_scope_only_supervised_cceos(self):
        scope = resolve_pl_scope(self.pl_a)
        ids = {c["staff_id"] for c in scope.cceos}
        self.assertEqual(ids, {self.cceo_a1_sp.id})
        self.assertNotIn(self.cceo_b1_sp.id, ids)

    # ── 2. cannot see another PL's data ──────────────────────────────────────
    def test_pl_cannot_see_other_pl_data(self):
        scope = resolve_pl_scope(self.pl_a)
        self.assertIn(self.sch_a1.id, scope.school_ids)
        self.assertNotIn(self.sch_b1.id, scope.school_ids)
        d = self._dash(self.pl_a)
        risk_names = {r["school"] for r in d["risk_list"]["rows"]}
        self.assertNotIn("School B1", risk_names)

    # ── 3. KPIs use the supervised portfolio ─────────────────────────────────
    def test_pl_kpis_use_supervised_portfolio(self):
        d = self._dash(self.pl_a)
        by_label = {k["label"]: k["value"] for k in d["kpi_strip_items"]}
        self.assertEqual(by_label["Schools Assigned to Team"], "3")  # A1,A2,A3 — not B1
        # Activities completed: A1's 3 activities, not B1's.
        self.assertEqual(by_label["Activities Completed"], "3")

    # ── 3b. Team execution % must never collide with the canonical Team
    # Targets label — a PL/CD would otherwise see "Team Target Achievement"
    # mean two different numbers (raw field execution here vs the IA-verified
    # weighted ledger % on the Team Targets page) in one session.
    def test_team_execution_kpi_label_does_not_collide_with_canonical_team_targets_label(
        self,
    ):
        d = self._dash(self.pl_a)
        labels = {k["label"] for k in d["kpi_strip_items"]}
        self.assertIn("Team Execution Progress %", labels)
        self.assertNotIn("Team Target Achievement %", labels)
        self.assertNotIn("Team Target Achievement", labels)

    # ── 4. SSA uses the latest verified ANNUAL cycle ─────────────────────────
    def test_pl_ssa_intervention_uses_latest_verified_annual_ssa(self):
        d = self._dash(self.pl_a)
        ssa = d["ssa_interventions"]
        self.assertTrue(ssa["has_data"])
        self.assertEqual(ssa["latest_fy"], FY)
        self.assertEqual(ssa["prev_fy"], PREV_FY)
        # Latest cycle avg across A1(7.0)+A3(8.0) = 7.5 → 75%; prev 5.0+6.0=5.5 → 55%; Δ +20.
        row = ssa["rows"][0]
        self.assertAlmostEqual(row["pct"], 75.0, places=1)
        self.assertAlmostEqual(row["delta"], 20.0, places=1)
        # The unverified A2 SSA (9.9) must NOT inflate the average.
        self.assertLess(row["pct"], 90)

    # ── 5. district performance scoped ───────────────────────────────────────
    def test_pl_district_performance_scoped(self):
        d = self._dash(self.pl_a)
        names = {r["name"] for r in d["district_performance"]["rows"]}
        self.assertEqual(names, {"District A"})
        self.assertNotIn("District B", names)

    # ── 6. cluster performance scoped ────────────────────────────────────────
    def test_pl_cluster_performance_scoped(self):
        d = self._dash(self.pl_a)
        rows = d["cluster_performance"]["rows"]
        self.assertEqual([r["name"] for r in rows], ["Cluster A"])

    # ── 7. CCEO performance only supervised CCEOs ────────────────────────────
    def test_pl_cceo_performance_only_supervised_cceos(self):
        d = self._dash(self.pl_a)
        names = {r["name"] for r in d["cceo_performance"]["rows"]}
        self.assertEqual(names, {"Ann A1"})
        self.assertNotIn("Ben B1", names)
        row = d["cceo_performance"]["rows"][0]
        self.assertTrue(row["has_target"])

    # ── 8. risk list from real workflow state ────────────────────────────────
    def test_pl_risk_list_generated_from_real_workflow_states(self):
        d = self._dash(self.pl_a)
        rows = {r["school"]: r for r in d["risk_list"]["rows"]}
        # A2 has no verified SSA (current_fy_ssa_status != done) and no visit → at risk.
        self.assertIn("School A2", rows)
        self.assertIn("No SSA", rows["School A2"]["issue"])
        # A1 was visited + SSA done → not flagged as No SSA/Not Visited.
        self.assertNotIn("School A1", rows)

    # ── 9. partner performance scoped ────────────────────────────────────────
    def test_pl_partner_performance_scoped(self):
        d = self._dash(self.pl_a)
        sp = d["staff_partner"]
        idx = sp["labels"].index("Activities")
        # A1's partner activity counts once for A; B's work never appears.
        self.assertEqual(sp["partner"][idx], 1)
        self.assertEqual(sp["staff"][idx], 2)  # visit + training (partner excluded)

    # ── 10. core & champion scoped ───────────────────────────────────────────
    def test_pl_core_champion_metrics_scoped(self):
        d = self._dash(self.pl_a)
        cc = d["core_champion"]
        self.assertEqual(cc["core"]["count"], 1)  # School A1 only (not B1)
        self.assertEqual(cc["champion"]["count"], 1)  # School A3
        # Champion annual trend rises 6.0→8.0 (60%→80%).
        self.assertEqual(cc["champion"]["series"], [60.0, 80.0])

    # ── 11. donor snapshot uses verified activity data ───────────────────────
    def test_pl_donor_snapshot_uses_verified_activity_data(self):
        d = self._dash(self.pl_a)
        m = {x["label"]: x for x in d["donor_snapshot"]["metrics"]}
        self.assertEqual(m["Teachers Trained"]["value"], "10")  # from A1's training
        self.assertEqual(m["School Leaders Trained"]["value"], "2")
        # Students impacted = enrollment of reached A-schools (A1=100), not B1.
        self.assertEqual(m["Students Impacted"]["value"], "100")

    # ── 12. export respects scope ────────────────────────────────────────────
    def test_pl_export_respects_scope(self):
        rows = PLAnalyticsService.export_rows(self.pl_a, fy=FY)
        schools = {r["school"] for r in rows}
        self.assertNotIn("School B1", schools)
        # And PL-B's export never contains A's schools.
        rows_b = PLAnalyticsService.export_rows(self.pl_b, fy=FY)
        self.assertNotIn("School A1", {r["school"] for r in rows_b})
        self.assertNotIn("School A2", {r["school"] for r in rows_b})

    # ── 13. insight creates a To-Do when a threshold is met ──────────────────
    def test_pl_insight_creates_todo_when_threshold_met(self):
        # A2 has no SSA → the schools-without-SSA threshold is met.
        todos = PLAnalyticsService.pl_todos(self.pl_a, fy=FY)
        titles = {t["title"] for t in todos}
        self.assertIn("Schedule SSA Collection", titles)

        # And it surfaces through the real To-Do queue for the PL.
        from apps.command_center.todo_service import get_todos

        class _P:
            def __init__(self, u):
                self.user_id = u.id
                self.active_role = u.active_role
                self.staff_profile_id = StaffProfile.objects.get(user=u).id

        queue = get_todos(_P(self.pl_a))
        self.assertTrue(any(t["source"] == "PL Analytics" for t in queue["todos"]))

        # When every school has verified SSA, no SSA-collection To-Do is emitted.
        School.objects.filter(
            id__in=[self.sch_a1.id, self.sch_a2.id, self.sch_a3.id]
        ).update(current_fy_ssa_status="done")
        titles2 = {t["title"] for t in PLAnalyticsService.pl_todos(self.pl_a, fy=FY)}
        self.assertNotIn("Schedule SSA Collection", titles2)
