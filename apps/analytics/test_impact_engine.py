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
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.analytics import impact_engine
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.core.navigation import build_analytics_sections
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


def _activity(
    school: School,
    fy: str,
    activity_type: str,
    *,
    delivery_type: str = "staff",
    focus: str | None = FOCUS,
    project: bool = False,
):
    return Activity.objects.create(
        school=school,
        activity_type=activity_type,
        status="ia_verified",
        planned_date=timezone.now().date() - timedelta(days=55),
        fy=fy,
        focus_intervention=focus,
        delivery_type=delivery_type,
        project_id="project-impact-test" if project else None,
        primary_driver_type="special_project" if project else "",
        activity_context_type="project" if project else "school",
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

    def test_five_programme_driver_correlations_use_verified_linked_work(self):
        for school in self.treated:
            _activity(school, self.fy, "partner_activity", delivery_type="partner")
            _activity(school, self.fy, "training")
            _activity(school, self.fy, "cluster_meeting")
            _activity(school, self.fy, "project_activity", project=True)
        # A legacy training without an SSA focus is not evidence for the
        # intervention-linked training question.
        _activity(self.untreated[0], self.fy, "training", focus=None)

        school_ids = [s.id for s in self.treated + self.untreated]
        imp = impact_engine.improvement_frame(school_ids, self.fy)
        acts = impact_engine.activity_frame(imp, school_ids)
        rows = {
            row["key"]: row
            for row in impact_engine.programme_driver_associations(imp, acts)
        }

        self.assertEqual(
            set(rows),
            {"partner", "training", "staff", "cluster_meeting", "special_project"},
        )
        self.assertEqual(rows["training"]["activities"], 10)
        for row in rows.values():
            self.assertGreater(row["correlation"]["rho"], 0)
            self.assertIsNotNone(row["correlation"]["ci_low"])
            self.assertIsNotNone(row["correlation"]["ci_high"])
            self.assertEqual(row["correlation"]["tests_run"], 5)
            self.assertLessEqual(
                row["correlation"]["p"], row["correlation"]["p_adjusted"]
            )
            self.assertGreaterEqual(row["schools_exposed"], 10)
            self.assertGreater(
                row["exposed_median_delta"], row["unexposed_median_delta"]
            )

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

    def test_lagging_reports_the_total_it_capped(self):
        """The table shows ten rows. It must say how many there were.

        A cap that hides rows without saying so is how somebody comes to
        believe they have seen every lagging district when they have seen ten
        of them. The engine carries the total so the page can state it.
        """
        school_ids = [s.id for s in self.treated + self.untreated]
        imp = impact_engine.improvement_frame(school_ids, self.fy)
        districts = {s.id: s.district.name for s in self.treated + self.untreated}
        geo = impact_engine.geographic_performance(imp, districts)

        self.assertIn("lagging_total", geo)
        self.assertEqual(geo["lagging_total"], len(geo["lagging"]))
        self.assertLessEqual(len(geo["lagging"]), impact_engine.LAGGING_SHOWN)

    def test_lagging_total_counts_past_the_cap(self):
        """The total is the count BEFORE the slice, not after it.

        Every ORM fixture in this file produces fewer lagging combinations than
        the cap, so a test built on one would assert `total == len(shown)` and
        pass whichever number the engine put there — the one thing this field
        exists for would go unchecked. Drive the engine with a frame that
        overshoots the cap instead: three districts of eight schools, every one
        of the eight interventions declining, is 24 combinations against a cap
        of 10.
        """
        rows = []
        school_id = 0
        districts = {}
        for district_index, district in enumerate(("Alpha", "Bravo", "Charlie")):
            for _ in range(impact_engine.MIN_GROUP_N):
                school_id += 1
                districts[school_id] = district
                for i, intervention in enumerate(impact_engine.ALL_INTERVENTIONS):
                    rows.append(
                        {
                            "school_id": school_id,
                            "intervention": intervention,
                            # Every cell gets its OWN median, comfortably past
                            # DECLINE_THRESHOLD. A single shared value would
                            # make the ordering assertion below hold whichever
                            # way the engine sorted, so it would check nothing.
                            "delta": -1.0
                            - district_index
                            - i * len(impact_engine.ALL_INTERVENTIONS) * 0.01,
                        }
                    )
        frame = impact_engine.pd.DataFrame(rows)

        geo = impact_engine.geographic_performance(frame, districts)

        combinations = 3 * len(impact_engine.ALL_INTERVENTIONS)
        self.assertEqual(geo["lagging_total"], combinations)
        self.assertEqual(len(geo["lagging"]), impact_engine.LAGGING_SHOWN)
        self.assertGreater(geo["lagging_total"], len(geo["lagging"]))
        # Worst first, so the ten shown are the ten steepest and not ten
        # arbitrary ones.
        deltas = [row["median_delta"] for row in geo["lagging"]]
        self.assertEqual(deltas, sorted(deltas))

    def test_empty_frame_still_reports_a_lagging_total(self):
        """The early return must carry the field too, or the page reads a
        missing key as an empty string and prints "The 0 steepest of "."""
        geo = impact_engine.geographic_performance(impact_engine.pd.DataFrame(), {})
        self.assertEqual(geo["lagging_total"], 0)

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

    def test_parish_grouping_is_offered_only_when_profile_data_exists(self):
        without_parish = {
            "school-1": {
                "pl": "PL A",
                "sub_region": "North",
                "district": "District A",
                "cluster": "Cluster A",
                "sub_county": "Sub-county A",
                "parish": "Unassigned parish",
            }
        }
        values = {
            option["value"]
            for option in impact_engine._group_options(without_parish, "district")
        }
        self.assertNotIn("parish", values)

        with_parish = {key: dict(value) for key, value in without_parish.items()}
        with_parish["school-1"]["parish"] = "Parish A"
        values = {
            option["value"]
            for option in impact_engine._group_options(with_parish, "parish")
        }
        self.assertIn("parish", values)

    def test_large_country_grouping_is_server_paginated(self):
        imp = impact_engine.pd.DataFrame(
            [
                {"school_id": f"school-{index}", "delta": index / 100}
                for index in range(25)
            ]
        )
        acts = impact_engine.pd.DataFrame(
            columns=[
                "activity_id",
                "school_id",
                "kind",
                "activity_type",
                "focus",
                "delivery_type",
                "is_special_project",
            ]
        )
        metadata = {
            f"school-{index}": {"district": f"District {index:02d}"}
            for index in range(25)
        }
        result = impact_engine.grouped_driver_associations(
            imp, acts, metadata, "district", page=2, page_size=20
        )
        self.assertEqual(result["total"], 25)
        self.assertEqual(result["total_pages"], 2)
        self.assertEqual(result["page"], 2)
        self.assertEqual(len(result["rows"]), 5)
        self.assertTrue(result["has_previous"])
        self.assertFalse(result["has_next"])


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

    def test_cceo_can_open_portfolio_scoped_analysis(self):
        client = Client()
        client.force_login(self.cceo)
        res = client.get("/impact")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["dashboard"]["coverage"]["schools_in_scope"], 0)

    def test_analytics_section_visibility_follows_permissions(self):
        """Impact Analytics is a section of the Analytics workspace now.

        The sidebar shows one Analytics entry for everyone who has any analysis
        access, so permission is expressed in the sections a role is offered —
        not in whether a link with this label exists.
        """
        cd_sections = build_analytics_sections(self.cd, "/impact")
        self.assertIn("Impact Analytics", [s["label"] for s in cd_sections])
        self.assertEqual(
            [s["label"] for s in cd_sections if s["active"]], ["Impact Analytics"]
        )
        for included in (self.cceo, self.accountant):
            labels = [
                s["label"] for s in build_analytics_sections(included, "/dashboard")
            ]
            self.assertIn("Impact Analytics", labels)

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

        other_region = Region.objects.create(name="RVP Other Region")
        other_district = District.objects.create(
            name="RVP Other District", region=other_region
        )
        other_school = School.objects.create(
            school_id="IMP-RVP-COUNTRY",
            name="RVP Country School",
            region=other_region,
            district=other_district,
        )
        _paired_ssa(other_school, self.fy, {FOCUS: 4.0}, {FOCUS: 5.0})
        country_dashboard = impact_engine.build_dashboard(rvp, {})
        self.assertEqual(country_dashboard["coverage"]["schools_paired"], 2)
        self.assertEqual(country_dashboard["filters"]["group_by"], "pl")


class ImpactPortfolioScopeTest(TestCase):
    def setUp(self):
        self.fy = get_operational_fy()
        region = Region.objects.create(name="Portfolio Impact Region")
        district = District.objects.create(
            name="Portfolio Impact District", region=region
        )
        self.pl = _user("impact-pl@edify.test", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        self.cceo = _user("impact-team@edify.test", EdifyRole.CCEO.value)
        self.other = _user("impact-other@edify.test", EdifyRole.CCEO.value)
        self.accountant = _user(
            "impact-country-acc@edify.test", EdifyRole.PROGRAM_ACCOUNTANT.value
        )
        self.pl_sp = StaffProfile.objects.create(user=self.pl, title="PL")
        self.cceo_sp = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        self.other_sp = StaffProfile.objects.create(user=self.other, title="CCEO")
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_sp, supervisee=self.cceo_sp
        )

        self.own = School.objects.create(
            school_id="IMPACT-PL-OWN", name="PL Own", region=region, district=district
        )
        self.team = School.objects.create(
            school_id="IMPACT-PL-TEAM", name="PL Team", region=region, district=district
        )
        self.outside = School.objects.create(
            school_id="IMPACT-OUTSIDE", name="Outside", region=region, district=district
        )
        StaffSchoolAssignment.objects.create(staff=self.pl_sp, school_id=self.own.id)
        StaffSchoolAssignment.objects.create(staff=self.cceo_sp, school_id=self.team.id)
        StaffSchoolAssignment.objects.create(
            staff=self.other_sp, school_id=self.outside.id
        )
        for school in (self.own, self.team, self.outside):
            _paired_ssa(school, self.fy, {FOCUS: 4.0}, {FOCUS: 5.0})

    def test_pl_sees_own_and_supervised_portfolios_only(self):
        dashboard = impact_engine.build_dashboard(self.pl, {})
        self.assertEqual(dashboard["coverage"]["schools_in_scope"], 2)
        self.assertEqual(dashboard["coverage"]["schools_paired"], 2)

    def test_field_staff_sees_only_own_portfolio(self):
        dashboard = impact_engine.build_dashboard(self.cceo, {})
        self.assertEqual(dashboard["coverage"]["schools_in_scope"], 1)
        self.assertEqual(dashboard["coverage"]["schools_paired"], 1)

    def test_accountant_sees_country_and_can_group_by_program_lead(self):
        dashboard = impact_engine.build_dashboard(self.accountant, {"group_by": "pl"})
        self.assertEqual(dashboard["coverage"]["schools_in_scope"], 3)
        self.assertEqual(dashboard["filters"]["group_by"], "pl")
        names = {row["name"] for row in dashboard["grouped_drivers"]}
        self.assertIn(self.pl.name, names)
