"""Program Lead dashboard — scope, structure and correctness.

Two PLs, each supervising one CCEO. PL-A must never see PL-B's CCEO, schools,
activities, handoffs or approvals. A PL can approve a supervised CCEO's weekly
fund request but never their own — their own request routes to the CD.

Rebuilt around the role description on 2026-09-13 (owner): a fixed part (six
team pulse tiles and Leadership Attention) above one view at a time — Map,
Priorities, Team, Coaching, Programmes, Collaboration — and only the fixed part
and the chosen view are built. The dashboard decides nothing in place: every
control opens the page where the work is done.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import Resolver404, resolve
from django.utils import timezone

from apps.accounts.models import (
    Leave,
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
)
from apps.activities.models import Activity
from apps.analytics import pl_dashboard_service as dashboard_module
from apps.analytics.pl_dashboard_service import (
    ATTENTION_LIMIT,
    DashboardContext,
    ProgramLeadDashboardService as S,
    normalise_view,
)
from apps.core.exceptions import Forbidden
from apps.core.rbac import EdifyRole
from apps.flags.models import CdFlag
from apps.frontend.views.dashboard_view_state import VIEW_COOKIE_PREFIX
from apps.fund_requests.models import WeeklyFundRequest
from apps.fund_requests.weekly_service import approve_weekly_request, request_advance
from apps.geography.models import District, Region
from apps.notifications.models import Notification
from apps.schools.models import School
from apps.ssa.models import SsaRecord
from apps.targets.models import CatchUpPlan, TargetArea

User = get_user_model()
FY = "2026"
LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "pl-dashboard-tests",
    }
}
TILE_LABELS = [
    "Team Priority Progress",
    "CCEOs On Track",
    "Waiting on You",
    "SSA Coverage",
    "Trainings Delivered",
    "Open Handoffs",
]
# Pages the Program Lead no longer holds (navigation contract, 2026-09-13) and
# the retired disbursement queue: no dashboard link may lead to one.
CLOSED_PATHS = (
    "/disbursements",
    "/business-transformation",
    "/hr-today",
    "/reports",
    "/coverage",
    "/decision-intelligence",
    "/monthly-request",
)


class _P:
    def __init__(self, u):
        self.user_id = u.id
        self.active_role = u.active_role
        self.staff_profile_id = StaffProfile.objects.get(user=u).id


@override_settings(CACHES=LOCMEM)
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
        )  # completed, no SF → pending
        # B1's work must never surface for PL-A.
        self._act(self.b1_sp.id, self.sch_b1, "school_visit", sf="SV-B")
        self._act(self.b1_sp.id, self.sch_b1, "training", sf="")

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
        self.wfr_b = WeeklyFundRequest.objects.create(
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

    def _act(self, sp_id, school, atype, sf="", **extra):
        values = {
            "school": school,
            "activity_type": atype,
            "delivery_type": "staff",
            "status": "completed",
            "responsible_staff_id": sp_id,
            "fy": FY,
            "quarter": "Q3",
            "planned_date": date(2026, 4, 10),
            "scheduled_date": timezone.make_aware(timezone.datetime(2026, 4, 10, 9, 0)),
            "evidence_status": "accepted",
            "salesforce_activity_id": sf,
        }
        values.update(extra)
        return Activity.objects.create(**values)

    def _catch_up_plan(self):
        area, _ = TargetArea.objects.get_or_create(
            key="pl-dash-visits", defaults={"label": "Visits"}
        )
        return CatchUpPlan.objects.create(
            pl_user_id=self.pl_a.id,
            staff_user_id=self.a1.id,
            area=area,
            fy=FY,
            month_of_fy=8,
            status="submitted",
        )

    def _dash(self, user, view="map", **kwargs):
        return S.get_dashboard(user, fy=FY, view=view, **kwargs)

    def _hrefs(self, html):
        return set(re.findall(r'href="(/[^"#]*)', html))

    # ── Views: the rail, the alias and building only what is shown ──────────
    def test_views_are_the_map_and_the_five_responsibilities(self):
        self.assertEqual(
            [key for key, _label, _hint in dashboard_module.VIEW_TABS],
            ["map", "priorities", "team", "coaching", "programmes", "collaboration"],
        )
        self.assertEqual(dashboard_module.DEFAULT_VIEW, "map")
        self.assertEqual(normalise_view("operations"), "team")
        self.assertEqual(normalise_view("Coaching"), "coaching")
        self.assertEqual(normalise_view("funding"), "map")
        self.assertEqual(normalise_view(None), "map")

    def test_only_the_fixed_part_and_the_chosen_view_are_built(self):
        other_views = {
            "priorities_view",
            "team_view",
            "coaching_view",
            "programmes_view",
            "collaboration_view",
        }
        for view in ("map", "priorities", "team", "coaching", "programmes"):
            with self.subTest(view=view):
                patches = {
                    name: patch.object(S, name, wraps=getattr(S, name))
                    for name in other_views
                }
                mocks = {name: p.start() for name, p in patches.items()}
                try:
                    data = self._dash(self.pl_a, view=view)
                finally:
                    for p in patches.values():
                        p.stop()
                built = {name for name, mock in mocks.items() if mock.called}
                expected = set() if view == "map" else {f"{view}_view"}
                self.assertEqual(built, expected)
                self.assertEqual(data["dashboard_view"], view)
                self.assertEqual(len(data["kpi_strip_items"]), 6)
                self.assertIn("leadership_attention", data)

        swap = self._dash(self.pl_a, view="team", include_fixed=False)
        self.assertNotIn("kpi_strip_items", swap)
        self.assertNotIn("leadership_attention", swap)
        self.assertIn("cceo_performance", swap)
        self.assertNotIn("ssa_matrix", swap)

    def test_operations_bookmark_and_cookie_land_on_team_and_are_rewritten(self):
        self.client.force_login(self.pl_a)
        response = self.client.get("/dashboard", {"fy": FY, "view": "operations"})
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('data-pl-view="team"', html)
        self.assertIn('name="view" value="team"', html)
        self.assertEqual(response.cookies[f"{VIEW_COOKIE_PREFIX}pl"].value, "team")

        self.client.cookies[f"{VIEW_COOKIE_PREFIX}pl"] = "operations"
        response = self.client.get("/dashboard", {"fy": FY})
        self.assertIn('data-pl-view="team"', response.content.decode())
        self.assertEqual(response.cookies[f"{VIEW_COOKIE_PREFIX}pl"].value, "team")

    def test_a_tab_click_builds_the_view_without_the_fixed_part(self):
        self.client.force_login(self.pl_a)
        with patch.object(S, "kpis", wraps=S.kpis) as kpis:
            response = self.client.get(
                "/dashboard",
                {"fy": FY, "view": "coaching"},
                HTTP_HX_REQUEST="true",
                HTTP_HX_TARGET="pl-dashboard-view-shell",
            )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(kpis.called)
        html = response.content.decode()
        self.assertIn('data-pl-view="coaching"', html)
        self.assertNotIn("Leadership Attention", html)
        self.assertIn('id="pl-filter-view" name="view" value="coaching"', html)

    def test_an_unknown_year_falls_back_to_the_operational_year(self):
        from apps.core.fy import get_operational_fy

        self.client.force_login(self.pl_a)
        response = self.client.get("/dashboard", {"fy": "1999'--", "view": "team"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["fy"], get_operational_fy())

    # ── The fixed part ───────────────────────────────────────────────────────
    def test_team_pulse_is_six_registered_tiles_each_opening_its_view(self):
        tiles = self._dash(self.pl_a)["kpi_strip_items"]
        self.assertEqual([t["label"] for t in tiles], TILE_LABELS)
        views = [t["drilldown_url"].split("view=")[1] for t in tiles]
        self.assertEqual(
            views,
            [
                "priorities",
                "coaching",
                "team",
                "programmes",
                "programmes",
                "collaboration",
            ],
        )
        from apps.core.metrics.pl_dashboard_metrics import PL_DASHBOARD_METRIC_ROWS

        self.assertEqual(
            [row["source_label"] for row in PL_DASHBOARD_METRIC_ROWS], TILE_LABELS
        )

    def test_missing_target_denominators_are_not_rendered_as_zero_percent(self):
        by_label = {t["label"]: t for t in self._dash(self.pl_a)["kpi_strip_items"]}
        self.assertEqual(by_label["Team Priority Progress"]["value"], "Not measured")
        self.assertEqual(by_label["CCEOs On Track"]["value"], "Not measured")

        self.client.force_login(self.pl_a)
        response = self.client.get("/dashboard", {"fy": FY, "view": "team"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "0/0")

    def test_team_pulse_counts_only_the_supervised_team(self):
        by_label = {t["label"]: t for t in self._dash(self.pl_a)["kpi_strip_items"]}
        # A1's one completed training; B1's is never counted for PL-A.
        self.assertEqual(by_label["Trainings Delivered"]["value"], "1")
        # A1's weekly request waits on PL-A; B1's waits on PL-B.
        self.assertEqual(by_label["Waiting on You"]["value"], "1")
        SsaRecord.objects.create(
            school=self.sch_a1,
            date_of_ssa=timezone.now(),
            fy=FY,
            quarter="Q3",
            verification_status="confirmed",
            uploaded_by="ia",
        )
        SsaRecord.objects.create(
            school=self.sch_b1,
            date_of_ssa=timezone.now(),
            fy=FY,
            quarter="Q3",
            verification_status="confirmed",
            uploaded_by="ia",
        )
        by_label = {t["label"]: t for t in self._dash(self.pl_a)["kpi_strip_items"]}
        self.assertEqual(by_label["SSA Coverage"]["value"], "50%")

    def test_attention_heading_always_renders_with_an_empty_state(self):
        self.client.force_login(self.pl_b)
        WeeklyFundRequest.objects.all().delete()
        response = self.client.get("/dashboard", {"fy": FY, "view": "map"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Leadership Attention")
        self.assertEqual(response.context["leadership_attention"], [])
        self.assertContains(response, "Nothing needs your attention right now.")

    def test_attention_shows_a_country_director_flag_and_opens_quality_flags(self):
        CdFlag.objects.create(
            raised_by_user_id="cd-1",
            raised_by_name="CD",
            assigned_to_user_id=self.pl_a.id,
            category="quality",
            note="Check the returned evidence",
            due_date=(timezone.localdate() - timedelta(days=1)).isoformat(),
            status="open",
        )
        CdFlag.objects.create(
            raised_by_user_id="cd-1",
            assigned_to_user_id=self.pl_b.id,
            category="quality",
            note="Not PL-A's",
            status="open",
        )
        cards = self._dash(self.pl_a)["leadership_attention"]
        flag = next(c for c in cards if c["responsibility"] == "Collaboration")
        self.assertEqual(flag["title"], "1 Country Director flag open")
        self.assertEqual(flag["tone"], "danger")
        self.assertEqual(flag["url"], "/quality-checks")

    def test_attention_is_at_most_four_items_most_urgent_first(self):
        group = {"count": 2, "overdue": 1}
        ctx = SimpleNamespace(
            handoffs={"groups_by_key": {"escalations": group}},
            collaboration={
                "cd_flags": {"open": 1, "overdue": 0},
                "regional_feedback": {"count": 1},
                "regional_coaching": {"count": 0},
                "partner_delivery": {"late": 3},
            },
            cceo_rows=[{"name": "A", "risk": "Critical"}],
            catch_up_by_user={"u": 1},
            overloaded=[{"name": "A"}],
            leave_conflicts=[],
        )
        cards = S.leadership_attention(ctx)
        self.assertEqual(len(cards), ATTENTION_LIMIT)
        tones = [c["tone"] for c in cards]
        self.assertEqual(tones, sorted(tones, key={"danger": 0, "warning": 1}.get))
        for card in cards:
            self.assertTrue(card["url"].startswith("/"))
            self.assertTrue(card["responsibility"])

    def test_catch_up_plans_waiting_on_the_lead_reach_attention(self):
        self._catch_up_plan()
        cards = self._dash(self.pl_a)["leadership_attention"]
        card = next(c for c in cards if c["responsibility"] == "Performance & coaching")
        self.assertIn("1 catch-up plan to approve", card["title"])
        self.assertEqual(card["url"], "/team-targets")

    def test_mobile_primary_action_is_the_first_attention_item(self):
        self.client.force_login(self.pl_b)
        WeeklyFundRequest.objects.all().delete()
        response = self.client.get("/dashboard", {"fy": FY})
        self.assertEqual(
            response.context["mobile_primary_action"]["url"],
            f"/team-planning-oversight/?fy={FY}",
        )
        CdFlag.objects.create(
            raised_by_user_id="cd-1",
            assigned_to_user_id=self.pl_b.id,
            category="quality",
            note="Follow up",
            status="open",
        )
        response = self.client.get("/dashboard", {"fy": FY})
        self.assertEqual(
            response.context["mobile_primary_action"],
            {"label": "Respond to flags", "url": "/quality-checks"},
        )

    # ── Team view ────────────────────────────────────────────────────────────
    def test_pl_dashboard_scope_only_supervised_cceos(self):
        d = self._dash(self.pl_a, view="team")
        names = {r["name"] for r in d["cceo_performance"]["rows"]}
        self.assertEqual(names, {"CCEO A1"})

    def test_waiting_on_you_groups_open_where_each_is_decided(self):
        Leave.objects.create(
            staff=self.a1_sp,
            type="personal_time_off",
            start_date="2026-10-01",
            end_date="2026-10-02",
            days=2,
            status="pending",
        )
        Leave.objects.create(
            staff=self.b1_sp,
            type="personal_time_off",
            start_date="2026-10-01",
            end_date="2026-10-02",
            days=2,
            status="pending",
        )
        waiting = self._dash(self.pl_a, view="team")["waiting_on_you"]
        by_key = waiting["groups_by_key"]
        self.assertEqual(
            {key: g["url"] for key, g in by_key.items()},
            {
                "fund": "/fund-approvals",
                "completions": "/pl/review-queue",
                "leave": "/leave/approvals",
                "escalations": "/escalations",
                "debriefs": "/debriefs",
            },
        )
        self.assertEqual(by_key["fund"]["count"], 1)
        self.assertEqual(by_key["leave"]["count"], 1)
        self.assertEqual(waiting["by_staff"].get(self.a1_sp.id), waiting["total"])
        self.assertNotIn(self.b1_sp.id, waiting["by_staff"])

    def test_team_week_counts_the_team_in_the_field_today_only(self):
        today = timezone.localdate()
        self._act(
            self.a1_sp.id,
            self.sch_a2,
            "school_visit",
            status="scheduled",
            planned_date=today,
        )
        self._act(
            self.b1_sp.id,
            self.sch_b1,
            "school_visit",
            status="scheduled",
            planned_date=today,
        )
        week = self._dash(self.pl_a, view="team")["team_week"]
        self.assertEqual(week["in_field"], [{"name": "CCEO A1", "activities": 1}])

    def test_pl_approval_queue_only_supervised_cceo_items(self):
        from apps.analytics.pl_analytics_service import resolve_pl_scope

        queue = S.approval_queue(self.pl_a, resolve_pl_scope(self.pl_a), FY)
        staff = {r["staff"] for r in queue["rows"]}
        self.assertIn("CCEO A1", staff)
        self.assertNotIn("CCEO B1", staff)
        fund = next(r for r in queue["rows"] if r["kind"] == "weekly_fund")
        self.assertEqual(fund["url"], "/fund-approvals")

    def test_the_approvals_drawer_links_out_and_approves_nothing(self):
        self.client.force_login(self.pl_a)
        response = self.client.get(f"/dashboard/pl-drilldown?drill=approvals&fy={FY}")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('href="/fund-approvals"', html)
        self.assertNotIn("pl-approve", html)
        self.assertNotIn("CCEO B1", html)
        # A retired drawer name opens the approvals drawer, never a stale one.
        response = self.client.get(f"/dashboard/pl-drilldown?drill=funding&fy={FY}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Waiting on your approval", response.content.decode())

    def test_the_retired_inline_approve_decides_nothing(self):
        self.client.force_login(self.pl_a)
        url = f"/dashboard/pl-approve?kind=weekly_fund&id={self.wfr_a.id}&fy={FY}"
        response = self.client.post(url, HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"], "/fund-approvals")
        response = self.client.post(url)
        self.assertRedirects(response, "/fund-approvals", fetch_redirect_response=False)
        self.wfr_a.refresh_from_db()
        self.assertEqual(self.wfr_a.status, "submitted_to_pl")

    def test_other_roles_are_refused_the_program_lead_endpoints(self):
        self.client.force_login(self.a1)
        for method, url in (
            ("get", f"/dashboard/pl-drilldown?drill=cceos&fy={FY}"),
            ("get", f"/dashboard/pl-urgent-schools?fy={FY}"),
            ("post", f"/dashboard/pl-approve?kind=weekly_fund&id={self.wfr_a.id}"),
        ):
            with self.subTest(url=url):
                response = getattr(self.client, method)(url)
                self.assertIn(response.status_code, (302, 403))
        self.wfr_a.refresh_from_db()
        self.assertEqual(self.wfr_a.status, "submitted_to_pl")

    def test_drilldowns_read_only_the_lead_s_team(self):
        cceos = S.drilldown(self.pl_a, "cceos", fy=FY)
        self.assertEqual({c["name"] for c in cceos["cceos"]}, {"CCEO A1"})
        backlog = S.drilldown(self.pl_a, "sf_backlog", fy=FY)
        self.assertEqual(len(backlog["activities"]), 1)
        self.assertEqual(backlog["activities"][0]["owner"], "CCEO A1")

    # ── Coaching view ────────────────────────────────────────────────────────
    def test_coaching_rows_per_officer_with_evidence_quality(self):
        self._catch_up_plan()
        data = self._dash(self.pl_a, view="coaching")
        rows = data["coaching_rows"]
        self.assertEqual([r["name"] for r in rows], ["CCEO A1"])
        row = rows[0]
        self.assertEqual(row["sf_pending"], 1)
        self.assertEqual(row["catch_up"], 1)
        self.assertIn(f"staff={self.a1_sp.id}", row["conversation_url"])
        self.assertIn(f"cceo={self.a1_sp.id}", row["coaching_url"])
        self.assertEqual(data["coaching_totals"]["catch_up"], 1)

    # ── Priorities view ──────────────────────────────────────────────────────
    def test_ssa_informed_plans_rate_per_officer(self):
        informed = self._act(
            self.a1_sp.id, self.sch_a2, "school_visit", status="scheduled"
        )
        uninformed = self._act(
            self.a1_sp.id, self.sch_a2, "school_visit", status="scheduled"
        )
        Activity.objects.filter(id=informed.id).update(ssa_alignment="priority")
        Activity.objects.filter(id=uninformed.id).update(ssa_alignment="no_focus")
        Activity.objects.filter(responsible_staff_id=self.b1_sp.id).update(
            ssa_alignment="priority"
        )
        ctx = DashboardContext(self.pl_a, FY)
        result = S.ssa_informed_plans(ctx)
        self.assertEqual(
            [(r["name"], r["judged"], r["rate"]) for r in result["rows"]],
            [("CCEO A1", 2, 50)],
        )

    def test_priorities_view_survives_a_failing_guidance_summary(self):
        with patch(
            "apps.cce_leadership.guidance.guidance_summary",
            side_effect=RuntimeError("boom"),
        ):
            data = self._dash(self.pl_a, view="priorities")
        self.assertEqual(data["guidance"]["issued"], 0)
        self.assertEqual(data["guidance_url"], "/priorities/guidance")

    # ── Programmes view ──────────────────────────────────────────────────────
    def test_pl_dashboard_excludes_other_pl_portfolio(self):
        d = self._dash(self.pl_a, view="programmes")
        urgent = {r["school"] for r in d["urgent_schools"]}
        self.assertIn("School A2", urgent)
        self.assertNotIn("School B1", urgent)

    def test_ssa_rollout_counts_each_school_once_in_its_furthest_state(self):
        SsaRecord.objects.create(
            school=self.sch_a1,
            date_of_ssa=timezone.now(),
            fy=FY,
            quarter="Q1",
            verification_status="pending",
            uploaded_by="ia",
        )
        SsaRecord.objects.create(
            school=self.sch_a1,
            date_of_ssa=timezone.now(),
            fy=FY,
            quarter="Q2",
            verification_status="confirmed",
            uploaded_by="ia",
        )
        self._act(self.a1_sp.id, self.sch_a2, "baseline_ssa_visit", status="scheduled")
        rollout = self._dash(self.pl_a, view="programmes")["ssa_rollout"]
        self.assertEqual(
            {
                k: rollout[k]
                for k in ("portfolio", "confirmed", "submitted", "scheduled")
            },
            {"portfolio": 2, "confirmed": 1, "submitted": 0, "scheduled": 1},
        )
        self.assertEqual(rollout["not_planned"], 0)

    def test_urgent_queue_distinguishes_personal_and_supervised_ownership(self):
        own_school = self._school("PL-OWN", self.dist_a, ssa_done=False)
        StaffSchoolAssignment.objects.create(
            staff=self.pl_a_sp, school_id=own_school.id
        )

        rows = {
            row["school"]: row
            for row in self._dash(self.pl_a, view="programmes")["urgent_schools"]
        }

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

        # The follow-up now shows on the Team view's "Follow-ups you sent".
        follow_ups = self._dash(self.pl_a, view="team")["follow_ups"]
        self.assertEqual(follow_ups["active"], 1)
        self.assertEqual(follow_ups["rows"][0]["recipient"], "CCEO A1")

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

    # ── Collaboration view ───────────────────────────────────────────────────
    def test_partner_delivery_late_counts_the_team_s_partner_work_only(self):
        past = timezone.localdate() - timedelta(days=5)
        self._act(
            None,
            self.sch_a2,
            "training",
            delivery_type="partner",
            status="scheduled",
            monitored_by_staff_id=self.a1_sp.id,
            planned_date=past,
        )
        self._act(
            None,
            self.sch_b1,
            "training",
            delivery_type="partner",
            status="scheduled",
            monitored_by_staff_id=self.b1_sp.id,
            planned_date=past,
        )
        data = self._dash(self.pl_a, view="collaboration")
        self.assertEqual(data["collaboration"]["partner_delivery"]["late"], 1)
        self.assertEqual(data["collaboration_urls"]["partners"], "/partner-oversight/")

    # ── Links ────────────────────────────────────────────────────────────────
    def test_every_view_links_only_to_pages_that_exist_and_the_lead_holds(self):
        self.client.force_login(self.pl_a)
        for view in (
            "map",
            "priorities",
            "team",
            "coaching",
            "programmes",
            "collaboration",
        ):
            with self.subTest(view=view):
                response = self.client.get("/dashboard", {"fy": FY, "view": view})
                self.assertEqual(response.status_code, 200)
                html = response.content.decode()
                if view != "map":
                    self.assertIn(f'data-pl-view="{view}"', html)
                for href in self._hrefs(html):
                    path = href.split("?")[0]
                    for closed in CLOSED_PATHS:
                        self.assertFalse(
                            path.startswith(closed), f"{view} links to {href}"
                        )
                    if path.startswith(("/static/", "/media/")):
                        continue
                    try:
                        resolve(path)
                    except Resolver404:
                        self.fail(
                            f"{view} view links to {href}, which does not resolve"
                        )

    # ── Approvals ────────────────────────────────────────────────────────────
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

    # ── Supervision To-Dos close themselves ──────────────────────────────────
    def test_dashboard_todos_auto_close_after_workflow_action(self):
        from apps.analytics.pl_analytics_service import PLAnalyticsService

        def ssa_rows():
            return [
                t
                for t in PLAnalyticsService.pl_todos(self.pl_a, fy=FY)
                if "SSA" in t["title"]
            ]

        self.assertTrue(ssa_rows())
        # Resolve the underlying state: every school gets verified SSA.
        School.objects.filter(id__in=[self.sch_a1.id, self.sch_a2.id]).update(
            current_fy_ssa_status="done"
        )
        for school in (self.sch_a1, self.sch_a2):
            SsaRecord.objects.create(
                school=school,
                date_of_ssa=timezone.now(),
                fy=FY,
                quarter="Q3",
                verification_status="confirmed",
                uploaded_by="ia",
            )
        self.assertFalse([t for t in ssa_rows() if "collection" in t["title"].lower()])


@override_settings(CACHES=LOCMEM, DASHBOARD_CACHE_SECONDS=0)
class PLDashboardQueryBudgetTest(TestCase):
    """What one dashboard response costs, per view, and how it grows.

    A ceiling, never a target. The fixed part is built on every full page; a
    tab click builds its view alone. The cache is off so every measurement is
    a real build, and a process-owned cache keeps the shared dev Redis out of
    the count.
    """

    #: Measured 2026-09-13 against this fixture with one officer; headroom
    #: covers unrelated growth in the shared helpers the views call.
    #: Each view is measured alone, so it includes the dozen reads that
    #: resolve the lead's team and portfolio (the map view builds nothing
    #: else: measured 13; team 32; coaching 28; programmes 53).
    FIXED_CEILING = 75
    VIEW_CEILINGS = {
        "map": 16,
        "priorities": 24,
        "team": 40,
        "coaching": 35,
        "programmes": 65,
        "collaboration": 30,
    }
    #: Queries each additional officer may add to a build. The compact roster
    #: reads one PLAnalyticsService.cceo_performance row per officer; nothing
    #: else on the page may scale with the team.
    PER_OFFICER = 3

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="QB Region")
        cls.district = District.objects.create(name="QB District", region=cls.region)
        cls.pl = User.objects.create_user(
            email="qb-pl@t.org",
            name="QB Lead",
            roles=["Program Lead"],
            active_role="Program Lead",
            password="x",
            is_active=True,
        )
        cls.pl_sp = StaffProfile.objects.create(user=cls.pl, title="PL")
        cls.serial = 0
        cls._officer()

    @classmethod
    def _officer(cls):
        cls.serial += 1
        n = cls.serial
        user = User.objects.create_user(
            email=f"qb-cceo-{n}@t.org",
            name=f"QB Officer {n}",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        sp = StaffProfile.objects.create(user=user, title="CCEO")
        StaffSupervisorAssignment.objects.create(supervisor=cls.pl_sp, supervisee=sp)
        school = School.objects.create(
            school_id=f"QB-{n}",
            name=f"QB School {n}",
            region=cls.region,
            district=cls.district,
        )
        StaffSchoolAssignment.objects.create(staff=sp, school_id=school.id)
        Activity.objects.create(
            school=school,
            activity_type="training",
            delivery_type="staff",
            status="completed",
            responsible_staff_id=sp.id,
            fy=FY,
            quarter="Q3",
            planned_date=date(2026, 4, 10),
        )
        WeeklyFundRequest.objects.create(
            fy=FY,
            week_start_date=date(2026, 7, 6) + timedelta(days=7 * n),
            week_end_date=date(2026, 7, 12) + timedelta(days=7 * n),
            responsible_user=user.id,
            total_amount=10_000,
            status="submitted_to_pl",
        )

    def _build(self, view, include_fixed=True):
        with CaptureQueriesContext(connection) as captured:
            S._get_dashboard_uncached(
                self.pl, fy=FY, view=view, include_fixed=include_fixed
            )
        return len(captured.captured_queries)

    def test_the_fixed_part_stays_within_its_ceiling(self):
        fixed = self._build("map") - self._build("map", include_fixed=False)
        self.assertLessEqual(fixed, self.FIXED_CEILING)

    def test_each_view_alone_stays_within_its_ceiling(self):
        for view, ceiling in self.VIEW_CEILINGS.items():
            with self.subTest(view=view):
                count = self._build(view, include_fixed=False)
                self.assertLessEqual(
                    count, ceiling, f"the {view} view cost {count} queries"
                )

    def test_a_larger_team_adds_at_most_a_few_queries_per_officer(self):
        before = {
            view: self._build(view) for view in ("team", "coaching", "collaboration")
        }
        for _ in range(4):
            self._officer()
        for view, baseline in before.items():
            with self.subTest(view=view):
                grown = self._build(view)
                self.assertLessEqual(
                    grown - baseline,
                    4 * self.PER_OFFICER,
                    f"the {view} page grew from {baseline} to {grown} queries "
                    "for four more officers",
                )
