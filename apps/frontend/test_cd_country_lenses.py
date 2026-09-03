"""Country lenses that were quietly wrong for the CD (owner, 2026-09-03).

Coverage ignored the fiscal year; global search handed a CD other
countries' staff; the field-debrief KPIs stayed on a 30-day window while the
FY selector changed only the list; policy compliance counted its first
thousand rows and let a country-less CD see everyone.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole

User = get_user_model()


def _person(email, name, role, country="Uganda"):
    u = User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    if country is not None:
        StaffProfile.objects.create(user=u, title=role, country=country)
    return u


class CoverageFiscalYearTest(TestCase):
    def test_coverage_honours_the_fiscal_year_and_breaks_reach_down_by_district(self):
        from apps.activities.models import Activity
        from apps.geography.models import District, Region
        from apps.schools.models import School

        cd = _person("cov-cd@t.org", "Cov CD", EdifyRole.COUNTRY_DIRECTOR.value)
        region = Region.objects.create(name="Central")
        district = District.objects.create(name="Wakiso", region=region)
        school = School.objects.create(
            name="Cov School", district=district, region=region
        )
        fy = get_operational_fy()
        old_fy = str(int(fy) - 1)
        Activity.objects.create(
            activity_type="school_visit",
            status="completed",
            school=school,
            fy=old_fy,
            planned_date=date.today() - timedelta(days=400),
            responsible_staff_id=cd.id,
        )
        self.client.force_login(cd)
        this_year = self.client.get(f"/coverage?fy={fy}")
        self.assertEqual(this_year.status_code, 200)
        self.assertEqual(this_year.context["visited"], 0)
        self.assertContains(this_year, "Wakiso")
        last_year = self.client.get(f"/coverage?fy={old_fy}")
        self.assertEqual(last_year.context["visited"], 1)
        self.assertEqual(last_year.context["districts"][0]["pct"], 100)


class SearchStaffScopeTest(TestCase):
    def test_a_cd_only_finds_staff_in_their_own_country(self):
        cd = _person("srch-cd@t.org", "Srch CD", EdifyRole.COUNTRY_DIRECTOR.value)
        _person("srch-ug@t.org", "Okello Uganda", EdifyRole.CCEO.value)
        _person("srch-ke@t.org", "Okello Kenya", EdifyRole.CCEO.value, country="Kenya")
        self.client.force_login(cd)
        response = self.client.get("/search?q=Okello")
        self.assertEqual(response.status_code, 200)
        names = {u.name for u in response.context["results"]["staff"]}
        self.assertIn("Okello Uganda", names)
        self.assertNotIn("Okello Kenya", names)

    def test_an_admin_still_searches_every_country(self):
        admin = _person("srch-admin@t.org", "Srch Admin", EdifyRole.ADMIN.value)
        _person("srch-ke2@t.org", "Okello Kenya", EdifyRole.CCEO.value, country="Kenya")
        self.client.force_login(admin)
        response = self.client.get("/search?q=Okello")
        names = {u.name for u in response.context["results"]["staff"]}
        self.assertIn("Okello Kenya", names)


class DebriefFiscalYearWindowTest(TestCase):
    def test_the_full_fy_option_widens_the_kpi_window_to_the_year(self):
        from apps.debriefs.dashboard_service import FieldDebriefDashboardService

        cd = _person("dbf-cd@t.org", "Dbf CD", EdifyRole.COUNTRY_DIRECTOR.value)
        fy = get_operational_fy()
        context = FieldDebriefDashboardService.get_dashboard(
            cd, {"fy": fy, "range_days": "fy"}
        )
        self.assertEqual(context["range_days"], "fy")
        self.assertEqual(context["start"], date(int(fy) - 1, 10, 1))
        self.assertLessEqual(context["end"], date.today())
        default = FieldDebriefDashboardService.get_dashboard(cd, {"fy": fy})
        self.assertEqual(default["range_days"], 30)


class PolicyComplianceScopeTest(TestCase):
    def test_a_country_less_cd_reports_on_nobody(self):
        from apps.documents.compliance import _scope_user_ids

        cd = _person(
            "pc-cd@t.org", "PC CD", EdifyRole.COUNTRY_DIRECTOR.value, country=""
        )
        self.assertEqual(_scope_user_ids(cd), set())

    def test_the_strip_counts_the_whole_scope_not_the_rendered_rows(self):
        from apps.documents.compliance import PolicyComplianceService

        class _Ack:
            def __init__(self, state, due=None):
                self.state = state
                self.due_date = due

        from apps.documents.models import AcknowledgementState

        records = [_Ack(AcknowledgementState.AGREED)] * 3 + [
            _Ack(AcknowledgementState.PENDING, date.today() - timedelta(days=1))
        ]
        counts = PolicyComplianceService.counts(records, date.today())
        self.assertEqual(counts["required"], 4)
        self.assertEqual(counts["pending"], 1)
