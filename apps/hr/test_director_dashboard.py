"""The Regional HR Director Dashboard, aligned with the role (2026-09-13).

The director works with the RVP and the Country Directors of a region to
staff, develop and care for its people, administering compensation, benefits,
leave, disciplinary matters, disputes and investigations, performance, morale,
safety and development, in compliance with each country's employment law. The
dashboard's figures used to match strings nothing writes and were partly
organisation-wide; these tests pin that every section reads the real records,
inside the director's countries, and that small groups stay anonymous.
"""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta

from django.test import TestCase

from apps.accounts.hr_dashboard_service import HRDashboardService
from apps.accounts.models import StaffProfile, User
from apps.hr.models import (
    ComplianceRequirement,
    EmployeeComplianceRecord,
    EmployeeRelationsCase,
    OffboardingPlan,
    PerformanceReview,
    PulseResponse,
    PulseSurvey,
    SafetyIncident,
    StaffRecognition,
    Vacancy,
)


def _person(email, role="CCEO", country="Uganda", department=None):
    user = User.objects.create_user(
        email=email,
        name=email.split("@")[0].replace("-", " ").title(),
        roles=[role],
        active_role=role,
        password="pwd",
        is_active=True,
        status="active",
    )
    profile = StaffProfile.objects.create(
        user=user,
        staff_number=email.split("@")[0].upper(),
        country=country,
        department=department,
    )
    return user, profile


def _pulse(survey, country, scores, n):
    already = PulseResponse.objects.filter(survey=survey).count()
    for index in range(already, already + n):
        PulseResponse.objects.create(
            survey=survey,
            respondent_key=f"respondent-{index}",
            country=country,
            scores=scores,
        )


class DirectorDashboardTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hr, cls.hr_sp = _person("dd-hr@edify.test", "HumanResources")
        cls.officer, cls.officer_sp = _person(
            "dd-officer@edify.test", department="Programmes"
        )
        cls.accountant, cls.accountant_sp = _person(
            "dd-accountant@edify.test", "Accountant", department="Finance"
        )
        cls.kenyan, cls.kenyan_sp = _person("dd-kenyan@edify.test", country="Kenya")

    def data(self, **filters):
        return HRDashboardService.get_dashboard(self.hr, **filters)

    def kpis(self, data):
        return {item["label"]: item["value"] for item in data["kpi_strip_items"]}

    # ── Reach ────────────────────────────────────────────────────────────────
    def test_every_section_stays_inside_the_directors_countries(self):
        Vacancy.objects.create(
            country="Uganda", department="Programmes", role="CCEO", status="open"
        )
        Vacancy.objects.create(
            country="Kenya", department="Programmes", role="CCEO", status="open"
        )
        for country in ("Uganda", "Kenya"):
            EmployeeRelationsCase.objects.create(
                country=country, case_type="grievance", description="A concern."
            )
            SafetyIncident.objects.create(
                country=country,
                incident_date=date.today(),
                category="injury",
                description="A fall.",
            )
        data = self.data()
        kpis = self.kpis(data)
        self.assertEqual(kpis["Active Employees"], "3")
        self.assertEqual(kpis["Open Positions"], "1")
        self.assertEqual(kpis["Open ER Cases"], "1")
        self.assertEqual(kpis["Open Safety Incidents"], "1")
        self.assertEqual(
            [row["country"] for row in data["workforce_by_country"]], ["Uganda"]
        )

    def test_a_filter_narrows_the_reach_and_never_widens_it(self):
        widened = self.data(country="Kenya")
        self.assertEqual(self.kpis(widened)["Active Employees"], "0")
        self.assertEqual(widened["workforce_by_country"], [])

        programmes = self.data(department="Programmes")
        self.assertEqual(self.kpis(programmes)["Active Employees"], "1")
        options = HRDashboardService.filter_options(self.hr)
        self.assertEqual(options["countries"], ["Uganda"])
        self.assertEqual(options["departments"], ["Finance", "Programmes"])

    # ── Staffing and retention ───────────────────────────────────────────────
    def test_turnover_counts_exits_and_names_voluntary_ones(self):
        from apps.core.fy import get_fy_date_range, get_operational_fy

        start, _ = get_fy_date_range(get_operational_fy())
        last_day = max(start.date(), date.today() - timedelta(days=1))
        OffboardingPlan.objects.create(
            staff=self.accountant_sp,
            last_working_day=last_day,
            exit_reason="dismissal",
            status="Closed",
        )
        OffboardingPlan.objects.create(
            staff=self.officer_sp,
            last_working_day=date.today() + timedelta(days=20),
            exit_reason="resignation",
        )
        uganda = self.data()["workforce_by_country"][0]
        self.assertEqual(uganda["leavers"], 1)
        self.assertEqual(uganda["voluntary"], 0, "a dismissal is not voluntary")
        self.assertEqual(uganda["leaving_soon"], 1)
        # One leaver among the three people employed this year.
        self.assertEqual(uganda["turnover"], 33.3)

    # ── Performance and talent ───────────────────────────────────────────────
    def test_the_review_cycle_reads_stages_and_final_ratings(self):
        fy = HRDashboardService.get_dashboard(self.hr)["fy"]
        PerformanceReview.objects.create(
            staff=self.officer_sp,
            period="FY",
            fy=fy,
            stage="closed",
            rating="exceeds",
            due_date=date.today() - timedelta(days=5),
        )
        PerformanceReview.objects.create(
            staff=self.accountant_sp,
            period="FY",
            fy=fy,
            stage="manager_assessment",
            due_date=date.today() - timedelta(days=2),
        )
        PerformanceReview.objects.create(
            staff=self.kenyan_sp,
            period="FY",
            fy=fy,
            stage="closed",
            rating="did_not_meet",
            due_date=date.today(),
        )
        performance = self.data()["performance"]
        stages = {row["key"]: row["count"] for row in performance["stages"]}
        self.assertEqual(stages["complete"], 1)
        self.assertEqual(stages["assessment"], 1)
        self.assertEqual(performance["overdue"], 1)
        ratings = {row["key"]: row["count"] for row in performance["ratings"]}
        self.assertEqual(ratings, {"exceeds": 1, "met": 0, "below": 0})

    # ── Wellbeing ────────────────────────────────────────────────────────────
    def test_morale_is_shown_only_above_the_anonymity_floor(self):
        survey = PulseSurvey.objects.create(
            title="Quarter pulse",
            countries=["Uganda", "Kenya"],
            opens_on=date.today() - timedelta(days=10),
            closes_on=date.today() - timedelta(days=1),
            status="closed",
        )
        scores = {
            "purpose": 5,
            "support": 4,
            "workload": 2,
            "recognition": 3,
            "growth": 4,
        }
        _pulse(survey, "Uganda", scores, 4)
        _pulse(survey, "Kenya", scores, 9)
        data = self.data()
        self.assertEqual(self.kpis(data)["Staff Morale"], "—")
        self.assertIsNone(data["motivation_rows"][0]["morale"])

        _pulse(survey, "Uganda", scores, 1)
        data = self.data()
        self.assertEqual(self.kpis(data)["Staff Morale"], "3.6")
        morale = data["motivation_rows"][0]["morale"]
        self.assertEqual(morale["responses"], 5, "Kenyan answers are not counted")
        self.assertEqual(morale["lowest"]["statement"], "My workload is manageable.")

    def test_low_morale_and_serious_incidents_reach_the_attention_band_first(self):
        survey = PulseSurvey.objects.create(
            title="Low pulse",
            countries=["Uganda"],
            opens_on=date.today() - timedelta(days=10),
            closes_on=date.today() - timedelta(days=1),
            status="closed",
        )
        _pulse(
            survey,
            "Uganda",
            {"purpose": 2, "support": 2, "workload": 1, "recognition": 2, "growth": 3},
            5,
        )
        SafetyIncident.objects.create(
            country="Uganda",
            incident_date=date.today(),
            category="road_traffic",
            severity="critical",
            description="Collision.",
        )
        PerformanceReview.objects.create(
            staff=self.officer_sp,
            period="FY",
            due_date=date.today() - timedelta(days=3),
        )
        titles = [item["title"] for item in self.data()["attention"]]
        self.assertTrue(titles[0].startswith("1 serious safety incident"))
        self.assertIn("Low staff morale in Uganda", titles)
        self.assertTrue(titles[-1].startswith("1 performance review overdue"))

    def test_recognition_and_cases_feed_the_country_signals(self):
        StaffRecognition.objects.create(
            staff=self.officer_sp,
            country="Uganda",
            category="teamwork",
            citation="Covered a colleague's schools.",
            awarded_on=date.today(),
        )
        EmployeeRelationsCase.objects.create(
            country="Uganda",
            case_type="disciplinary",
            description="Conduct.",
            is_confidential=True,
        )
        row = self.data()["motivation_rows"][0]
        self.assertEqual(row["recognitions"], 1)
        self.assertEqual(row["disciplinary"], 1, "confidential cases are counted")

    # ── Compliance ───────────────────────────────────────────────────────────
    def test_compliance_completion_counts_employees_with_no_evidence(self):
        requirement = ComplianceRequirement.objects.create(
            country="Uganda", name="Signed contract", is_mandatory=True
        )
        EmployeeComplianceRecord.objects.create(
            staff=self.officer_sp, requirement=requirement, status="Compliant"
        )
        data = self.data()
        # One compliant record; the director and the accountant have none.
        self.assertEqual(self.kpis(data)["Compliance Completion"], "33%")
        row = data["compliance_status"][0]
        self.assertEqual((row["compliant"], row["missing"]), (1, 2))


class DirectorDashboardPageTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hr, _ = _person("dp-hr@edify.test", "HumanResources")
        cls.officer, cls.officer_sp = _person("dp-officer@edify.test", department="Programmes")

    def setUp(self):
        self.client.force_login(self.hr)

    def test_the_page_follows_the_role_description(self):
        page = self.client.get("/dashboard?view=operations")
        self.assertEqual(page.status_code, 200)
        html = page.content.decode()
        self.assertIn("Regional HR Director Dashboard", html)
        order = [
            "People pulse",
            "Leadership Attention Required",
            "Staffing and retention",
            "Performance and talent",
            "Employee relations and wellbeing",
            "Policy and compliance",
            "Leave, pay and benefits",
        ]
        positions = [html.index(marker) for marker in order]
        self.assertEqual(positions, sorted(positions))
        for drawer in (
            'hx-get="/recruitment/new"',
            'hx-get="/employee-relations/new"',
            'hx-get="/health-safety/new"',
            'hx-get="/pulse-surveys/new"',
        ):
            self.assertIn(drawer, html)
        # The people and capacity signals from field debriefs are read here;
        # the HR sidebar leaves Field Debrief to the people who file them.
        self.assertIn("Field capacity signals", html)

    def test_filter_tabs_use_validated_values_and_reset_keeps_view(self):
        page = self.client.get("/dashboard?view=talent&fy=9999&country=Kenya&department=Unknown")
        self.assertEqual(page.status_code, 200)
        for tab in page.context["dashboard_tabs"]["tabs"]:
            self.assertNotIn("9999", tab["url"])
            self.assertNotIn("Kenya", tab["url"])
            self.assertNotIn("Unknown", tab["url"])
        self.assertContains(page, 'data-dashboard-live')
        self.assertContains(page, 'href="/dashboard?view=talent"')
        self.assertContains(page, 'edify-filter-field platform-filter-compact')

    def test_focused_workflows_render_only_the_selected_people_programme(self):
        sections = {"staffing": "staffing", "talent": "performance",
                    "wellbeing": "wellbeing", "compliance": "compliance", "rewards": "rewards"}
        for view, section in sections.items():
            with self.subTest(view=view):
                page = self.client.get(
                    f"/dashboard?fy=2026&country=Uganda&department=Programmes&view={view}",
                    HTTP_HX_TARGET="hr-dashboard-view-shell", HTTP_HX_REQUEST="true")
                self.assertEqual(page.status_code, 200)
                self.assertContains(page, f'data-hr-section="{section}"')
                for other in set(sections.values()) - {section}:
                    self.assertNotContains(page, f'data-hr-section="{other}"')
                self.assertContains(page, 'country=Uganda&amp;department=Programmes')
                self.assertContains(page, 'hx-swap-oob="outerHTML"')
                self.assertNotContains(page, '<html')
                self.assertEqual(page.cookies["edify_dashboard_view_hr"].value, view)
        remembered = self.client.get("/dashboard")
        self.assertEqual(remembered.context["dashboard_view"], "rewards")

    def test_the_export_carries_figures_never_names(self):
        OffboardingPlan.objects.create(
            staff=self.officer_sp,
            last_working_day=date.today() + timedelta(days=5),
            exit_reason="resignation",
        )
        PerformanceReview.objects.create(
            staff=self.officer_sp, period="FY", due_date=date.today()
        )
        response = self.client.get("/dashboard?export=csv")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        rows = list(csv.reader(io.StringIO(body)))
        self.assertEqual(rows[0], ["Section", "Metric", "Value", "Context"])
        self.assertIn("Staffing by country", {row[0] for row in rows[1:]})
        self.assertNotIn(self.officer.name, body)

    def test_the_map_is_still_one_tab_away(self):
        html = self.client.get("/dashboard?view=map").content.decode()
        self.assertIn("subregionMap()", html)
