from datetime import date

from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, TestCase

from apps.accounts.models import StaffSupervisorAssignment
from apps.activities.models import Activity
from apps.clusters.models import Cluster
from apps.clusters.oversight_service import cluster_oversight_table_data
from apps.clusters.test_cluster_oversight_views import _create_user
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import Region, District


class DedicatedClusterOversightTest(TestCase):
    def setUp(self):
        self.pl = _create_user("lead@dedicated.test", EdifyRole.COUNTRY_PROGRAM_LEAD)
        self.cceo = _create_user("member@dedicated.test", EdifyRole.CCEO)
        self.idle = _create_user("idle@dedicated.test", EdifyRole.CCEO)
        self.ia = _create_user("ia@dedicated.test", EdifyRole.IMPACT_ASSESSMENT)
        for user in (self.cceo, self.idle):
            StaffSupervisorAssignment.objects.create(
                supervisor=self.pl.staff_profile, supervisee=user.staff_profile
            )
        region = Region.objects.create(name="Test region")
        district = District.objects.create(name="Test district", region=region)
        self.cluster = Cluster.objects.create(
            district=district,
            region=region,
            name="Lead cluster",
            responsible_staff_id=self.pl.id,
        )
        self.inactive = Cluster.objects.create(
            district=district,
            region=region,
            name="Inactive team cluster",
            responsible_staff_id=self.cceo.staff_profile.id,
            status="inactive",
        )
        self.fy = get_operational_fy()
        self.meeting = Activity.objects.create(
            activity_type="cluster_meeting",
            cluster=self.cluster,
            responsible_staff_id=self.cceo.id,
            fy=self.fy,
            planned_date=date.today(),
            status="scheduled",
        )
        self.training = Activity.objects.create(
            activity_type="cluster_training",
            cluster=self.cluster,
            responsible_staff_id=self.pl.staff_profile.id,
            fy=self.fy,
            planned_date=date.today(),
            status="scheduled",
        )

    def test_pl_has_one_tab_per_member_and_work_follows_responsible_person(self):
        data = cluster_oversight_table_data(self.pl, fy=self.fy)
        tabs = {tab["id"]: tab for tab in data["cceo_tabs"]}
        self.assertEqual(len(tabs), len(data["cceo_tabs"]))
        self.assertEqual(
            set(tabs),
            {"my-clusters", self.cceo.staff_profile.id, self.idle.staff_profile.id},
        )
        self.assertEqual(data["total_clusters"], 2)
        self.assertEqual(
            [i.activity_id for i in tabs["my-clusters"]["trainings"]],
            [self.training.id],
        )
        self.assertEqual(
            [i.activity_id for i in tabs[self.cceo.staff_profile.id]["meetings"]],
            [self.meeting.id],
        )
        self.assertEqual(tabs[self.idle.staff_profile.id]["count"], 0)

    def test_ia_sees_pl_and_entire_roster_in_one_hierarchy(self):
        data = cluster_oversight_table_data(self.ia, fy=self.fy)
        lead = next(
            lead for lead in data["leads"] if lead["id"] == self.pl.staff_profile.id
        )
        self.assertEqual(
            {t["id"] for t in lead["cceo_tabs"]},
            {u.staff_profile.id for u in (self.pl, self.cceo, self.idle)},
        )
        self.client.force_login(self.ia)
        response = self.client.get("/cluster-oversight/", {"fy": self.fy})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'aria-label="Group trainings"')
        self.assertContains(response, 'aria-label="Cluster meetings"')
        self.assertNotContains(response, 'aria-label="Cluster filters"')

    def test_cluster_sections_are_removed_and_old_links_redirect(self):
        self.client.force_login(self.ia)
        for route in ("/team-planning-oversight/", "/country-planning-oversight/"):
            response = self.client.get(route)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, 'id="cluster-oversight-heading"')
            self.assertNotContains(response, "view=clusters")
            response = self.client.get(route, {"view": "clusters", "fy": self.fy})
            self.assertRedirects(
                response,
                f"/cluster-oversight/?fy={self.fy}",
                fetch_redirect_response=False,
            )

    def test_planned_counts_include_undated_and_overdue_but_not_completed(self):
        self.meeting.planned_date = None
        self.meeting.save()
        Activity.objects.create(
            activity_type="cluster_meeting",
            cluster=self.cluster,
            responsible_staff_id=self.pl.id,
            fy=self.fy,
            status="completed",
            planned_date=date.today(),
        )
        Activity.objects.create(
            activity_type="cluster_training",
            cluster=self.cluster,
            responsible_staff_id=self.pl.id,
            fy=self.fy,
            status="cancelled",
        )
        for user in (self.pl, self.ia, self.cceo):
            with self.subTest(role=user.active_role):
                data = cluster_oversight_table_data(user, fy=self.fy)
                self.assertEqual(data["meetings_planned"], 1)
                self.assertEqual(
                    data["trainings_planned"], 1 if user != self.cceo else 0
                )
        data = cluster_oversight_table_data(self.pl, fy=self.fy)
        member = next(
            t for t in data["cceo_tabs"] if t["id"] == self.cceo.staff_profile.id
        )
        self.assertEqual(member["meetings_planned"], 1)

    def test_owner_cannot_see_another_teams_plans(self):
        outsider = _create_user("outside@dedicated.test", EdifyRole.CCEO)
        data = cluster_oversight_table_data(outsider, fy=self.fy)
        self.assertEqual((data["meetings_planned"], data["trainings_planned"]), (0, 0))

    def test_an_officer_with_no_lead_has_one_tab_for_clusters_and_work(self):
        """Under "Unassigned", work was grouped by the raw owner id. A cluster
        keyed its tab by StaffProfile id while the officer's meeting named
        their User id, so one person became two tabs — one holding their
        clusters, the other their work."""
        lone = _create_user("lone@dedicated.test", EdifyRole.CCEO)
        held = Cluster.objects.create(
            district=self.cluster.district,
            region=self.cluster.region,
            name="Lone cluster",
            responsible_staff_id=lone.staff_profile.id,
        )
        meeting = Activity.objects.create(
            activity_type="cluster_meeting",
            cluster=held,
            responsible_staff_id=lone.id,
            fy=self.fy,
            planned_date=date.today(),
            status="scheduled",
        )

        data = cluster_oversight_table_data(self.ia, fy=self.fy)

        unassigned = next(
            lead for lead in data["leads"] if lead["id"] == "__unassigned__"
        )
        tabs = [tab for tab in unassigned["cceo_tabs"] if tab["name"] == "Lone"]
        self.assertEqual(len(tabs), 1, [t["id"] for t in unassigned["cceo_tabs"]])
        self.assertEqual(tabs[0]["id"], lone.staff_profile.id)
        self.assertEqual(tabs[0]["count"], 1)
        self.assertEqual([i.activity_id for i in tabs[0]["meetings"]], [meeting.id])

    def test_every_leads_roster_loads_in_two_queries(self):
        from apps.planning import oversight_service as planning

        other = _create_user(
            "other-lead@dedicated.test", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        lead_ids = [self.pl.staff_profile.id, other.id, "__unassigned__"]

        with self.assertNumQueries(2):
            rosters = planning.program_lead_rosters(lead_ids)

        self.assertNotIn("__unassigned__", rosters)
        for lead_id in lead_ids[:2]:
            with self.subTest(lead=lead_id):
                self.assertEqual(
                    rosters[lead_id], planning.program_lead_members(lead_id)
                )
        self.assertEqual(
            [m["id"] for m in rosters[self.pl.staff_profile.id]],
            [
                self.pl.staff_profile.id,
                self.idle.staff_profile.id,
                self.cceo.staff_profile.id,
            ],
        )

    def test_the_page_reads_the_team_as_people_on_a_chart(self):
        """Cluster Oversight carries the per-person chart
        (docs/chart-inventory-and-standard-2026-09-20.md, 21 September), and
        e2e/chart-standard.spec.js draws it: one series per officer for a
        Programme Lead, one per Lead for a country reader."""
        for user, title in (
            (self.pl, "Cluster activity by person"),
            (self.ia, "Cluster activity by Programme Lead"),
        ):
            with self.subTest(role=user.active_role):
                self.client.force_login(user)
                response = self.client.get("/cluster-oversight/", {"fy": self.fy})
                self.assertContains(response, title)
                self.assertContains(response, 'class="card edify-data-chart"')


class ClusterActivityTablePagesPerOfficerTest(SimpleTestCase):
    """Each officer's two activity tables turn their own pages.

    Cluster Oversight lists every officer's group trainings and cluster
    meetings in tabs on one page, so a shared page parameter would move every
    table at once. Each table is keyed by the officer and the kind of work.
    """

    def _render(self, query=""):
        rows = [
            {
                "cluster_id": f"c{i}",
                "cluster_name": f"Cluster {i}",
                "activity_type": "cluster_training",
                "planned_date": date(2026, 9, 1),
            }
            for i in range(12)
        ]
        member = {"id": "O1", "name": "Officer", "trainings": rows, "meetings": []}
        request = RequestFactory().get("/cluster-oversight/" + query)
        return render_to_string(
            "partials/oversight/cluster_member_work.html",
            {"member": member, "request": request},
        )

    def test_the_trainings_table_pages_under_its_own_parameter(self):
        html = self._render()
        self.assertIn("ct_page-O1=2", html)
        self.assertNotIn("cm_page-O1=2", html)
        self.assertIn("Cluster 0<", html)
        self.assertNotIn("Cluster 11<", html)

    def test_the_second_page_shows_the_remaining_rows(self):
        html = self._render("?ct_page-O1=2")
        self.assertIn("Cluster 11<", html)
        self.assertNotIn("Cluster 0<", html)
