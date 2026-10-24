"""Core Schools draws its tabs when they are opened (2026-10-24).

The page drew all four tabs on every load and hid three: 8,500 elements and
765 KB for a CCEO's 103 Core schools on a seeded database, the planning queue
alone 179 KB, and the server built all of their data first. The Planning
Queue, Intervention Impact and Performance tabs now load the first time they
are shown, for the same filters and page; the page builds none of their data.
The Staff vs Partner figure the KPI strip shows is still read on the page.
"""

from __future__ import annotations

from unittest import mock

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School

PANELS = ("queue", "impact", "performance")
SERVICES = "apps.frontend.views.core_schools_views"


class CoreSchoolsLazyPanelsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="LP Region")
        cls.district = District.objects.create(name="LP District", region=region)
        sub = SubCounty.objects.create(name="LP Sub", district=cls.district)
        cls.user = User.objects.create(
            email="lp-cceo@edify.org",
            name="LP Field",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            is_active=True,
            status="active",
        )
        profile = StaffProfile.objects.create(user=cls.user, title="CCEO")
        for i in range(3):
            school = School.objects.create(
                school_id=f"LP-{i}",
                name=f"LP School {i}",
                region=region,
                district=cls.district,
                sub_county=sub,
                school_type="core",
                account_owner_id=profile.id,
                account_owner_status="matched",
            )
            StaffSchoolAssignment.objects.create(staff=profile, school_id=school.id)

    def setUp(self):
        self.client.force_login(self.user)

    def test_the_page_builds_no_hidden_tab(self):
        refuse = mock.Mock(side_effect=AssertionError("built on page load"))
        with (
            mock.patch(f"{SERVICES}.CorePlanningService.get_planning_queue", refuse),
            mock.patch(
                f"{SERVICES}.CoreInterventionImpactService.get_intervention_impact",
                refuse,
            ),
            mock.patch(
                f"{SERVICES}.CoreStaffPartnerPerformanceService"
                ".get_intervention_comparison_rows",
                refuse,
            ),
        ):
            response = self.client.get("/core-schools")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        for panel in PANELS:
            with self.subTest(panel=panel):
                self.assertIn(f'id="core-panel-{panel}"', html)
                self.assertIn(f"panel={panel}", html)
                self.assertNotIn(f'data-core-panel-loaded="{panel}"', html)
        self.assertIn('hx-trigger="intersect once"', html)
        # The KPI strip still reads Staff vs Partner.
        self.assertIn("Staff vs Partner", html)

    def test_each_tab_loads_alone_when_opened(self):
        for panel in PANELS:
            with self.subTest(panel=panel):
                response = self.client.get("/core-schools", {"panel": panel})
                self.assertEqual(response.status_code, 200)
                html = response.content.decode()
                self.assertIn(f'data-core-panel-loaded="{panel}"', html)
                self.assertNotIn("<html", html)
                self.assertNotIn('id="core-schools-table-container"', html)

    def test_a_tab_loads_for_the_filters_and_page_in_view(self):
        html = self.client.get(
            "/core-schools", {"district": self.district.id, "page": "1", "q": "LP"}
        ).content.decode()
        loader = html[html.index('id="core-panel-queue"') :]
        loader = loader[: loader.index("</div>")]
        self.assertIn(f"district={self.district.id}", loader)
        self.assertIn("q=LP", loader)
        self.assertIn("page=1", loader)

    def test_an_unknown_panel_is_the_whole_page(self):
        response = self.client.get("/core-schools", {"panel": "nope"})
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="core-schools-table-container"', response.content.decode())
