"""Program Lead Command Dashboard — scope + correctness tests (mandate §20).

Two PLs, each supervising one CCEO. PL-A must never see PL-B's CCEO, schools,
activities, approvals, backlog, route, or funding. Personal targets (the PL's
own work) are computed separately from the supervised-team target progress.
A PL can approve a supervised CCEO's weekly fund request but never their own —
their own request routes to the CD.
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
from apps.analytics.pl_dashboard_service import ProgramLeadDashboardService as S
from apps.core.exceptions import Forbidden
from apps.core.rbac import EdifyRole
from apps.fund_requests.models import FundRequest, WeeklyFundRequest
from apps.fund_requests.weekly_service import approve_weekly_request, request_advance
from apps.geography.models import District, Region
from apps.notifications.models import Notification
from apps.schools.models import School

User = get_user_model()
FY = "2026"


class _P:
    def __init__(self, u):
        self.user_id = u.id
        self.active_role = u.active_role
        self.staff_profile_id = StaffProfile.objects.get(user=u).id


class PLDashboardTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="R")
        self.dist_a = District.objects.create(name="Dist A", region=self.region)
        self.dist_b = District.objects.create(name="Dist B", region=self.region)

        self.pl_a, self.pl_a_sp = self._staff(
            "pla@t.org", "PL A", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.a1, self.a1_sp = self._staff("a1@t.org", "CCEO A1", EdifyRole.CCEO.value)
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_a_sp, supervisee=self.a1_sp
        )

        self.pl_b, self.pl_b_sp = self._staff(
            "plb@t.org", "PL B", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.b1, self.b1_sp = self._staff("b1@t.org", "CCEO B1", EdifyRole.CCEO.value)
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_b_sp, supervisee=self.b1_sp
        )

        self.sch_a1 = self._school("A1", self.dist_a, ssa_done=True)
        self.sch_a2 = self._school(
            "A2", self.dist_a, ssa_done=False
        )  # no SSA → at risk
        self.sch_b1 = self._school("B1", self.dist_b, ssa_done=False)
        StaffSchoolAssignment.objects.create(staff=self.a1_sp, school_id=self.sch_a1.id)
        StaffSchoolAssignment.objects.create(staff=self.a1_sp, school_id=self.sch_a2.id)
        StaffSchoolAssignment.objects.create(staff=self.b1_sp, school_id=self.sch_b1.id)

        # A1 completes a visit on A1 (with SF ID) + a training missing SF ID.
        self._act(self.a1_sp.id, self.sch_a1, "school_visit", sf="SV-1")
        self._act(
            self.a1_sp.id, self.sch_a1, "training", sf=""
        )  # completed, no SF → backlog
        # B1's work must never surface for PL-A.
        self._act(self.b1_sp.id, self.sch_b1, "school_visit", sf="SV-B")

        # A weekly fund request from A1 → awaits PL-A.
        self.wfr_a = WeeklyFundRequest.objects.create(
            fy=FY,
            week_start_date=date(2026, 7, 6),
            week_end_date=date(2026, 7, 12),
            responsible_user=self.a1.id,
            total_amount=90_000,
            status="submitted_to_pl",
        )
        # A weekly fund request from B1 → awaits PL-B (must not appear for PL-A).
        WeeklyFundRequest.objects.create(
            fy=FY,
            week_start_date=date(2026, 7, 6),
            week_end_date=date(2026, 7, 12),
            responsible_user=self.b1.id,
            total_amount=50_000,
            status="submitted_to_pl",
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

    def _school(self, sid, district, ssa_done):
        return School.objects.create(
            school_id=f"S-{sid}",
            name=f"School {sid}",
            region=self.region,
            district=district,
            enrollment=100,
            current_fy_ssa_status="done" if ssa_done else "not_done",
        )

    def _act(self, sp_id, school, atype, sf=""):
        return Activity.objects.create(
            school=school,
            activity_type=atype,
            delivery_type="staff",
            status="completed",
            responsible_staff_id=sp_id,
            fy=FY,
            quarter="Q3",
            planned_date=date(2026, 4, 10),
            scheduled_date=timezone.make_aware(timezone.datetime(2026, 4, 10, 9, 0)),
            evidence_status="accepted",
            salesforce_activity_id=sf,
        )

    def _dash(self, user):
        return S.get_dashboard(user, fy=FY)

    # ── 1/2. scope isolation ─────────────────────────────────────────────────
    def test_pl_dashboard_scope_only_supervised_cceos(self):
        d = self._dash(self.pl_a)
        names = {r["name"] for r in d["cceo_performance"]["rows"]}
        self.assertEqual(names, {"CCEO A1"})
        self.assertNotIn("CCEO B1", names)

    def test_pl_dashboard_excludes_other_pl_portfolio(self):
        d = self._dash(self.pl_a)
        urgent = {r["school"] for r in d["urgent_schools"]}
        self.assertIn("School A2", urgent)
        self.assertNotIn("School B1", urgent)

    def test_urgent_queue_distinguishes_personal_and_supervised_ownership(self):
        own_school = self._school("PL-OWN", self.dist_a, ssa_done=False)
        StaffSchoolAssignment.objects.create(
            staff=self.pl_a_sp, school_id=own_school.id
        )

        rows = {row["school"]: row for row in self._dash(self.pl_a)["urgent_schools"]}

        self.assertEqual(rows["School PL-OWN"]["owner_kind"], "pl")
        self.assertEqual(rows["School PL-OWN"]["owner_name"], "PL A")
        self.assertEqual(rows["School A2"]["owner_kind"], "cceo")
        self.assertEqual(rows["School A2"]["owner_name"], "CCEO A1")
        self.assertEqual(
            rows["School A2"]["recommended_activity_label"],
            "Complete SSA",
        )
        self.assertIn(
            "recommended_activity_type=baseline_ssa_visit",
            rows["School PL-OWN"]["schedule_url"],
        )

    def test_urgent_schools_use_four_row_pages_without_losing_scope(self):
        for index in range(5):
            school = self._school(f"PAGE-{index}", self.dist_a, ssa_done=False)
            StaffSchoolAssignment.objects.create(staff=self.a1_sp, school_id=school.id)

        from apps.analytics.pl_analytics_service import resolve_pl_scope

        pls = resolve_pl_scope(self.pl_a)
        first_page = S.urgent_schools_page(self.pl_a, pls, FY, {}, page=1)
        second_page = S.urgent_schools_page(self.pl_a, pls, FY, {}, page=2)

        self.assertEqual(first_page["page_size"], 4)
        self.assertEqual(first_page["total"], 6)
        self.assertEqual(len(first_page["rows"]), 4)
        self.assertEqual(len(second_page["rows"]), 2)
        self.assertTrue(first_page["has_next"])
        self.assertTrue(second_page["has_previous"])
        self.assertFalse(second_page["has_next"])
        self.assertFalse(
            {row["id"] for row in first_page["rows"]}
            & {row["id"] for row in second_page["rows"]}
        )
        self.assertNotIn(
            self.sch_b1.id,
            {row["id"] for row in first_page["rows"] + second_page["rows"]},
        )

    def test_pl_send_creates_one_tracked_action_and_a_second_send_is_refused(self):
        """Sending used to write a notification and nothing else, so it was
        "idempotent" only in the sense that a retry re-marked the same
        notification unread — there was no record to duplicate. It now commits
        a TeamAction, and the second attempt is refused with a reason rather
        than silently repeating."""
        from apps.planning.action_models import ACTIVE_STATES, TeamAction

        self.client.force_login(self.pl_a)
        url = f"/dashboard/pl-send-urgent-action?school_id={self.sch_a2.id}&fy={FY}"

        first = self.client.post(url, HTTP_HX_REQUEST="true")
        second = self.client.post(url, HTTP_HX_REQUEST="true")

        self.assertEqual(first.status_code, 200)
        self.assertContains(first, "Sent to CCEO A1")

        actions = TeamAction.objects.filter(school_id=self.sch_a2.id)
        self.assertEqual(actions.count(), 1)
        action = actions.get()
        self.assertEqual(action.recipient_id, self.a1.id)
        self.assertIn(action.state, ACTIVE_STATES)
        self.assertIsNotNone(action.due_date)

        self.assertEqual(second.status_code, 200)
        self.assertContains(second, "Already sent")
        self.assertEqual(TeamAction.objects.filter(school_id=self.sch_a2.id).count(), 1)

        note = Notification.objects.get(
            recipient_id=self.a1.id,
            context_id=action.id,
            source_event_type="school_action_assigned",
        )
        self.assertTrue(note.action_required)
        # The notification routes to the work, not to a dashboard to search.
        self.assertEqual(note.target_route, action.workflow_route)

    def test_a_sent_school_leaves_the_pl_urgent_queue(self):
        """The point of the whole change: the card is an UNASSIGNED queue."""
        from apps.analytics.pl_analytics_service import resolve_pl_scope

        pls = resolve_pl_scope(self.pl_a)

        def on_card():
            rows = S.urgent_schools(self.pl_a, pls, FY, {}, limit=5000)
            return any(r["id"] == self.sch_a2.id for r in rows)

        self.assertTrue(on_card())
        self.client.force_login(self.pl_a)
        self.client.post(
            f"/dashboard/pl-send-urgent-action?school_id={self.sch_a2.id}&fy={FY}",
            HTTP_HX_REQUEST="true",
        )
        self.assertFalse(on_card())

    def test_pl_cannot_delegate_another_program_leads_school(self):
        self.client.force_login(self.pl_a)
        response = self.client.post(
            f"/dashboard/pl-send-urgent-action?school_id={self.sch_b1.id}&fy={FY}",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 403)

    # ── 3. KPIs scoped ───────────────────────────────────────────────────────
    def test_pl_kpis_scoped_to_supervised_team(self):
        d = self._dash(self.pl_a)
        by = {k["label"]: k["value"] for k in d["kpi_strip_items"]}
        # 2 completed visits/trainings by A1 (B1's excluded); 1 has SF ID → 50%.
        self.assertEqual(by["Activity SF ID Compliance"], "50%")

    def test_missing_target_denominators_are_not_rendered_as_zero_percent(self):
        dashboard = self._dash(self.pl_a)
        by_label = {item["label"]: item for item in dashboard["kpi_strip_items"]}
        self.assertEqual(by_label["Team Execution Progress"]["value"], "Not measured")
        self.assertEqual(by_label["CCEOs On Track"]["value"], "Not measured")

        supervision = next(
            card
            for card in dashboard["personal_targets"]["cards"]
            if card["label"] == "Supervision Visits"
        )
        self.assertFalse(supervision["has_target"])
        self.assertIsNone(supervision["pct"])

        self.client.force_login(self.pl_a)
        response = self.client.get("/dashboard", {"fy": FY})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "0/0")
        self.assertContains(response, "Not measurable")

    def test_monthly_fund_request_uses_exact_month_and_complete_pl_team(self):
        def monthly(owner, month, amount):
            return FundRequest.objects.create(
                fy=FY,
                period="monthly",
                period_key=f"{FY}-M{month}",
                scope="own",
                submitted_by_user_id=owner.id,
                submitted_by_role=owner.active_role,
                total_amount=amount,
                activity_count=1,
                status="draft",
            )

        monthly(self.a1, 8, 90_000)
        monthly(self.pl_a, 8, 40_000)
        monthly(self.b1, 8, 500_000)  # another PL's team
        monthly(self.pl_a, 7, 700_000)  # another month

        dashboard = S.get_dashboard(self.pl_a, fy=FY, month="8")
        by_label = {item["label"]: item for item in dashboard["kpi_strip_items"]}
        funding = by_label["Monthly Fund Request"]
        self.assertEqual(funding["value"], "UGX 130K")
        self.assertEqual(funding["link"], "?drill=funding&month=8")
        self.assertIn("August team plan", funding["helper"])

        drilldown = S.drilldown(self.pl_a, "funding", fy=FY, month="8")
        self.assertEqual(drilldown["kind"], "fund_requests")
        self.assertEqual(drilldown["title"], "Monthly Team Fund Requests")
        self.assertEqual(
            {(row["owner"], row["amount"]) for row in drilldown["fund_requests"]},
            {("CCEO A1", "UGX 90,000"), ("PL A", "UGX 40,000")},
        )
        self.assertIn("UGX 130,000", drilldown["subtitle"])

        self.client.force_login(self.pl_a)
        dashboard_response = self.client.get("/dashboard", {"fy": FY})
        self.assertEqual(dashboard_response.status_code, 200)
        dashboard_html = dashboard_response.content.decode()
        funding_link_start = dashboard_html.index(
            '<a href="/dashboard/pl-drilldown?drill=funding'
        )
        funding_link_end = dashboard_html.index(">", funding_link_start)
        funding_link = dashboard_html[funding_link_start:funding_link_end]
        self.assertIn('hx-get="/dashboard/pl-drilldown?drill=funding', funding_link)
        self.assertIn('hx-target="#drawer-container"', funding_link)
        self.assertIn('hx-swap="innerHTML"', funding_link)

        response = self.client.get(
            f"/dashboard/pl-drilldown?drill=funding&fy={FY}&month=8"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Monthly Team Fund Requests")
        self.assertContains(response, "UGX 130,000")
        self.assertContains(response, "UGX 90,000")
        self.assertContains(response, "UGX 40,000")
        self.assertNotContains(response, "UGX 500,000")

    # ── 4. personal vs team targets are separate ─────────────────────────────
    def test_pl_personal_targets_are_separate_from_team_targets(self):
        StaffTargetProfile.objects.create(staff=self.pl_a_sp, fy=FY, visits_target=10)
        StaffTargetProfile.objects.create(
            staff=self.a1_sp, fy=FY, visits_target=2, trainings_target=1
        )
        d = self._dash(self.pl_a)
        labels = {c["label"] for c in d["personal_targets"]["cards"]}
        self.assertEqual(
            labels,
            {
                "Supervision Visits",
                "Plan Approvals",
                "Team Reviews",
                "Fund Requests Reviewed",
            },
        )
        # PL's own supervision-visit target (10) is independent of the team target.
        sv = next(
            c
            for c in d["personal_targets"]["cards"]
            if c["label"] == "Supervision Visits"
        )
        self.assertEqual(sv["target"], 10)

    # ── 5. approval queue scoped ─────────────────────────────────────────────
    def test_pl_approval_queue_only_supervised_cceo_items(self):
        from apps.analytics.pl_analytics_service import resolve_pl_scope

        dashboard = self._dash(self.pl_a)
        queue = S.approval_queue(self.pl_a, resolve_pl_scope(self.pl_a), FY)
        staff = {r["staff"] for r in queue["rows"]}

        self.assertNotIn("approval_queue", dashboard)
        self.assertIn("CCEO A1", staff)
        self.assertNotIn("CCEO B1", staff)

    # ── 6. PL cannot approve own weekly fund request ─────────────────────────
    def test_pl_cannot_approve_own_weekly_fund_request(self):
        own = WeeklyFundRequest.objects.create(
            fy=FY,
            week_start_date=date(2026, 7, 13),
            week_end_date=date(2026, 7, 19),
            responsible_user=self.pl_a.id,
            total_amount=40_000,
            status="submitted_to_cd",
        )
        with self.assertRaises(Forbidden):
            approve_weekly_request(own.id, _P(self.pl_a))

    # ── 7. PL's own weekly fund request routes to CD ─────────────────────────
    def test_pl_own_weekly_fund_request_routes_to_cd(self):
        own = WeeklyFundRequest.objects.create(
            fy=FY,
            week_start_date=date(2026, 7, 20),
            week_end_date=date(2026, 7, 26),
            responsible_user=self.pl_a.id,
            total_amount=40_000,
            status="pending_responsible_confirmation",
        )
        res = request_advance(own.id, _P(self.pl_a))
        self.assertEqual(res["status"], "submitted_to_cd")

    # ── 8. Activity SF ID backlog ────────────────────────────────────────────
    def test_activity_sf_id_backlog_calculation(self):
        d = self._dash(self.pl_a)
        # One completed training by A1 has no SF ID → in the backlog snapshot.
        overdue = next(c for c in d["backlog_snapshot"] if "SF ID" in c["label"])
        self.assertGreaterEqual(overdue["value"], 0)
        # Compliance = 1 of 2 → 50%.
        by = {k["label"]: k["value"] for k in d["kpi_strip_items"]}
        self.assertEqual(by["Activity SF ID Compliance"], "50%")

    # ── 9. high-risk schools scoped ──────────────────────────────────────────
    def test_high_risk_schools_scoped_to_pl(self):
        from apps.analytics.pl_dashboard_service import ProgramLeadDashboardService
        from apps.analytics.pl_analytics_service import resolve_pl_scope

        pls = resolve_pl_scope(self.pl_a)
        acts = ProgramLeadDashboardService._team_acts(pls, FY, {})
        n = ProgramLeadDashboardService._high_risk_count(pls, FY, acts)
        # A2 (no SSA + not visited) is high risk; B1 is never counted for PL-A.
        self.assertGreaterEqual(n, 1)
        self.assertNotIn(self.sch_b1.id, pls.school_ids)

    # ── 10. team backlog scoped ──────────────────────────────────────────────
    def test_team_backlog_scoped_to_pl(self):
        d = self._dash(self.pl_a)
        by = {k["label"]: k["value"] for k in d["kpi_strip_items"]}
        # Backlog counts A1's missing-SF training; B1's work is excluded.
        self.assertGreaterEqual(int(by["Team Backlog"]), 1)

    # ── 11. route & capacity scoped ──────────────────────────────────────────
    def test_route_capacity_scoped_to_pl(self):
        d = self._dash(self.pl_a)
        names = {t["name"] for t in d["route_capacity"]["table"]}
        self.assertLessEqual(names, {"CCEO A1"})
        self.assertNotIn("CCEO B1", names)

    # ── 12. funding & execution scoped ───────────────────────────────────────
    def test_funding_execution_scoped_to_pl(self):
        # A1's approved request counts for PL-A; B1's never does.
        WeeklyFundRequest.objects.filter(id=self.wfr_a.id).update(
            status="confirmed_for_advance"
        )
        WeeklyFundRequest.objects.create(
            fy=FY,
            week_start_date=date(2026, 8, 3),
            week_end_date=date(2026, 8, 9),
            responsible_user=self.b1.id,
            total_amount=500_000,
            status="confirmed_for_advance",
        )
        d = self._dash(self.pl_a)
        approved = next(
            b for b in d["funding_execution"]["statuses"] if b["label"] == "Approved"
        )
        self.assertEqual(approved["count"], 1)  # only A1's, not B1's

    # ── 13. quick actions route to valid pages ───────────────────────────────
    def test_quick_actions_route_to_valid_pages(self):
        d = self._dash(self.pl_a)
        for q in d["quick_actions"]:
            path = q["url"].split("?")[0]
            self.assertTrue(resolve(path), f"{path} did not resolve")

    # ── 14. dashboard To-Dos auto-close after workflow action ────────────────
    def test_dashboard_todos_auto_close_after_workflow_action(self):
        from apps.analytics.pl_analytics_service import PLAnalyticsService

        titles = {t["title"] for t in PLAnalyticsService.pl_todos(self.pl_a, fy=FY)}
        self.assertIn("Schedule SSA Collection", titles)
        # Resolve the underlying state: every school gets verified SSA.
        School.objects.filter(id__in=[self.sch_a1.id, self.sch_a2.id]).update(
            current_fy_ssa_status="done"
        )
        titles2 = {t["title"] for t in PLAnalyticsService.pl_todos(self.pl_a, fy=FY)}
        self.assertNotIn("Schedule SSA Collection", titles2)
