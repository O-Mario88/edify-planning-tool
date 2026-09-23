from datetime import date

from django.test import TestCase

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

    def test_the_accountant_reads_clusters_as_names_not_links(self):
        """Owner, 2026-09-23: the Accountant keeps the cluster reading they had
        on Team Oversight. They cannot open a cluster record, so each cluster
        is named without a link they would be refused."""
        accountant = _create_user(
            "accountant@dedicated.test", EdifyRole.PROGRAM_ACCOUNTANT
        )
        self.client.force_login(accountant)
        response = self.client.get("/cluster-oversight/", {"fy": self.fy})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lead cluster")
        self.assertContains(response, 'aria-label="Cluster meetings"')
        self.assertNotContains(response, f'href="/clusters/{self.cluster.id}"')
        self.assertContains(response, 'href="/cluster-oversight/"')

    def test_readers_who_can_open_a_cluster_keep_its_link(self):
        self.client.force_login(self.ia)
        response = self.client.get("/cluster-oversight/", {"fy": self.fy})
        self.assertContains(response, f'href="/clusters/{self.cluster.id}"')

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


class ClusterSessionsReadTheWorkPlannedTest(TestCase):
    """Owner, 2026-09-23: "cluster meeting table and group training tables are
    not fetching the planned group training and Meeting from the database so
    it is returning blank even though the training have been planned", and
    "the date of the last activity should only appear if the planned activity
    is completed, because the activities can easily be cancelled"."""

    def setUp(self):
        self.pl = _create_user("lead@sessions.test", EdifyRole.COUNTRY_PROGRAM_LEAD)
        self.cceo = _create_user("member@sessions.test", EdifyRole.CCEO)
        self.ia = _create_user("ia@sessions.test", EdifyRole.IMPACT_ASSESSMENT)
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl.staff_profile, supervisee=self.cceo.staff_profile
        )
        region = Region.objects.create(name="Sessions region")
        self.district = District.objects.create(name="Sessions district", region=region)
        self.region = region
        self.cluster = Cluster.objects.create(
            district=self.district,
            region=region,
            name="Sessions cluster",
            responsible_staff_id=self.cceo.staff_profile.id,
        )
        self.fy = get_operational_fy()
        self.next_fy = str(int(self.fy) + 1)
        # Planned in September for October: the next fiscal year.
        self.october = date(int(self.fy), 10, 14)

    def _session(self, kind, *, status="scheduled", fy=None, day=None, **kw):
        return Activity.objects.create(
            activity_type=kind,
            cluster=kw.pop("cluster", self.cluster),
            responsible_staff_id=kw.pop(
                "responsible_staff_id", self.cceo.staff_profile.id
            ),
            fy=fy or self.next_fy,
            planned_date=day or self.october,
            status=status,
            **kw,
        )

    def _member(self, data, user):
        for lead in data["leads"]:
            for tab in lead["cceo_tabs"]:
                if tab["id"] == user.staff_profile.id:
                    return tab
        return next(
            tab for tab in data["cceo_tabs"] if tab["id"] == user.staff_profile.id
        )

    def test_sessions_planned_into_next_year_fill_the_operational_year_tables(self):
        meeting = self._session("cluster_meeting")
        training = self._session("cluster_training")
        for reader in (self.pl, self.ia):
            with self.subTest(role=reader.active_role):
                data = cluster_oversight_table_data(reader, fy=self.fy)
                tab = self._member(data, self.cceo)
                self.assertEqual([i.activity_id for i in tab["meetings"]], [meeting.id])
                self.assertEqual(
                    [i.activity_id for i in tab["trainings"]], [training.id]
                )
                self.assertEqual(
                    (data["meetings_planned"], data["trainings_planned"]), (1, 1)
                )
                self.assertEqual(
                    data["plan_period_label"], f"FY {self.fy}–{self.next_fy}"
                )
        # The next year on its own still reads them; an earlier year does not.
        data = cluster_oversight_table_data(self.ia, fy=self.next_fy)
        self.assertEqual(data["meetings_planned"], 1)
        self.assertEqual(data["plan_period_label"], f"FY {self.next_fy}")
        earlier = cluster_oversight_table_data(self.ia, fy=str(int(self.fy) - 1))
        self.assertEqual(
            (earlier["meetings_planned"], earlier["trainings_planned"]), (0, 0)
        )

    def test_the_page_opens_on_the_planned_sessions(self):
        self._session("cluster_meeting")
        self._session("cluster_training")
        self.client.force_login(self.ia)
        response = self.client.get("/cluster-oversight/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Open plans in FY {self.fy}–{self.next_fy}")
        self.assertContains(
            response, 'Group trainings <span class="edify-text-caption">(1)</span>'
        )
        self.assertContains(
            response, 'Cluster meetings <span class="edify-text-caption">(1)</span>'
        )

    def test_the_last_activity_date_is_the_last_session_delivered(self):
        from apps.clusters.oversight_service import grouped_clusters

        this_year = date(int(self.fy), 3, 5)
        # Planned, rescheduled and cancelled sessions are not activity yet.
        self._session("cluster_meeting", status="scheduled")
        self._session(
            "cluster_training", status="cancelled", day=date(int(self.fy), 6, 1)
        )
        self._session(
            "cluster_meeting", status="rescheduled", day=date(int(self.fy), 5, 1)
        )
        quiet = Cluster.objects.create(
            district=self.district,
            region=self.region,
            name="Quiet cluster",
            responsible_staff_id=self.cceo.staff_profile.id,
        )
        self._session("cluster_meeting", cluster=quiet, status="cancelled", fy=self.fy)
        # Delivered: awaiting verification, and one IA-verified whose recorded
        # delivery date differs from the date it was planned for.
        self._session(
            "cluster_meeting",
            status="awaiting_ia_verification",
            fy=self.fy,
            day=date(int(self.fy), 2, 1),
        )
        self._session(
            "cluster_training",
            status="ia_verified",
            fy=self.fy,
            day=date(int(self.fy), 3, 1),
            actual_delivery_date=this_year,
        )
        expected = this_year.strftime("%b %d, %Y")

        data = cluster_oversight_table_data(self.ia, fy=self.fy)
        rows = {
            row["cluster_id"]: row
            for lead in data["leads"]
            for tab in lead["cceo_tabs"]
            for row in tab["clusters"]
        }
        self.assertEqual(rows[self.cluster.id]["last_activity_date"], expected)
        self.assertEqual(rows[quiet.id]["last_activity_date"], "—")

        grouped = {
            row["id"]: row
            for group in grouped_clusters(self.ia)["groups"]
            for row in group["clusters"]
        }
        self.assertEqual(grouped[self.cluster.id]["last_activity_date"], expected)
        self.assertEqual(grouped[quiet.id]["last_activity_date"], "—")

    def test_a_persons_sessions_sit_in_the_same_tab_as_their_clusters(self):
        """The session's owner stored as a User id and the cluster's as a
        StaffProfile id are one person: one tab, clusters and sessions
        together, under the same Programme Lead — also for an officer with no
        Programme Lead, whose work used to split into two tabs of one name."""
        loner = _create_user("loner@sessions.test", EdifyRole.CCEO)
        lone_cluster = Cluster.objects.create(
            district=self.district,
            region=self.region,
            name="Loner cluster",
            responsible_staff_id=loner.staff_profile.id,
        )
        self._session(
            "cluster_meeting", cluster=lone_cluster, responsible_staff_id=loner.id
        )
        self._session("cluster_training", responsible_staff_id=self.cceo.id)

        data = cluster_oversight_table_data(self.ia, fy=self.fy)
        for user, cluster in ((loner, lone_cluster), (self.cceo, self.cluster)):
            with self.subTest(officer=user.email):
                tabs = [
                    tab
                    for lead in data["leads"]
                    for tab in lead["cceo_tabs"]
                    if tab["name"] == user.name
                ]
                self.assertEqual(len(tabs), 1)
                tab = tabs[0]
                self.assertEqual(
                    [row["cluster_id"] for row in tab["clusters"]], [cluster.id]
                )
                self.assertEqual(len(tab["meetings"]) + len(tab["trainings"]), 1)
