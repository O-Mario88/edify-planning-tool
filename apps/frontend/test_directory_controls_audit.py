"""Controls audit fixes on the School Directory (2026-09-14).

F-02: a pagination gap is decoration, never a page button that submits
page=… and resets the list. F-03: an empty table says whether the registry,
the reader's reach or the chosen filters made it empty.
"""

from __future__ import annotations

from django.core.paginator import Paginator
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, TestCase

from apps.core.pagination import PAGE_GAP, elided_page_numbers


class PaginationGapTest(SimpleTestCase):
    def test_gaps_are_one_token_and_never_a_page_control(self):
        paginator = Paginator(list(range(703)), 15)
        page = paginator.page(10)
        numbers = elided_page_numbers(page)
        self.assertIn(PAGE_GAP, numbers)
        self.assertNotIn("…", numbers)
        for pages_list in (
            numbers,
            # The raw Django range is also rendered as decoration.
            list(paginator.get_elided_page_range(10, on_each_side=1, on_ends=1)),
        ):
            with self.subTest(pages_list=pages_list[:3]):
                html = render_to_string(
                    "partials/schools/table.html",
                    {
                        "directory_read_only": True,
                        "view_models": [],
                        "page_obj": page,
                        "pages_list": pages_list,
                    },
                )
                self.assertNotIn("page=…", html)
                self.assertNotIn("page=...", html)
                self.assertIn('aria-hidden="true">…</span>', html)


class DirectoryEmptyStateTest(TestCase):
    def _render(self, state, **get):
        request = RequestFactory().get("/schools", get)
        return render_to_string(
            "partials/schools/table.html",
            {
                "request": request,
                "directory_read_only": True,
                "view_models": [],
                "directory_empty_state": state,
                "can_open_upload_center": True,
            },
        )

    def test_each_empty_table_says_why(self):
        no_matches = self._render("no_matches", district="Abim", tab="unclustered")
        self.assertIn("No schools match these filters.", no_matches)
        self.assertIn(">Clear filters</a>", no_matches)
        self.assertNotIn("No schools uploaded yet.", no_matches)

        scope = self._render("scope_empty")
        self.assertIn("No schools are assigned to you yet.", scope)
        self.assertNotIn("Open Upload Center", scope)

        registry = self._render("registry_empty")
        self.assertIn("No schools uploaded yet.", registry)
        self.assertIn("Open Upload Center", registry)

    def test_the_directory_view_decides_the_state(self):
        from apps.accounts.models import User

        admin = User.objects.create_user(
            email="dir-admin@t.org",
            name="Dir Admin",
            roles=["Admin"],
            active_role="Admin",
            password="x",
            is_active=True,
        )
        self.client.force_login(admin)
        empty = self.client.get("/schools")
        self.assertEqual(empty.context["directory_empty_state"], "registry_empty")

        from apps.geography.models import District, Region
        from apps.schools.models import School

        region = Region.objects.create(name="Dir Region")
        district = District.objects.create(name="Dir District", region=region)
        School.objects.create(
            school_id="DIR-1", name="Dir School", region=region, district=district
        )
        filtered = self.client.get("/schools", {"q": "no-such-school"})
        self.assertEqual(filtered.context["directory_empty_state"], "no_matches")
        self.assertContains(filtered, "No schools match these filters.")


class PlanningClusterDisclosureTest(SimpleTestCase):
    """F-04: the cluster card opens from one named control that says whether
    it is open and which panel it controls. Since 2026-09-19 the planning
    clusters tab draws the canonical cluster card shared with /clusters. Since
    ffa2431 the name itself is the one toggle button that carries the
    disclosure state and names the details panel, and the details panel opens
    with a link to the profile that names the cluster."""

    def test_the_cluster_card_has_one_named_disclosure_control(self):
        html = render_to_string(
            "partials/planning/school_table.html",
            {
                "active_tab": "clusters",
                "clusters": [
                    {
                        "id": "cl-1",
                        "name": "Mukono North",
                        "district": "Mukono",
                        "school_count": 4,
                        "avg_ssa": 5.2,
                        "weakest_interventions": [],
                    }
                ],
            },
        )
        self.assertIn('aria-controls="cluster-details-cl-1"', html)
        self.assertIn(':aria-expanded="cardExpanded.toString()"', html)
        self.assertIn('id="cluster-details-cl-1"', html)
        self.assertEqual(html.count('aria-controls="cluster-details-cl-1"'), 1)
        details = html.split('id="cluster-details-cl-1"', 1)[1]
        self.assertRegex(
            details,
            r'<a href="/clusters/cl-1"[^>]*>Open Mukono North cluster profile</a>',
        )
        self.assertNotIn(
            "focus:outline-none", html.split('id="cluster-details-cl-1"')[0]
        )
