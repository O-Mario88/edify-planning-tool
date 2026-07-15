"""Team Targets Dashboard — the PL supervision cockpit (mandate §38).

Covers: strict supervision scoping (no other PL's team, no PL self-mixing),
aggregation from individual My Targets ledgers, validity rules per official
target area, partner no-double-count, pace-aware risk with leave adjustment,
the catch-up plan workflow (planning items + budget lines), credit reversal,
quick-action route validity, HTMX scope enforcement, and export scoping.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import (
    Leave,
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
)
from apps.activities.models import Activity
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.partners.models import Partner
from apps.schools.models import School
from apps.ssa.models import SsaRecord
from apps.targets.fy_calendar import FinancialYearCalendarService as Cal
from apps.targets.models import (
    MonthlyPersonalTarget,
    MostSignificantChangeStory,
    TargetAchievementLedger,
    TargetArea,
)
from apps.targets.my_targets import TargetAchievementService
from apps.targets.team_targets import (
    PLCatchUpPlanService,
    PLTeamTargetsService,
    team_status_display,
)

User = get_user_model()
FY = "2026"
TODAY = date(2026, 7, 15)  # July → month 10, Q4; pace = 11/23 wd ≈ 48%
JULY = 10


def _fixed_current(at=None):
    return {
        "today": TODAY,
        "fy": FY,
        "month_of_fy": JULY,
        "quarter": "Q4",
        "month_label": "July 2026",
    }


class TeamTargetsPageTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="R")
        self.district = District.objects.create(
            name="D-Primary", region=self.region, district_type="primary"
        )
        self.pl, self.pl_sp = self._staff(
            "pl-a@t.org", "PL Alpha", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.other_pl, self.other_pl_sp = self._staff(
            "pl-b@t.org", "PL Beta", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.cceo1, self.cceo1_sp = self._staff(
            "c1@t.org", "Grace One", EdifyRole.CCEO.value
        )
        self.cceo2, self.cceo2_sp = self._staff(
            "c2@t.org", "James Two", EdifyRole.CCEO.value
        )
        self.foreign, self.foreign_sp = self._staff(
            "c3@t.org", "Other Three", EdifyRole.CCEO.value
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_sp, supervisee=self.cceo1_sp
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_sp, supervisee=self.cceo2_sp
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.other_pl_sp, supervisee=self.foreign_sp
        )
        self.school = School.objects.create(
            school_id="TT-S1",
            name="Team School One",
            region=self.region,
            district=self.district,
            current_fy_ssa_status="done",
        )
        StaffSchoolAssignment.objects.create(
            staff=self.cceo1_sp, school_id=self.school.id
        )
        self._current = patch.object(Cal, "current", side_effect=_fixed_current)
        self._current.start()
        self.addCleanup(self._current.stop)

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

    def _monthly(self, user, area_key, month, target):
        MonthlyPersonalTarget.objects.update_or_create(
            user_id=user.id,
            area=TargetArea.objects.get(key=area_key),
            fy=FY,
            month_of_fy=month,
            defaults={"target": target},
        )

    def _act(
        self,
        sp,
        planned,
        atype="school_visit",
        # Target credit requires IA verification (§8): a "done, credited"
        # fixture activity must be IA-verified, not merely "completed".
        status="ia_verified",
        sf_id="SF-OK",
        delivery="staff",
        partner=None,
    ):
        return Activity.objects.create(
            school=self.school,
            activity_type=atype,
            delivery_type=delivery,
            status=status,
            responsible_staff_id=sp.id,
            fy=FY,
            quarter=Cal.quarter_of_month(Cal.month_of_fy_for(planned, FY) or 1),
            planned_date=planned,
            salesforce_activity_id=sf_id,
            assigned_partner_id=partner.id if partner else None,
            scheduled_date=timezone.make_aware(
                timezone.datetime(planned.year, planned.month, planned.day, 9)
            ),
        )

    def _page(self, user=None):
        return PLTeamTargetsService.get_page(user or self.pl)

    def _area(self, page, key):
        return next(k for k in page["key_progress"] if k["key"] == key)

    # ── 1–3: scope ───────────────────────────────────────────────────────────
    def test_pl_team_targets_shows_only_supervised_cceos(self):
        names = [m["name"] for m in self._page()["members"]]
        self.assertEqual(sorted(names), ["Grace One", "James Two"])
        self.assertNotIn("Other Three", names)

    def test_pl_cannot_see_other_pl_team(self):
        c = Client()
        c.force_login(self.pl)
        html = c.get("/team-targets").content.decode()
        self.assertNotIn("Other Three", html)
        resp = c.get(f"/team-targets/staff-drawer?staff={self.foreign.id}")
        self.assertEqual(resp.status_code, 403)

    def test_pl_personal_targets_not_mixed_into_team_targets(self):
        self._monthly(self.pl, "school_visits", JULY, 9)
        self._act(self.pl_sp, date(2026, 7, 6))
        TargetAchievementService.rebuild(self.pl, FY)
        page = self._page()
        self.assertNotIn("PL Alpha", [m["name"] for m in page["members"]])
        visits = self._area(page, "school_visits")
        self.assertEqual((visits["target"], visits["achieved"]), (0, 0))

    # ── 4–6: period + areas ──────────────────────────────────────────────────
    def test_default_period_is_current_month(self):
        page = self._page()
        self.assertEqual(page["month_of_fy"], JULY)
        self.assertEqual(page["month_label"], "July 2026")
        self.assertEqual(page["quarter"], "Q4")

    def test_mid_year_not_rendered(self):
        c = Client()
        c.force_login(self.pl)
        self.assertNotIn("Mid-Year", c.get("/team-targets").content.decode())
        matrix = c.get("/team-targets/matrix").content.decode()
        self.assertNotIn("Mid-Year", matrix)
        for q in ("Q1", "Q2", "Q3", "Q4"):
            self.assertIn(q, matrix)

    def test_only_five_official_target_areas_used(self):
        page = self._page()
        self.assertEqual(
            [a["key"] for a in page["areas"]],
            [
                "school_visits",
                "cluster_meetings",
                "cluster_trainings",
                "ssa_completed",
                "mscs",
            ],
        )
        c = Client()
        c.force_login(self.pl)
        html = c.get("/team-targets").content.decode()
        for wrong in (
            "Plan Approvals",
            "Fund Requests Reviewed",
            "Follow-Ups Closed",
            "Salesforce Logging",
        ):
            self.assertNotIn(wrong, html)

    # ── 7: aggregation ───────────────────────────────────────────────────────
    def test_team_target_aggregates_individual_my_targets(self):
        self._monthly(self.cceo1, "school_visits", JULY, 4)
        self._monthly(self.cceo2, "school_visits", JULY, 6)
        self._act(self.cceo1_sp, date(2026, 7, 2))
        self._act(self.cceo1_sp, date(2026, 7, 3), sf_id="SF-2")
        self._act(self.cceo2_sp, date(2026, 7, 6), sf_id="SF-3")
        page = self._page()
        visits = self._area(page, "school_visits")
        self.assertEqual((visits["target"], visits["achieved"]), (10, 3))
        monthly_kpi = next(k for k in page["kpis"] if k["key"] == "monthly")
        self.assertEqual(monthly_kpi["value"], "30%")

    def test_team_member_filter_recalculates_the_entire_reporting_scope(self):
        self._monthly(self.cceo1, "school_visits", JULY, 4)
        self._monthly(self.cceo2, "school_visits", JULY, 6)
        self._act(self.cceo1_sp, date(2026, 7, 2))
        self._act(self.cceo2_sp, date(2026, 7, 3), sf_id="SF-C2")

        page = PLTeamTargetsService.get_page(self.pl, team_member=str(self.cceo1.id))

        self.assertEqual([m["name"] for m in page["members"]], ["Grace One"])
        visits = self._area(page, "school_visits")
        self.assertEqual((visits["target"], visits["achieved"]), (4, 1))
        self.assertEqual(page["team_size"], 1)
        self.assertEqual(page["overall_team_size"], 2)

    def test_district_filter_uses_assigned_school_portfolios(self):
        page = PLTeamTargetsService.get_page(self.pl, district=self.district.name)

        self.assertEqual([m["name"] for m in page["members"]], ["Grace One"])
        self.assertIn(self.district.name, page["district_options"])
        self.assertEqual(page["selected_district"], self.district.name)

    def test_target_category_filter_uses_only_the_selected_official_area(self):
        self._monthly(self.cceo1, "school_visits", JULY, 4)
        self._monthly(self.cceo1, "mscs", JULY, 1)
        self._act(self.cceo1_sp, date(2026, 7, 2))

        page = PLTeamTargetsService.get_page(self.pl, category="school_visits")

        self.assertEqual(page["selected_category"], "school_visits")
        self.assertEqual(
            [row["key"] for row in page["key_progress"]], ["school_visits"]
        )
        monthly_kpi = next(k for k in page["kpis"] if k["key"] == "monthly")
        self.assertEqual(monthly_kpi["value"], "25%")

    def test_team_targets_filter_bar_exposes_the_five_reporting_filters(self):
        client = Client()
        client.force_login(self.pl)
        html = client.get("/team-targets").content.decode()

        for field in ("fy", "month", "category", "district", "team_member"):
            self.assertIn(f'name="{field}"', html)
        self.assertIn('id="team-targets-workspace"', html)
        self.assertNotIn("Search team member", html)

    def test_team_targets_renders_accessible_mobile_performance_cards(self):
        self._monthly(self.cceo1, "school_visits", JULY, 4)
        client = Client()
        client.force_login(self.pl)

        html = client.get("/team-targets").content.decode()

        self.assertIn('class="tt-mobile-performance"', html)
        self.assertIn(
            'aria-label="Open Grace One validated achievement, pace, and blockers"',
            html,
        )
        self.assertIn("Target-area breakdown", html)
        member = next(m for m in self._page()["members"] if m["name"] == "Grace One")
        self.assertEqual(
            [cell["key"] for cell in member["mobile_cells"]],
            ["month", "Q4", "fy"],
        )

    def test_expanded_staff_breakdown_matches_all_six_reporting_periods(self):
        self._monthly(self.cceo1, "school_visits", 1, 6)
        self._monthly(self.cceo1, "school_visits", JULY, 4)
        self._act(self.cceo1_sp, date(2025, 10, 2), sf_id="SF-Q1")
        self._act(self.cceo1_sp, date(2026, 7, 2), sf_id="SF-Q4")

        page = self._page()
        grace = next(
            member for member in page["members"] if member["name"] == "Grace One"
        )
        visits = next(
            area for area in grace["area_matrix"] if area["key"] == "school_visits"
        )

        self.assertEqual(
            [period["key"] for period in visits["periods"]],
            ["month", "Q1", "Q2", "Q3", "Q4", "fy"],
        )
        self.assertEqual(
            [(period["achieved"], period["target"]) for period in visits["periods"]],
            [(1, 4), (1, 6), (0, 0), (0, 0), (1, 4), (2, 10)],
        )

        client = Client()
        client.force_login(self.pl)
        html = client.get("/team-targets").content.decode()
        self.assertIn('class="tt-area-matrix"', html)
        self.assertIn("target-area performance by reporting period", html)
        self.assertIn(f'aria-controls="tt-desktop-areas-{self.cceo1.id}"', html)
        self.assertIn('class="tt-mobile-area__periods"', html)

    def test_performance_statuses_use_the_five_scannable_display_states(self):
        self.assertEqual(
            team_status_display("Slightly Behind", "warning"),
            ("Needs Attention", "warning"),
        )
        self.assertEqual(
            team_status_display("High Risk", "danger"),
            ("Needs Attention", "warning"),
        )
        self.assertEqual(
            team_status_display("Not Started", "neutral"), ("Upcoming", "info")
        )
        self.assertEqual(
            team_status_display("On Track", "success"), ("On Track", "success")
        )
        self.assertEqual(
            team_status_display("Not Assigned", "neutral"),
            ("Not Assigned", "neutral"),
        )
        self.assertEqual(
            team_status_display("Critical", "danger"), ("Critical", "danger")
        )

    def test_target_area_progress_drills_into_only_the_clicked_area(self):
        self._monthly(self.cceo1, "school_visits", JULY, 4)
        self._monthly(self.cceo1, "cluster_meetings", JULY, 2)
        client = Client()
        client.force_login(self.pl)

        response = client.get(
            "/team-targets/matrix",
            {"fy": FY, "month": JULY, "area": "school_visits"},
        )
        html = response.content.decode()
        payload = PLTeamTargetsService.matrix(
            self.pl,
            fy=FY,
            month_of_fy=JULY,
            area="school_visits",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["selected_area_label"], "School Visits")
        self.assertTrue(payload["rows"])
        self.assertEqual({row["area"] for row in payload["rows"]}, {"School Visits"})
        self.assertIn("School Visits · Team Progress", html)
        self.assertNotIn("Cluster Meetings · Team Progress", html)

    def test_target_area_progress_uses_the_wide_workspace_drawer_only(self):
        client = Client()
        client.force_login(self.pl)

        matrix = client.get(
            "/team-targets/matrix",
            {"fy": FY, "month": JULY, "area": "school_visits"},
        )
        staff = client.get(f"/team-targets/staff-drawer?staff={self.cceo1.id}")

        self.assertEqual(matrix.context["drawer_size"], "workspace")
        self.assertIn("size: 'workspace'", matrix.content.decode())
        self.assertNotIn("size: 'workspace'", staff.content.decode())

    def test_current_quarter_is_visually_and_textually_identified(self):
        self._monthly(self.cceo1, "school_visits", JULY, 4)
        client = Client()
        client.force_login(self.pl)

        html = client.get("/team-targets", {"fy": FY, "month": JULY}).content.decode()

        self.assertIn("is-current-quarter", html)
        self.assertIn("Current quarter", html)

    def test_performance_rows_expand_as_a_single_disclosure_and_keep_review_separate(
        self,
    ):
        self._monthly(self.cceo1, "school_visits", JULY, 4)
        client = Client()
        client.force_login(self.pl)

        html = client.get("/team-targets", {"fy": FY, "month": JULY}).content.decode()

        self.assertIn('class="tt-matrix__action-head"', html)
        self.assertIn('class="tt-matrix__action-cell"', html)
        self.assertIn('class="tt-row-action"', html)
        self.assertIn("validated achievement, pace, and blockers", html)
        self.assertIn('@click="expandedStaff = expandedStaff ===', html)
        self.assertIn("@click.window=", html)
        self.assertIn('colspan="8"', html)

    def test_team_targets_uses_an_accessible_line_chart_without_weekly_pacing(self):
        self._monthly(self.cceo1, "school_visits", JULY, 4)
        self._act(self.cceo1_sp, date(2026, 7, 2))
        client = Client()
        client.force_login(self.pl)

        response = client.get("/team-targets")
        html = response.content.decode()
        page = self._page()

        self.assertIn('class="tt-line-chart"', html)
        self.assertIn('class="tt-line-chart__series"', html)
        self.assertIn("Monthly team performance values", html)
        self.assertNotIn("Weekly pacing", html)
        self.assertNotIn("pacing", page)
        self.assertTrue(page["team_trend_segments"])
        july = next(point for point in page["team_trend"] if point["selected"])
        self.assertEqual(july["pct"], 25)
        self.assertIsNotNone(july["x"])
        self.assertIsNotNone(july["y"])

    # ── 8–12: validity per area ──────────────────────────────────────────────
    def test_team_visit_target_counts_only_valid_visits(self):
        self._monthly(self.cceo1, "school_visits", JULY, 4)
        self._act(self.cceo1_sp, date(2026, 7, 2), status="scheduled", sf_id="")
        # Completed + SF ID but pre-IA → still provisional, not counted (§8).
        self._act(self.cceo1_sp, date(2026, 7, 3), status="completed", sf_id="SF-8")
        self.assertEqual(self._area(self._page(), "school_visits")["achieved"], 0)
        # Only an IA-verified visit is credited.
        self._act(self.cceo1_sp, date(2026, 7, 6), status="ia_verified", sf_id="SF-9")
        self.assertEqual(self._area(self._page(), "school_visits")["achieved"], 1)

    def test_team_cluster_meeting_target_counts_only_valid_meetings(self):
        self._monthly(self.cceo1, "cluster_meetings", JULY, 2)
        self._act(self.cceo1_sp, date(2026, 7, 2), atype="cluster_meeting", sf_id="")
        self.assertEqual(self._area(self._page(), "cluster_meetings")["achieved"], 0)
        self._act(
            self.cceo1_sp, date(2026, 7, 6), atype="cluster_meeting", sf_id="SF-CM"
        )
        self.assertEqual(self._area(self._page(), "cluster_meetings")["achieved"], 1)

    def test_team_cluster_training_counts_only_valid_trainings(self):
        self._monthly(self.cceo1, "cluster_trainings", JULY, 2)
        self._act(
            self.cceo1_sp,
            date(2026, 7, 2),
            atype="cluster_training",
            status="scheduled",
            sf_id="",
        )
        self.assertEqual(self._area(self._page(), "cluster_trainings")["achieved"], 0)
        self._act(
            self.cceo1_sp, date(2026, 7, 6), atype="cluster_training", sf_id="SF-CT"
        )
        self.assertEqual(self._area(self._page(), "cluster_trainings")["achieved"], 1)

    def test_team_ssa_counts_only_ia_verified_ssa(self):
        self._monthly(self.cceo1, "ssa_completed", JULY, 2)
        rec = SsaRecord.objects.create(
            school=self.school,
            fy=FY,
            quarter="Q4",
            date_of_ssa=timezone.make_aware(timezone.datetime(2026, 7, 6, 10)),
            verification_status="pending",
            collected_by_user_id=self.cceo1.id,
            uploaded_by=self.cceo1.id,
        )
        self.assertEqual(self._area(self._page(), "ssa_completed")["achieved"], 0)
        SsaRecord.objects.filter(id=rec.id).update(verification_status="confirmed")
        self.assertEqual(self._area(self._page(), "ssa_completed")["achieved"], 1)

    def test_team_mscs_counts_only_approved_mscs(self):
        self._monthly(self.cceo1, "mscs", JULY, 1)
        story = MostSignificantChangeStory.objects.create(
            user_id=self.cceo1.id,
            title="Story",
            narrative="…",
            story_date=date(2026, 7, 8),
            status="submitted",
        )
        self.assertEqual(self._area(self._page(), "mscs")["achieved"], 0)
        story.status = "approved"
        story.save(update_fields=["status"])
        self.assertEqual(self._area(self._page(), "mscs")["achieved"], 1)

    # ── 13–14: compliance + partner rules ────────────────────────────────────
    def test_activity_sf_id_compliance_is_not_target_area(self):
        page = self._page()
        self.assertNotIn("Activity SF ID", [k["label"] for k in page["key_progress"]])
        sf_kpi = next(k for k in page["kpis"] if k["key"] == "sfid")
        self.assertEqual(sf_kpi["label"], "Activity SF ID Compliance")

    def test_partner_activity_not_double_counted(self):
        partner = Partner.objects.create(name="Helper Org", region_name="R")
        self._monthly(self.cceo1, "school_visits", JULY, 4)
        a = self._act(
            self.cceo1_sp, date(2026, 7, 6), delivery="partner", partner=partner
        )
        Activity.objects.filter(id=a.id).update(monitored_by_staff_id=self.cceo1_sp.id)
        page = self._page()
        self.assertEqual(
            self._area(page, "school_visits")["achieved"], 0
        )  # no CCEO credit
        self.assertEqual(
            TargetAchievementLedger.objects.filter(source_id=a.id).count(), 0
        )
        prow = next(p for p in page["partners"] if p["name"] == "Helper Org")
        self.assertEqual((prow["assigned"], prow["valid"]), (1, 1))  # shown separately

    # ── 15–16: pace + leave ──────────────────────────────────────────────────
    def test_staff_risk_uses_expected_pace(self):
        # pace ≈ 48% mid-July: 5/10=50% On Track · 4/10 Slightly Behind ·
        # 3/10 High Risk · 0/10 Critical
        self._monthly(self.cceo1, "school_visits", JULY, 10)
        self._monthly(self.cceo2, "school_visits", JULY, 10)
        for i in (2, 3, 6, 7, 8):
            self._act(self.cceo1_sp, date(2026, 7, i), sf_id=f"SF-{i}")
        for i in (2, 3, 6, 7):
            self._act(self.cceo2_sp, date(2026, 7, i), sf_id=f"SF-B{i}")
        members = {m["name"]: m for m in self._page()["members"]}
        self.assertEqual(members["Grace One"]["status"], "On Track")
        self.assertEqual(members["James Two"]["status"], "Slightly Behind")
        Activity.objects.filter(responsible_staff_id=self.cceo2_sp.id).delete()
        for i in (2, 3, 6):
            self._act(self.cceo2_sp, date(2026, 7, i), sf_id=f"SF-C{i}")
        members = {m["name"]: m for m in self._page()["members"]}
        self.assertEqual(members["James Two"]["status"], "High Risk")

    def test_leave_adjusts_pace_not_target_without_adjustment(self):
        self._monthly(self.cceo1, "school_visits", JULY, 10)
        self._monthly(self.cceo2, "school_visits", JULY, 10)
        Leave.objects.create(
            staff=self.cceo1_sp,
            type="annual",
            status="approved",
            start_date="2026-07-01",
            end_date="2026-07-14",
            days=10,
        )
        members = {m["name"]: m for m in self._page()["members"]}
        on_leave, working = members["Grace One"], members["James Two"]
        self.assertEqual(on_leave["month_target"], 10)  # target NOT reduced
        self.assertLess(on_leave["pace"], working["pace"])  # pace expectation is
        self.assertNotEqual(on_leave["status"], "Critical")  # leave-adjusted
        self.assertEqual(working["status"], "Critical")

    # ── 17–18: catch-up plan workflow ────────────────────────────────────────
    def test_recovery_plan_creates_planning_items(self):
        plan = PLCatchUpPlanService.submit(
            self.pl,
            staff_user_id=self.cceo1.id,
            area_key="school_visits",
            fy=FY,
            month_of_fy=JULY,
            count=1,
            school_ids=[self.school.school_id],
            note="Recover July visits",
        )
        self.assertEqual(plan.status, "submitted")
        result = PLCatchUpPlanService.approve(plan, self.pl)
        plan.refresh_from_db()
        self.assertEqual(plan.status, "approved")
        self.assertEqual(len(result["created"]), 1)
        act = Activity.objects.get(id=result["created"][0])
        self.assertEqual(act.status, "planned")  # entered Planning
        self.assertIsNone(act.scheduled_date)
        self.assertEqual(act.responsible_staff_id, self.cceo1_sp.id)

    def test_recovery_schedule_creates_budget_lines(self):
        from apps.budget.models import CostCatalogue, CostSetting

        catalogue, _ = CostCatalogue.objects.get_or_create(
            country="Uganda",
            fy=FY,
            version=1,
            defaults={"is_active": True, "label": "Test Catalogue"},
        )
        catalogue.is_active = True
        catalogue.save(update_fields=["is_active"])
        for key, cost in (
            ("staff_visit_transport_primary", 280000),
            ("lunch", 30000),
            ("primary_transport_per_day", 280000),
            ("primary_lunch_per_day", 30000),
        ):
            CostSetting.objects.update_or_create(
                key=key,
                defaults={
                    "label": key,
                    "unit_cost": cost,
                    "fy": FY,
                    "catalogue": catalogue,
                    "version": 1,
                },
            )
        plan = PLCatchUpPlanService.submit(
            self.pl,
            staff_user_id=self.cceo1.id,
            area_key="school_visits",
            fy=FY,
            month_of_fy=JULY,
            count=1,
            school_ids=[self.school.school_id],
            planned_dates=["2026-07-21"],
        )
        result = PLCatchUpPlanService.approve(plan, self.pl)
        plan.refresh_from_db()
        self.assertEqual(
            len(result["created"]), 1, f"scheduling path failed: {result['errors']}"
        )
        act = Activity.objects.get(id=result["created"][0])
        self.assertEqual(plan.status, "scheduled")
        self.assertIsNotNone(act.scheduled_date)
        self.assertGreater(act.schedule_cost_lines.count(), 0)  # budget lines exist

    # ── 19: reversal ─────────────────────────────────────────────────────────
    def test_target_credit_reversed_when_activity_returned(self):
        self._monthly(self.cceo1, "school_visits", JULY, 4)
        a = self._act(self.cceo1_sp, date(2026, 7, 6))
        self.assertEqual(self._area(self._page(), "school_visits")["achieved"], 1)
        Activity.objects.filter(id=a.id).update(status="returned_by_ia")
        page = self._page()
        self.assertEqual(self._area(page, "school_visits")["achieved"], 0)
        row = TargetAchievementLedger.objects.get(source_id=a.id)
        self.assertEqual(row.validation_status, "reversed")

    # ── 20–22: routes, HTMX scope, export ────────────────────────────────────
    def test_quick_actions_use_valid_routes(self):
        c = Client()
        c.force_login(self.pl)
        for url in (
            "/planning",
            "/team-targets/matrix",
            "/team-targets/recovery",
            "/team-targets/sfid-backlog",
            "/team-targets/export",
        ):
            self.assertNotEqual(c.get(url).status_code, 404, url)

    def test_htmx_team_target_endpoints_enforce_pl_scope(self):
        c = Client()
        c.force_login(self.other_pl)  # PL Beta must not touch PL Alpha's team
        self.assertEqual(
            c.get(f"/team-targets/staff-drawer?staff={self.cceo1.id}").status_code, 403
        )
        resp = c.post(
            "/team-targets/catchup",
            {
                "staff_user_id": self.cceo1.id,
                "area": "school_visits",
                "fy": FY,
                "month": JULY,
            },
        )
        self.assertEqual(resp.status_code, 403)
        plan = PLCatchUpPlanService.submit(
            self.pl,
            staff_user_id=self.cceo1.id,
            area_key="school_visits",
            fy=FY,
            month_of_fy=JULY,
            count=1,
        )
        resp = c.post(f"/team-targets/catchup/{plan.id}/action", {"action": "approve"})
        self.assertEqual(resp.status_code, 403)

    def test_export_contains_only_supervised_team(self):
        self._monthly(self.cceo1, "school_visits", JULY, 4)
        c = Client()
        c.force_login(self.pl)
        body = c.get(f"/team-targets/export?fy={FY}").content.decode()
        self.assertIn("Grace One", body)
        self.assertIn("James Two", body)
        self.assertNotIn("Other Three", body)
        self.assertNotIn("PL Alpha,School Visits", body)  # PL's own rows absent

    def test_export_honours_team_member_and_target_category_filters(self):
        self._monthly(self.cceo1, "school_visits", JULY, 4)
        client = Client()
        client.force_login(self.pl)

        body = client.get(
            "/team-targets/export",
            {
                "fy": FY,
                "month": JULY,
                "team_member": self.cceo1.id,
                "category": "school_visits",
            },
        ).content.decode()

        self.assertIn("Grace One,School Visits", body)
        self.assertNotIn("James Two", body)
        self.assertNotIn("Most Significant Change Stories", body)


class TeamTargetsTodoTest(TestCase):
    """§29 — PL To-Dos derive from team state and auto-close."""

    def setUp(self):
        self.region = Region.objects.create(name="R2")
        self.district = District.objects.create(
            name="D2", region=self.region, district_type="primary"
        )
        self.pl = User.objects.create_user(
            email="pl-t@t.org",
            name="PL Todo",
            roles=[EdifyRole.COUNTRY_PROGRAM_LEAD.value],
            active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            password="x",
            is_active=True,
        )
        self.pl_sp = StaffProfile.objects.create(user=self.pl, title="PL")
        self.cceo = User.objects.create_user(
            email="c-t@t.org",
            name="Cee Todo",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        self.cceo_sp = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_sp, supervisee=self.cceo_sp
        )
        self._current = patch.object(Cal, "current", side_effect=_fixed_current)
        self._current.start()
        self.addCleanup(self._current.stop)

    def test_high_risk_cceo_todo_appears_and_auto_closes(self):
        from apps.command_center.todo_service import get_todos

        MonthlyPersonalTarget.objects.create(
            user_id=self.cceo.id,
            area=TargetArea.objects.get(key="school_visits"),
            fy=FY,
            month_of_fy=JULY,
            target=10,
        )
        titles = [t["title"] for t in get_todos(self.pl)["todos"]]
        self.assertIn("Review high-risk CCEO — Cee Todo", titles)
        school = School.objects.create(
            school_id="TD-S1",
            name="Todo School",
            region=self.region,
            district=self.district,
            current_fy_ssa_status="done",
        )
        for i in (1, 2, 3, 6, 7):
            Activity.objects.create(
                school=school,
                activity_type="school_visit",
                delivery_type="staff",
                # IA-verified so the work is actually credited (§8) and the
                # CCEO recovers out of the high-risk band.
                status="ia_verified",
                responsible_staff_id=self.cceo_sp.id,
                fy=FY,
                quarter="Q4",
                planned_date=date(2026, 7, i),
                salesforce_activity_id=f"SF-T{i}",
                scheduled_date=timezone.make_aware(timezone.datetime(2026, 7, i, 9)),
            )
        titles = [t["title"] for t in get_todos(self.pl)["todos"]]
        self.assertNotIn("Review high-risk CCEO — Cee Todo", titles)  # recovered
