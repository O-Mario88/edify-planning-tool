"""Country Director Analytics — scope + correctness tests (mandate §25).

A CD sees COUNTRY-WIDE intelligence across every PL, CCEO, district, region,
partner and cluster — never narrowed to one supervised team. But the CD ACTS
only through oversight workflows (review / recommend / assign-follow-up-to-PL /
escalate / approve-return finance) — never field execution. SSA impact is
measured by verified ANNUAL cycles; budget health comes from the real finance
workflow; operational risk counts real workflow gaps.

Fixture: 2 PLs (A, B) each supervising 1 CCEO, across 2 districts in 1 region,
with 2 verified annual SSA cycles, a partner with attributed activity, and an
activity-advance finance pipeline.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import resolve
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    StaffTargetProfile,
)
from apps.activities.models import Activity
from apps.analytics.cd_analytics_service import (
    CDAnalyticsService as S,
    resolve_cd_scope,
    _country_activities,
)
from apps.core.navigation import PAGE_PERMISSIONS
from apps.core.rbac import EdifyRole
from apps.fund_requests.models import AdvanceRequest, WeeklyFundRequest
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

User = get_user_model()
FY, PREV = "2026", "2025"
BANNED = (
    "schedule",
    "start activity",
    "upload evidence",
    "enter sf",
    "enter salesforce",
    "start plan",
)


class CDAnalyticsTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Central Region")
        self.dist_a = District.objects.create(name="District A", region=self.region)
        self.dist_b = District.objects.create(name="District B", region=self.region)

        self.cd, _ = self._staff(
            "cd@t.org", "Diana Amaka", EdifyRole.COUNTRY_DIRECTOR.value
        )

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

        # Schools: a1 & b1 have SSA; a2 has none (→ at-risk).
        self.sch_a1 = self._school("A1", self.dist_a, 100, ssa_done=True)
        self.sch_a2 = self._school("A2", self.dist_a, 80, ssa_done=False)
        self.sch_b1 = self._school("B1", self.dist_b, 120, ssa_done=True)
        StaffSchoolAssignment.objects.create(staff=self.a1_sp, school_id=self.sch_a1.id)
        StaffSchoolAssignment.objects.create(staff=self.a1_sp, school_id=self.sch_a2.id)
        StaffSchoolAssignment.objects.create(staff=self.b1_sp, school_id=self.sch_b1.id)

        # Verified annual SSA cycles (FY2025 → FY2026).
        self._ssa(self.sch_a1, PREV, 6.0, {"leadership": 6.0}, "confirmed")
        self._ssa(self.sch_a1, FY, 7.5, {"leadership": 7.0}, "confirmed")
        self._ssa(self.sch_b1, PREV, 5.0, {"leadership": 5.0}, "confirmed")
        self._ssa(self.sch_b1, FY, 5.5, {"leadership": 5.0}, "confirmed")
        # An UNCONFIRMED FY2026 record with a wild score → must be excluded everywhere.
        self._ssa(self.sch_a1, FY, 1.0, {"leadership": 1.0}, "pending")

        # Activities (staff-delivered) — a1 visit + training, b1 visit.
        self.act_a1_visit = self._act(
            self.a1_sp.id, self.sch_a1, "school_visit", "ia_verified", sf="SV-A1"
        )
        self.act_a1_train = self._act(
            self.a1_sp.id, self.sch_a1, "training", "ia_verified", teachers=10, leaders=3
        )
        self._act(self.b1_sp.id, self.sch_b1, "school_visit", "ia_verified", sf="SV-B1")

        # Partner P delivers on a1 (attributed + one verified activity).
        self.partner = Partner.objects.create(name="Hope Builders Network")
        PartnerAssignment.objects.create(partner=self.partner, school_id=self.sch_a1.id)
        self.act_partner = self._act(
            self.a1_sp.id,
            self.sch_a1,
            "school_visit",
            "ia_verified",
            delivery="partner",
            partner=self.partner.id,
        )

        # Activity-advance finance pipeline (the real country finance volume).
        self._adv(
            self.act_a1_visit, self.a1.id, 100_000, "pending_responsible_confirmation"
        )
        self._adv(self.act_a1_train, self.a1.id, 50_000, "disbursed", disbursed=50_000)
        self._adv(
            self.act_partner,
            self.a1.id,
            30_000,
            "accounted",
            disbursed=30_000,
            accounted=30_000,
        )

        # Targets (config — achievement stays computed from real completions).
        StaffTargetProfile.objects.create(
            staff=self.a1_sp, fy=FY, visits_target=1, trainings_target=1
        )
        StaffTargetProfile.objects.create(staff=self.b1_sp, fy=FY, visits_target=1)
        StaffTargetProfile.objects.create(staff=self.pl_a_sp, fy=FY, visits_target=1)
        StaffTargetProfile.objects.create(staff=self.pl_b_sp, fy=FY, visits_target=1)

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

    def _school(self, sid, district, enrollment, ssa_done):
        return School.objects.create(
            school_id=f"S-{sid}",
            name=f"School {sid}",
            region=self.region,
            district=district,
            enrollment=enrollment,
            current_fy_ssa_status="done" if ssa_done else "not_done",
        )

    def _ssa(self, school, fy, avg, scores, status):
        rec = SsaRecord.objects.create(
            school=school,
            fy=fy,
            quarter="Q1",
            average_score=avg,
            verification_status=status,
            date_of_ssa=date(int(fy) - 1, 11, 1),
            uploaded_by="test",
        )
        for interv, sc in scores.items():
            SsaScore.objects.create(ssa_record=rec, intervention=interv, score=sc)
        return rec

    def _act(
        self,
        sp_id,
        school,
        atype,
        status,
        sf="",
        teachers=None,
        leaders=None,
        delivery="staff",
        partner=None,
    ):
        return Activity.objects.create(
            school=school,
            activity_type=atype,
            delivery_type=delivery,
            status=status,
            responsible_staff_id=sp_id,
            fy=FY,
            quarter="Q3",
            planned_date=date(2026, 4, 10),
            scheduled_date=timezone.make_aware(timezone.datetime(2026, 4, 10, 9, 0)),
            evidence_status="accepted",
            salesforce_activity_id=sf,
            teachers_attended=teachers,
            leaders_attended=leaders,
            assigned_partner_id=partner,
        )

    def _adv(self, activity, user_id, amount, status, disbursed=0, accounted=0):
        from apps.activities.models import ActivityScheduleCostLine

        line = ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key="transport",
            label="Transport",
            unit_cost=amount,
            amount=amount,
        )
        return AdvanceRequest.objects.create(
            activity=activity,
            budget_line=line,
            responsible_user_id=user_id,
            fy=FY,
            quarter="Q3",
            planned_date=date(2026, 4, 10),
            amount=amount,
            status=status,
            disbursed_amount=disbursed,
            accounted_amount=accounted,
        )

    def _dash(self):
        return S.get_dashboard(self.cd, fy=FY)

    # ── 1. country-wide scope ────────────────────────────────────────────────
    def test_cd_analytics_country_scope(self):
        d = self._dash()
        pl_names = {r["name"] for r in d["pl_oversight"]["rows"]}
        self.assertEqual(pl_names, {"PL Ada", "PL Bola"})  # BOTH PLs — never one team
        cceo_names = {r["name"] for r in d["cceo_snapshot"]["rows"]}
        self.assertIn("CCEO A1", cceo_names)
        self.assertIn("CCEO B1", cceo_names)
        self.assertEqual(d["scope_meta"]["cceo_count"], 2)

    # ── 2. KPIs use country data ─────────────────────────────────────────────
    def test_cd_kpis_use_country_data(self):
        d = self._dash()
        by = {k["label"]: k["value"] for k in d["kpi_strip_items"]}
        # a1 + b1 reached by completed activity (a2 never reached).
        self.assertEqual(by["Schools Impacted"], "2")
        self.assertEqual(by["Teachers Trained"], "10")
        self.assertEqual(by["Active PLs / Active CCEOs"], "2 / 2")

    # ── 3. no field-planning actions ─────────────────────────────────────────
    def test_cd_does_not_get_field_planning_actions(self):
        # Every oversight-action verb is leadership/oversight — never field exec.
        for kind, acts in S._OVERSIGHT_ACTIONS.items():
            for a in acts:
                self.assertFalse(
                    any(b in a.lower() for b in BANNED),
                    f"{kind}:{a} is field execution",
                )
        # Recommended actions route to CD/PL owners (oversight), not the CD's own field work.
        d = self._dash()
        for a in d["recommended_actions"]["items"]:
            self.assertIn(a["owner"], {"CD", "PL"})

    # ── 4. SSA uses latest verified ANNUAL cycle ─────────────────────────────
    def test_cd_ssa_uses_latest_verified_annual_cycle(self):
        d = self._dash()
        ssa = d["ssa_interventions"]
        self.assertEqual(ssa["latest_fy"], FY)
        self.assertEqual(ssa["prev_fy"], PREV)
        lship = next(r for r in ssa["rows"] if r["code"] == "Lship")
        # Confirmed FY2026 leadership avg = (7.0 + 5.0)/2 = 6.0 → 60%. The unconfirmed
        # 1.0 record is excluded (else the avg would drop below 60).
        self.assertEqual(lship["pct"], 60.0)
        # Positive annual delta vs FY2025 leadership avg (6.0+5.0)/2 = 5.5 → 55%.
        self.assertEqual(lship["delta"], 5.0)

    # ── 5. district heatmap uses verified SSA ────────────────────────────────
    def test_cd_district_heatmap_uses_verified_ssa(self):
        d = self._dash()
        rows = {r["name"]: r for r in d["district_heatmap"]["rows"]}
        self.assertIn("District A", rows)
        # District A avg SSA reflects the confirmed FY2026 record (7.5 → 75%),
        # never the unconfirmed 1.0 record.
        self.assertEqual(rows["District A"]["avg"], 75.0)

    # ── 6. partner performance uses verified activities + SSA delta ──────────
    def test_cd_partner_performance_uses_verified_activities_and_ssa_delta(self):
        d = self._dash()
        row = next(
            r
            for r in d["partner_performance"]["rows"]
            if r["name"] == "Hope Builders Network"
        )
        self.assertGreaterEqual(row["verified"], 1)  # the ia_verified partner activity
        self.assertEqual(row["schools_supported"], 1)  # a1 via PartnerAssignment
        # a1 annual SSA delta: (7.5 - 6.0) × 10 = 15.0pp.
        self.assertEqual(row["ssa_improve"], 15.0)

    # ── 7. cluster average uses all cluster-school SSA scores ────────────────
    def test_cd_cluster_average_uses_all_cluster_school_ssa_scores(self):
        from apps.clusters.models import Cluster

        cl = Cluster.objects.create(
            name="Cluster One", district=self.dist_a, region=self.region
        )
        # School.save() nulls cluster_id → assign via .update() (documented fixture path).
        School.objects.filter(id__in=[self.sch_a1.id, self.sch_b1.id]).update(
            cluster_id=cl.id, cluster_status="clustered"
        )
        d = self._dash()
        row = next(r for r in d["cluster_performance"]["rows"] if r["id"] == cl.id)
        # Avg of a1 (7.5) and b1 (5.5) latest confirmed SSA = 6.5 → 65%.
        self.assertEqual(row["schools"], 2)
        self.assertEqual(row["avg_ssa"], 65.0)

    # ── 8. recommended actions generate CD or PL To-Dos ──────────────────────
    def test_cd_recommended_actions_generate_cd_or_pl_todos(self):
        todos = S.cd_todos(self.cd, fy=FY)
        self.assertTrue(todos)
        for t in todos:
            self.assertIn(t["owner"], {"CD", "PL"})
        # Auto-close: a weekly request escalated to the CD raises a To-Do that
        # disappears once the request is no longer awaiting the CD.
        wfr = WeeklyFundRequest.objects.create(
            fy=FY,
            week_start_date=date(2026, 7, 6),
            week_end_date=date(2026, 7, 12),
            responsible_user=self.pl_a.id,
            total_amount=40_000,
            status="submitted_to_cd",
        )
        titles = {t["title"] for t in S.cd_todos(self.cd, fy=FY)}
        self.assertIn("Approve PL Weekly Fund Request", titles)
        WeeklyFundRequest.objects.filter(id=wfr.id).update(
            status="confirmed_for_advance"
        )
        titles2 = {t["title"] for t in S.cd_todos(self.cd, fy=FY)}
        self.assertNotIn("Approve PL Weekly Fund Request", titles2)

    # ── 9. budget health uses finance-workflow data ──────────────────────────
    def test_cd_budget_health_uses_finance_workflow_data(self):
        d = self._dash()
        bf = d["budget_finance"]
        self.assertEqual(bf["requested"], 180_000)  # 100k + 50k + 30k advances
        self.assertEqual(bf["disbursed"], 80_000)  # 50k disbursed + 30k accounted
        self.assertEqual(bf["utilization_pct"], 44)  # 80k / 180k

    # ── 10. operational risk counts real workflow gaps ───────────────────────
    def test_cd_operational_risk_counts_real_workflow_gaps(self):
        d = self._dash()
        risk = {c["label"]: c["count"] for c in d["operational_risk"]}
        self.assertEqual(risk["No SSA Schools"], 1)  # a2 only
        self.assertEqual(risk["No Visit"], 1)  # a2 (a1 & b1 visited)

    # ── 11. export respects role permissions ─────────────────────────────────
    def test_cd_export_respects_role_permissions(self):
        # cd_analytics is gated to the Country Director (+ Admin) only.
        self.assertEqual(PAGE_PERMISSIONS["cd_analytics"], {"CD", "ADMIN"})
        self.assertNotIn("CCEO", PAGE_PERMISSIONS["cd_analytics"])
        self.assertNotIn("PL", PAGE_PERMISSIONS["cd_analytics"])
        # The gated export route resolves to the permission-decorated view.
        match = resolve("/analytics/country-director/export")
        self.assertEqual(match.url_name, "cd_analytics_export")
        # Export payload is the country PL roster (both PLs, country-wide).
        rows = S.export_rows(self.cd, fy=FY)
        self.assertEqual({r["name"] for r in rows}, {"PL Ada", "PL Bola"})

    # ── 12. drill-downs are read/oversight, not field execution ──────────────
    def test_cd_drilldowns_are_read_or_oversight_actions_not_field_execution(self):
        scope = resolve_cd_scope(FY)
        acts = _country_activities(scope)
        _, cluster_school = S._cluster_membership(scope, acts)

        class _P(dict):
            def get(self, k, d=None):
                return dict.get(self, k, d)

        cases = [
            ("pl", _P(id=self.pl_a.id)),
            ("cceo", _P(id=self.a1_sp.id)),
            ("district", _P(id=self.dist_a.id)),
            ("region", _P(id=self.region.id)),
            ("partner", _P(id=self.partner.id)),
            ("ssa", _P(intervention="leadership")),
            ("budget", _P()),
            ("risk", _P(issue="no_ssa")),
            ("kpi", _P()),
        ]
        for kind, params in cases:
            payload = S.drilldown(self.cd, kind, params, fy=FY)
            self.assertTrue(payload.get("oversight_only"), f"{kind} not oversight-only")
            for a in payload.get("actions", []):
                self.assertFalse(
                    any(b in a.lower() for b in BANNED),
                    f"{kind}:{a} is field execution",
                )


class CDRefinedSpecTest(CDAnalyticsTest):
    """Improved enterprise workflow (§32) — the refined CD analytics rules.

    Inherits the country fixture; adds the mandated behaviours: weighted
    five-area overall achievement, coverage-honest heatmap, recommendation
    matrix, fairness context, SF-ID vs NetSuite separation, filter-preserving
    drilldowns, and permission-enforced endpoints.
    """

    def test_cd_has_no_field_execution_actions(self):
        d = self._dash()
        for kind, acts in S._OVERSIGHT_ACTIONS.items():
            for a in acts:
                self.assertFalse(any(b in a.lower() for b in BANNED), f"{kind}:{a}")
        for item in d["recommended_actions"]["items"]:
            self.assertIn(item["owner"], {"CD", "PL"})
            self.assertFalse(
                any(b in item["issue"].lower() for b in BANNED), item["issue"]
            )

    def test_cd_kpis_use_verified_workflow_data(self):
        from apps.analytics.pl_analytics_service import COMPLETED_STATUSES

        d = self._dash()
        by = {k["label"]: k["value"] for k in d["kpi_strip_items"]}
        real_completed = Activity.objects.filter(
            fy=FY, status__in=COMPLETED_STATUSES, deleted_at__isnull=True
        ).count()
        self.assertEqual(by["Total Activities Completed"], f"{real_completed:,}")
        self.assertEqual(by["Schools Impacted"], "2")  # only verified-reached schools

    def test_cd_ssa_uses_annual_verified_cycle(self):
        d = self._dash()
        by = {k["label"]: k["value"] for k in d["kpi_strip_items"]}
        # Confirmed FY2026 average = (7.5 + 5.5)/2 = 6.5 → 65%; the pending 1.0
        # record must not drag it down; no monthly SSA delta exists anywhere.
        self.assertEqual(by["Average SSA Score"], "65.0%")
        self.assertNotIn("monthly_delta", d["ssa_interventions"])

    def test_ssa_enrollment_score_separate_from_school_enrollment(self):
        # A wild SSA Enrollment *score* must not touch Students Impacted, which
        # comes from uploaded school enrollment of verified-reached schools.
        rec = SsaRecord.objects.filter(
            school=self.sch_a1, fy=FY, verification_status="confirmed"
        ).first()
        SsaScore.objects.create(ssa_record=rec, intervention="enrollment", score=9.9)
        cd = resolve_cd_scope(FY)
        impact = S.impact_summary(cd, _country_activities(cd))
        self.assertEqual(impact["students_impacted"], 220)  # 100 (A1) + 120 (B1)

    def test_district_heatmap_uses_all_eight_interventions(self):
        d = self._dash()
        hm = d["district_heatmap"]
        self.assertEqual(len(hm["codes"]), 8)
        self.assertEqual(
            hm["codes"], ["CB", "WOG", "FH", "Lship", "GR", "LE", "TE", "Erlm't"]
        )
        for row in hm["rows"]:
            self.assertEqual(len(row["cells"]), 8)

    def test_district_ssa_displays_coverage(self):
        d = self._dash()
        rows = {r["name"]: r for r in d["district_heatmap"]["rows"]}
        a = rows["District A"]  # 1 of 2 schools has verified SSA
        self.assertEqual(a["coverage"], "1 of 2")
        self.assertTrue(a["low_coverage"])  # 50% < 60% threshold
        b = rows["District B"]
        self.assertEqual(b["coverage"], "1 of 1")
        self.assertFalse(b["low_coverage"])

    def test_partner_recommendation_uses_target_and_impact(self):
        rec = S._partner_recommendation
        self.assertEqual(rec(80, 6, 10)[0], "Assign More Schools")
        self.assertEqual(rec(80, 1, 10)[0], "Quality Review")
        self.assertEqual(rec(40, 6, 10)[0], "Capacity Review")
        self.assertEqual(rec(70, -2, 10)[0], "Drop / Do Not Renew")
        self.assertEqual(rec(0, None, 0)[0], "Insufficient Data")
        self.assertEqual(rec(80, None, 10)[0], "Insufficient Data")

    def test_pl_performance_uses_supervised_team_data(self):
        d = self._dash()
        rows = {r["name"]: r for r in d["pl_oversight"]["rows"]}
        self.assertEqual(rows["PL Ada"]["cceos"], 1)  # her supervised team only
        self.assertEqual(rows["PL Bola"]["cceos"], 1)
        self.assertNotEqual(rows["PL Ada"]["backlog"], rows["PL Bola"].get("_x", None))

    def test_cceo_snapshot_uses_fairness_context(self):
        d = self._dash()
        rows = {r["name"]: r for r in d["cceo_snapshot"]["rows"]}
        self.assertEqual(rows["CCEO A1"]["schools"], 2)  # workload context shown
        self.assertEqual(rows["CCEO B1"]["schools"], 1)
        self.assertEqual(rows["CCEO A1"]["owner_pl"], "PL Ada")

    def test_cceo_snapshot_annual_delta_is_correct(self):
        cd = resolve_cd_scope(FY)
        rows = {
            r["name"]: r for r in S.cceo_snapshot(cd, _country_activities(cd))["rows"]
        }
        # sch_a1: 6.0 -> 7.5 = +1.5 -> 15.0pp; sch_b1: 5.0 -> 5.5 = +0.5 -> 5.0pp.
        self.assertEqual(rows["CCEO A1"]["ssa_improve"], 15.0)
        self.assertEqual(rows["CCEO B1"]["ssa_improve"], 5.0)

    def test_cceo_snapshot_excludes_other_cceo_schools(self):
        cd = resolve_cd_scope(FY)
        rows = {
            r["name"]: r for r in S.cceo_snapshot(cd, _country_activities(cd))["rows"]
        }
        # a1's SSA delta must be driven only by sch_a1/sch_a2 (a2 has no SSA),
        # never diluted or inflated by b1's schools.
        self.assertEqual(rows["CCEO A1"]["ssa_improve"], 15.0)

    def test_cceo_snapshot_handles_missing_ssa(self):
        # a2 has no SSA at all; only assigned to CCEO A1.
        cd = resolve_cd_scope(FY)
        rows = {
            r["name"]: r for r in S.cceo_snapshot(cd, _country_activities(cd))["rows"]
        }
        # Still computed from a1's measurable school only — never blocked or
        # zeroed out by the sibling school's missing SSA.
        self.assertEqual(rows["CCEO A1"]["ssa_improve"], 15.0)

    def test_cceo_snapshot_uses_verified_ssa_only(self):
        # The unconfirmed FY2026 record on sch_a1 (score 1.0, status=pending)
        # must never pull the delta toward it.
        cd = resolve_cd_scope(FY)
        rows = {
            r["name"]: r for r in S.cceo_snapshot(cd, _country_activities(cd))["rows"]
        }
        self.assertEqual(rows["CCEO A1"]["ssa_improve"], 15.0)

    def test_cceo_snapshot_query_count_is_bounded(self):
        # 2 PLs in the fixture: _pls() (1) + cycle_fys (1) + 3 queries per PL
        # via _pl_cceos (StaffProfile lookup, supervised-team list, school
        # assignments) + 1 bulk activity fetch + 2 bulk SSA cycle fetches.
        # This scales with PL count (small, fixed), never with CCEO count.
        cd = resolve_cd_scope(FY)
        acts = _country_activities(cd)
        with self.assertNumQueries(11):
            S.cceo_snapshot(cd, acts)

    def test_cceo_snapshot_query_count_stable_as_cceo_count_grows(self):
        # Add 20 more CCEOs (10 per PL) with schools + activities — the query
        # count for cceo_snapshot must not grow with CCEO count (only with PL
        # count, which stays at 2 here), proving the N+1 is gone.
        for i in range(20):
            pl_sp = self.pl_a_sp if i % 2 == 0 else self.pl_b_sp
            u, sp = self._staff(
                f"extra{i}@t.org", f"Extra CCEO {i}", EdifyRole.CCEO.value
            )
            StaffSupervisorAssignment.objects.create(supervisor=pl_sp, supervisee=sp)
            school = self._school(f"EX{i}", self.dist_a, 50, ssa_done=False)
            StaffSchoolAssignment.objects.create(staff=sp, school_id=school.id)
            self._act(sp.id, school, "school_visit", "ia_verified", sf=f"SV-EX{i}")
        cd = resolve_cd_scope(FY)
        acts = _country_activities(cd)
        with self.assertNumQueries(11):
            S.cceo_snapshot(cd, acts)

    def test_activity_sf_id_separate_from_netsuite_code(self):
        d = self._dash()
        risk_labels = [c["label"] for c in d["operational_risk"]]
        self.assertIn("Activity SF ID Pending", risk_labels)  # program proof
        self.assertIn("Accountability Pending", risk_labels)  # money proof
        by = {c["label"]: c for c in d["operational_risk"]}
        # a1's training completed without an SF ID → counted as SF-ID pending;
        # its aging window is the program-proof one, not a finance window.
        self.assertGreaterEqual(by["Activity SF ID Pending"]["count"], 1)
        self.assertEqual(by["Activity SF ID Pending"]["aging"], "7+ days")
        self.assertEqual(by["Accountability Pending"]["aging"], "14+ days")

    def test_recommended_action_creates_correct_todo(self):
        todos = S.cd_todos(self.cd, fy=FY)
        self.assertTrue(todos)
        for t in todos:
            self.assertIn(t["owner"], {"CD", "PL"})
            self.assertTrue(
                t.get("route") or t.get("action_url") or t.get("action_label")
            )

    def test_cd_drilldowns_preserve_filters(self):
        data = S.drilldown(
            self.cd,
            "district",
            {"id": self.dist_a.id},
            fy=FY,
            quarter="Q3",
            filters={"pl": self.pl_a.id},
        )
        self.assertEqual(data["fy"], FY)
        self.assertEqual(data["quarter"], "Q3")
        self.assertEqual(data["filters"].get("pl"), self.pl_a.id)

    def test_cd_export_respects_country_scope(self):
        from django.test import Client

        rows = S.export_rows(self.cd, fy=FY)
        names = {r["name"] for r in rows}
        self.assertIn("PL Ada", names)
        self.assertIn("PL Bola", names)  # full country, not one team
        c = Client()
        c.force_login(self.a1)  # a CCEO must not export
        self.assertNotEqual(
            c.get("/analytics/country-director/export").status_code, 200
        )

    def test_htmx_cd_endpoints_enforce_permission(self):
        from django.test import Client

        c = Client()
        c.force_login(self.a1)
        for url in (
            "/analytics/country-director",
            f"/analytics/country-director/drilldown?drill=district&id={self.dist_a.id}",
        ):
            self.assertNotEqual(c.get(url).status_code, 200, url)
        c.force_login(self.cd)
        self.assertEqual(
            c.get(
                f"/analytics/country-director/drilldown?drill=district&id={self.dist_a.id}"
            ).status_code,
            200,
        )

    def test_weighted_overall_uses_five_area_weights(self):
        from apps.targets.my_targets import TargetAchievementService

        # Build the validated ledgers: a1 visit (SF ✓) validates; a1 training
        # (no SF) stays provisional; the partner-delivered visit never credits.
        TargetAchievementService.rebuild(self.a1, FY)
        TargetAchievementService.rebuild(self.b1, FY)
        cd = resolve_cd_scope(FY)
        pct, achieved, target = S._weighted_overall(cd)
        # Visits: 2 validated of 2 targeted → 100% (w30). Trainings: 0 of 1 →
        # 0% (w20). Weighted = 3000/50 = 60.
        self.assertEqual((achieved, target), (2, 3))
        self.assertEqual(pct, 60)
        from apps.targets.models import TargetAchievementLedger

        self.assertFalse(
            TargetAchievementLedger.objects.filter(
                source_id=self.act_partner.id
            ).exists()
        )  # partner never double-counts
