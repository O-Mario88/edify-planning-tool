"""A link is drawn only for someone who can follow it (role crawl, 2026-09-14).

A role-by-role crawl followed every link and button the pages drew and found
some that landed on "Access Denied" or a 403 drawer: Personal Time Off's Team
Availability report, the Data Quality Center's staff setup queue, HR Today's
row actions, the HR dashboard's Recruitment and Org Structure links, the
vacancy drawer on Workforce Planning, activity records on planning oversight,
and cluster and school profiles in the school lists.

Each is now drawn through the shared page check (the `can_open` filter over
apps.core.permissions.can_open_url): present for a role its page lets in,
absent, or plain text, for a role it refuses.
"""

from __future__ import annotations

import copy
from types import SimpleNamespace
from unittest import mock

from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.core.permissions import page_permission_for_url
from apps.core.rbac import EdifyRole
from apps.hr.hr_exceptions import (
    DEADLINES,
    GROUP_LABELS,
    MANAGER_OVERDUE,
    PEOPLE_RISK,
    WAITING_ON_HR,
)

ACCOUNTANT = EdifyRole.PROGRAM_ACCOUNTANT.value
ADMIN = EdifyRole.ADMIN.value
BT_OFFICER = EdifyRole.BUSINESS_TRANSFORMATION_OFFICER.value
CCEO = EdifyRole.CCEO.value
CD = EdifyRole.COUNTRY_DIRECTOR.value
COORDINATOR = EdifyRole.PROJECT_COORDINATOR.value
HR = EdifyRole.HUMAN_RESOURCES.value
IA = EdifyRole.IMPACT_ASSESSMENT.value
MFI_ADMIN = EdifyRole.MFI_PARTNER_ADMIN.value
MFI_OFFICER = EdifyRole.MFI_LOAN_OFFICER.value
PL = EdifyRole.COUNTRY_PROGRAM_LEAD.value
REGIONAL_LEAD = EdifyRole.REGIONAL_PROGRAM_LEAD.value
RVP = EdifyRole.REGIONAL_VICE_PRESIDENT.value


def _render(template: str, role: str, **context) -> str:
    """Render a partial for a viewer holding `role`.

    The page check reads only the viewer's active role, so an unsaved user is
    enough and these template tests never touch the database.
    """
    request = RequestFactory().get("/")
    request.user = User(email="viewer@t.test", name="Viewer", active_role=role)
    return render_to_string(template, {"request": request, **context})


class StandInGateUrlTest(SimpleTestCase):
    """Row templates ask about a route with a stand-in id ("/activities/0",
    "/clusters/0") so a table answers its gate without building a URL per
    record. That holds only while the stand-in resolves to the same gate as a
    real record's URL."""

    def test_each_stand_in_shares_the_gate_of_a_real_record(self):
        for stand_in, real in (
            (
                "/activities/0",
                reverse("frontend:activity_detail_full", args=["cm0activity"]),
            ),
            ("/clusters/0", reverse("frontend:cluster_detail", args=["cm0cluster"])),
            ("/clusters", reverse("frontend:cluster_list")),
        ):
            with self.subTest(stand_in=stand_in):
                gate = page_permission_for_url(real)
                self.assertIsNotNone(gate)
                self.assertEqual(page_permission_for_url(stand_in), gate)


class OversightActivityLinkTest(SimpleTestCase):
    """Planning oversight linked every role it admits to /activities/<id>,
    which My Plan gates. The RVP and the Regional Programme Lead were refused
    outright; the Accountant passes the gate, but its record reach is
    finance-only and the record refused every activity with no money
    movement."""

    ITEM = SimpleNamespace(
        activity_id="cm0activity",
        partner_activity_id="cm0partneractivity",
        partner_assignment_id="cm0assignment",
        activity_type="school_visit",
        context_label="Alpha Primary",
        school_id=None,
        executor_name="James",
        planned_cost=75_000,
        activity_status="scheduled",
        risks=[],
    )
    REFUSED = (ACCOUNTANT, RVP, REGIONAL_LEAD)
    ADMITTED = (PL, CD)

    def _team_table(self, role: str) -> str:
        return _render(
            "partials/oversight/cd_team_detail.html",
            role,
            owner_groups=[
                {
                    "name": "Team Lead",
                    "summary": {},
                    "items": [self.ITEM],
                    "page_param": "owner_1",
                }
            ],
        )

    def test_the_team_table_names_the_activity_without_linking_a_refused_role(self):
        for role in self.REFUSED:
            with self.subTest(role=role):
                html = self._team_table(role)
                self.assertNotIn('href="/activities/', html)
                self.assertIn("School Visit", html)
        for role in self.ADMITTED:
            with self.subTest(role=role):
                self.assertIn('href="/activities/cm0activity"', self._team_table(role))

    def test_the_drawers_offer_the_record_only_to_a_role_that_can_open_it(self):
        for template, href in (
            (
                "partials/oversight/detail_drawer.html",
                'href="/activities/cm0activity"',
            ),
            (
                "partials/oversight/partner_detail_drawer.html",
                'href="/activities/cm0partneractivity"',
            ),
        ):
            for role in self.REFUSED:
                with self.subTest(template=template, role=role):
                    html = _render(template, role, item=self.ITEM, lineage={})
                    self.assertNotIn(href, html)
                    self.assertNotIn("Open the full activity record", html)
            for role in self.ADMITTED:
                with self.subTest(template=template, role=role):
                    html = _render(template, role, item=self.ITEM, lineage={})
                    self.assertIn(href, html)


class SchoolListLinkTest(SimpleTestCase):
    """The school lists linked each row's cluster, and the directory each
    school's profile, for roles those pages refuse: the Accountant reads core
    schools but not clusters, the Project Coordinator opens schools but not
    clusters, and the Regional Programme Lead opens neither."""

    SCHOOL = {
        "id": "cm0school",
        "school_id": "U-1001",
        "name": "Alpha Primary",
        "school_name": "Alpha Primary",
        "cluster_id": "cm0cluster",
        "cluster_name": "Kampala North",
        "assessment": {"status": "Missing"},
        "ssa_groups": [],
        "has_ssa_scores": False,
        "available_actions": [],
    }
    CLUSTER_HREF = 'href="/clusters/cm0cluster"'
    SCHOOL_HREF = 'href="/schools/U-1001"'

    def test_the_core_school_row_links_the_cluster_only_where_it_opens(self):
        template = "partials/core_schools/school_row.html"
        refused = _render(template, ACCOUNTANT, school=self.SCHOOL)
        self.assertNotIn(self.CLUSTER_HREF, refused)
        self.assertIn("Kampala North", refused)
        self.assertIn(self.CLUSTER_HREF, _render(template, CD, school=self.SCHOOL))

    def test_the_directory_row_links_the_school_and_cluster_by_their_own_pages(self):
        template = "partials/schools/directory_row.html"

        def row(role):
            return _render(template, role, school=self.SCHOOL, directory_read_only=True)

        regional_lead = row(REGIONAL_LEAD)
        self.assertNotIn(self.SCHOOL_HREF, regional_lead)
        self.assertNotIn(self.CLUSTER_HREF, regional_lead)
        self.assertIn("Alpha Primary", regional_lead)
        self.assertIn("Kampala North", regional_lead)

        coordinator = row(COORDINATOR)
        self.assertIn(self.SCHOOL_HREF, coordinator)
        self.assertNotIn(self.CLUSTER_HREF, coordinator)

        director = row(CD)
        self.assertIn(self.SCHOOL_HREF, director)
        self.assertIn(self.CLUSTER_HREF, director)


class ClusterOversightLinkTest(SimpleTestCase):
    """Cluster Oversight sits on the planning oversight pages, which the RVP,
    the Regional Programme Lead and the Accountant read without opening
    clusters."""

    def _workspace(self, role: str) -> str:
        rows = [
            {
                "cluster": SimpleNamespace(id=f"cm0cluster{n}", name=f"Cluster {n}"),
                "district": "Kampala",
                "owner": "James",
                "schools": 3,
            }
            for n in range(51)
        ]
        return _render(
            "partials/clusters/oversight_workspace.html",
            role,
            groups=[
                {
                    "key": "lead",
                    "label": "Team Lead",
                    "is_unassigned": False,
                    "count": len(rows),
                    "schools": 3 * len(rows),
                    "clusters": rows,
                }
            ],
            total_clusters=len(rows),
            total_schools=3 * len(rows),
            unassigned=0,
            is_team_lens=True,
        )

    def test_clusters_and_the_directory_are_linked_only_where_they_open(self):
        for role in (ACCOUNTANT, RVP, REGIONAL_LEAD):
            with self.subTest(role=role):
                html = self._workspace(role)
                self.assertNotIn('href="/clusters', html)
                self.assertIn("Cluster 0", html)
                self.assertIn("Showing 50 of 51 clusters.", html)
        lead = self._workspace(PL)
        self.assertIn('href="/clusters/cm0cluster0"', lead)
        self.assertIn('href="/clusters"', lead)


class HrOperationsLinkTest(SimpleTestCase):
    """The HR dashboard's Recruitment figures and Organisation link are drawn
    as links only for a viewer those registers let in."""

    def _operations(self, role: str) -> str:
        return _render(
            "partials/dashboards/hr/operations.html",
            role,
            dashboard_view="operations",
            recruitment={"open": 4, "replacements": 1, "pending_approval": 2},
            development={"awaiting_hr": 0, "awaiting_signoff": 0},
            headcount_by_role={"rows": []},
        )

    def test_a_viewer_without_the_registers_reads_the_figures_unlinked(self):
        html = self._operations(RVP)
        self.assertNotIn('href="/recruitment"', html)
        self.assertNotIn('href="/org-structure"', html)
        self.assertIn(
            '<div class="hrd-figure"><span class="hrd-figure__label">Open roles', html
        )

        hr = self._operations(HR)
        self.assertIn('<a class="hrd-figure" href="/recruitment">', hr)
        self.assertIn('href="/org-structure"', hr)


class PeoplePageLinkTest(TestCase):
    """The same rule through the pages' own views."""

    ROLES = (
        ACCOUNTANT,
        ADMIN,
        BT_OFFICER,
        CCEO,
        CD,
        COORDINATOR,
        HR,
        IA,
        MFI_ADMIN,
        MFI_OFFICER,
        PL,
        REGIONAL_LEAD,
        RVP,
    )

    @classmethod
    def setUpTestData(cls):
        cls.users = {
            role: User.objects.create(
                email=f"{role.replace(' ', '-').lower()}@links.test",
                name=f"{role} viewer",
                roles=[role],
                active_role=role,
                is_active=True,
            )
            for role in cls.ROLES
        }

    def _page(self, role: str, url: str) -> str:
        self.client.force_login(self.users[role])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, f"{role} {url}")
        return response.content.decode()

    def test_personal_time_off_links_team_availability_only_where_it_opens(self):
        full_report = 'class="pto-text-link">Full report'
        for role in (
            CCEO,
            IA,
            ACCOUNTANT,
            REGIONAL_LEAD,
            COORDINATOR,
            BT_OFFICER,
            MFI_OFFICER,
            MFI_ADMIN,
        ):
            with self.subTest(role=role):
                html = self._page(role, "/personal-time-off/")
                self.assertNotIn(full_report, html)
                self.assertNotIn('href="/leave/team-availability"', html)
        self.assertIn(full_report, self._page(PL, "/personal-time-off/"))

    def test_the_data_quality_center_offers_the_setup_queue_where_it_opens(self):
        """Both readers of this page can now follow the link.

        Impact Assessment used to be this test's negative example: it could
        open the Data Quality Center and not the Staff Setup Queue, so the
        link was hidden from it. On 2026-09-18 the queue stopped being gated
        on `users` — IA runs the school upload, so the unattached rows are
        its own — and the negative case went with it, because the page itself
        is only `{IA, ADMIN}` and both hold the queue now. The `can_open`
        gate is unchanged and still covered by this class's other tests; what
        moved is which side of it IA sits on.
        """
        queue = 'href="/admin-panel/staff-setup-queue"'
        self.assertIn(queue, self._page(IA, "/admin-panel/data-quality-center"))
        self.assertIn(queue, self._page(ADMIN, "/admin-panel/data-quality-center"))

    def test_hr_today_draws_a_row_action_only_where_the_viewer_can_follow_it(self):
        queue = {
            "groups": [
                {
                    "key": key,
                    "label": GROUP_LABELS[key],
                    "items": [
                        {
                            "group": PEOPLE_RISK,
                            "kind": "no_supervisor",
                            "title": "Active employee has no manager",
                            "detail": "Nobody can approve their leave.",
                            "url": "/org-structure",
                            "severity": "high",
                            "person": "Pat Officer",
                            "due_label": "",
                        }
                    ]
                    if key == PEOPLE_RISK
                    else [],
                }
                for key in (WAITING_ON_HR, MANAGER_OVERDUE, PEOPLE_RISK, DEADLINES)
            ],
            "counts": {},
            "critical_count": 0,
            "total": 1,
        }
        # A fresh copy per request: the view trims each group in place.
        with mock.patch(
            "apps.frontend.views.hr_today_views.grouped_hr_exceptions",
            side_effect=lambda *args, **kwargs: copy.deepcopy(queue),
        ):
            for role in (CD, RVP):
                with self.subTest(role=role):
                    html = self._page(role, "/hr-today")
                    self.assertIn("Active employee has no manager", html)
                    self.assertNotIn('href="/org-structure"', html)
            self.assertIn('href="/org-structure"', self._page(HR, "/hr-today"))

    def test_workforce_planning_offers_recruitment_only_where_it_opens(self):
        drawer = 'hx-get="/recruitment/new"'
        register = 'href="/recruitment"'
        rvp = self._page(RVP, "/workforce-planning")
        self.assertNotIn(drawer, rvp)
        self.assertNotIn(register, rvp)
        for role in (CD, HR):
            with self.subTest(role=role):
                html = self._page(role, "/workforce-planning")
                self.assertIn(drawer, html)
                self.assertIn(register, html)


class CoreSchoolsReportLinkGateTest(SimpleTestCase):
    """The Accountant opens Core Schools but not Visit Effectiveness, so the
    "View Full Report" and analysis links are drawn only for roles that can
    follow them."""

    def test_visit_effectiveness_links_follow_the_page_gate(self):
        for template in (
            "partials/core_schools/intervention_impact.html",
            "partials/core_schools/performance_insights.html",
        ):
            for role, drawn in ((CCEO, True), (PL, True), (ACCOUNTANT, False)):
                with self.subTest(template=template, role=role):
                    html = _render(template, role)
                    self.assertEqual(
                        "/analytics/visit-effectiveness" in html, drawn, role
                    )
