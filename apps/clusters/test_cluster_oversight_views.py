"""Tests for Cluster Oversight and Core Schools Oversight views and tables.

Covers:
1. Permission checks for /cluster-oversight/ and /core-schools-oversight/ across roles.
2. Verification of Cluster Oversight table columns:
   - Cluster Name, District, Cluster leader's Name, Cluster leader's Phone number,
     # School SSA scores average, Least performing intervention, Date of the last activity
   - Confirms "Responsible CCEO" column is NOT in the table (moved to tabs).
   - Confirms Cluster Performance metrics/overview are integrated on the page.
3. Verification of Core Schools Oversight table columns.
4. Role-aware actions (View vs Owner dropdown).
"""

from __future__ import annotations

from datetime import date
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.clusters.models import Cluster
from apps.geography.models import District, Region
from apps.core.rbac import EdifyRole
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.core.enums import SchoolType
from apps.schools.models import School


def _create_user(email: str, role: EdifyRole) -> User:
    user, _ = User.objects.get_or_create(
        email=email,
        defaults={
            "name": email.split("@")[0].replace(".", " ").title(),
            "roles": [role.value],
            "active_role": role.value,
            "is_active": True,
        },
    )
    StaffProfile.objects.get_or_create(user=user, defaults={"title": role.value})
    return user


class OversightViewsAccessTest(TestCase):
    def setUp(self):
        self.cd = _create_user("cd@oversight.test", EdifyRole.COUNTRY_DIRECTOR)
        self.ia = _create_user("ia@oversight.test", EdifyRole.IMPACT_ASSESSMENT)
        self.pl = _create_user("pl@oversight.test", EdifyRole.COUNTRY_PROGRAM_LEAD)
        self.rpl = _create_user("rpl@oversight.test", EdifyRole.REGIONAL_PROGRAM_LEAD)
        self.cceo = _create_user("cceo@oversight.test", EdifyRole.CCEO)

        self.region, _ = Region.objects.get_or_create(name="Central Region")
        self.district, _ = District.objects.get_or_create(
            name="Kampala District", defaults={"region": self.region}
        )
        self.cluster = Cluster.objects.create(
            name="Alpha Cluster",
            region=self.region,
            district=self.district,
            responsible_staff_id=str(self.cceo.id),
            cluster_leader_name="John Doe",
            cluster_leader_phone="+256700123456",
        )
        self.school = School.objects.create(
            name="Alpha Academy",
            school_id="SCH-001",
            region=self.region,
            district=self.district,
            cluster_id=str(self.cluster.id),
            school_type=SchoolType.CORE,
        )

    def test_pl_working_clusters_exclude_supervised_portfolio(self):
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl.staff_profile,
            supervisee=self.cceo.staff_profile,
        )
        for owner_id in (self.pl.id, self.pl.staff_profile.id):
            Cluster.objects.create(
                name=f"Owned cluster {owner_id}",
                responsible_staff_id=str(owner_id),
                region=self.region,
                district=self.district,
            )
        Cluster.objects.create(
            name="Other team private cluster",
            responsible_staff_id=str(self.rpl.id),
            region=self.region,
            district=self.district,
        )
        self.client.force_login(self.pl)
        response = self.client.get("/clusters")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["page_obj"]), 2)
        self.assertContains(response, "Owned cluster")
        self.assertNotContains(response, "Alpha Cluster")
        oversight = self.client.get(reverse("frontend:cluster_oversight"))
        self.assertContains(oversight, "Alpha Cluster")
        self.assertContains(oversight, "My Clusters")
        self.assertEqual(oversight.context["cceo_tabs"][0]["count"], 2)
        self.assertNotContains(oversight, 'aria-label="Supervising Program Leads"')
        self.assertNotContains(oversight, "Other team private cluster")

    def test_core_oversight_has_only_one_active_sidebar_entry(self):
        from apps.core.navigation import build_sidebar_for_user

        sections = build_sidebar_for_user(self.pl, "/core-schools-oversight/")
        active = [
            item["url"]
            for section in sections
            for item in section["items"]
            if item["active"]
        ]
        self.assertEqual(active, ["/core-schools-oversight/"])

    def test_annual_filters_render_options_and_swap_only_workspace(self):
        self.client.force_login(self.cd)
        for name in ("cluster_oversight", "core_schools_oversight"):
            url = reverse(f"frontend:{name}")
            response = self.client.get(url)
            self.assertContains(response, 'name="fy"', count=1)
            self.assertNotContains(response, 'name="week"')
            self.assertTrue(response.context["fy_options"])
            partial = self.client.get(
                url, {"fy": response.context["fy"]}, HTTP_HX_REQUEST="true"
            )
            self.assertEqual(partial.status_code, 200)
            self.assertNotContains(partial, "<!DOCTYPE", html=False)
            self.assertNotContains(partial, 'name="fy"')
            self.assertContains(partial, "context-metrics")

    def test_cluster_oversight_accessible_by_permitted_roles(self):
        url = reverse("frontend:cluster_oversight")
        for user in [self.cd, self.ia, self.pl, self.rpl]:
            self.client.force_login(user)
            resp = self.client.get(url)
            self.assertEqual(
                resp.status_code,
                200,
                f"{user.active_role} should have access to /cluster-oversight/",
            )

    def test_cluster_oversight_denied_for_cceo(self):
        url = reverse("frontend:cluster_oversight")
        self.client.force_login(self.cceo)
        resp = self.client.get(url)
        # Should be forbidden (403) or redirect (302)
        self.assertIn(resp.status_code, [302, 403])

    def test_core_schools_oversight_accessible_by_permitted_roles(self):
        url = reverse("frontend:core_schools_oversight")
        for user in [self.cd, self.ia, self.pl, self.rpl]:
            self.client.force_login(user)
            resp = self.client.get(url)
            self.assertEqual(
                resp.status_code,
                200,
                f"{user.active_role} should have access to /core-schools-oversight/",
            )

    def test_core_schools_oversight_denied_for_cceo(self):
        url = reverse("frontend:core_schools_oversight")
        self.client.force_login(self.cceo)
        resp = self.client.get(url)
        self.assertIn(resp.status_code, [302, 403])

    def test_cluster_oversight_table_has_7_columns_and_no_responsible_cceo_column(self):
        url = reverse("frontend:cluster_oversight")
        self.client.force_login(self.cd)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        # Check required columns
        self.assertContains(resp, "Cluster Name")
        self.assertContains(resp, "District")
        self.assertContains(resp, "Cluster Leader's Name")
        self.assertContains(resp, "Cluster Leader's Phone")
        self.assertContains(resp, "# School SSA Scores Avg")
        self.assertContains(resp, "Least Performing Intervention")
        self.assertContains(resp, "Date of Last Activity")

        # Ensure "Responsible CCEO" is NOT a table header
        self.assertNotContains(
            resp,
            '<th scope="col" class="px-4 py-2.5 font-semibold min-w-[150px]">Responsible CCEO</th>',
        )
        self.assertNotContains(resp, ">Responsible CCEO<")

        # Cluster performance overview metrics exist
        self.assertContains(resp, "Total Clusters")
        self.assertContains(resp, "Active Clusters")
        self.assertContains(resp, "Sessions Held")
        self.assertContains(resp, "Schools Reached")
        self.assertContains(resp, "Alpha Cluster")
        self.assertContains(resp, "John Doe")
        self.assertContains(resp, "+256700123456")

    def test_core_schools_oversight_table_columns(self):
        url = reverse("frontend:core_schools_oversight")
        self.client.force_login(self.cd)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        self.assertContains(resp, "School ID")
        self.assertContains(resp, "School Name")
        self.assertContains(resp, "District")
        self.assertContains(resp, "Cluster")
        self.assertContains(resp, "Visits (4)")
        self.assertContains(resp, "Trainings (4)")
        self.assertContains(resp, "Package Progress")
        self.assertContains(resp, "SSA Score")
        self.assertContains(resp, "Status")
        self.assertContains(resp, "Actions")

    def test_country_planning_team_detail_renders_all_4_tables_and_role_aware_actions(
        self,
    ):
        # 1. Establish supervisory relationship PL -> CCEO
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl.staff_profile,
            supervisee=self.cceo.staff_profile,
        )

        # 2. Client school and visit
        client_school = School.objects.create(
            name="St. Mary's Client School",
            school_id="SCH-CLIENT-001",
            region=self.region,
            district=self.district,
            school_type=SchoolType.CLIENT,
        )
        Activity.objects.create(
            activity_type="school_visit",
            school=client_school,
            fy="2026",
            planned_date=date(2026, 9, 20),
            status="scheduled",
            responsible_staff_id=str(self.cceo.id),
            activity_purpose_text="Teacher Professional Development",
        )

        # 3. Core school visit
        Activity.objects.create(
            activity_type="core_visit",
            school=self.school,
            fy="2026",
            planned_date=date(2026, 9, 21),
            status="scheduled",
            responsible_staff_id=str(self.cceo.id),
            activity_purpose_text="Core Diagnostic Verification",
        )

        # 4. Cluster meeting
        Activity.objects.create(
            activity_type="cluster_meeting",
            cluster=self.cluster,
            fy="2026",
            planned_date=date(2026, 9, 22),
            status="scheduled",
            responsible_staff_id=str(self.cceo.id),
            activity_purpose_text="Termly Cluster Alignment",
        )

        # 5. In-school training (cost 0, cluster planned from = School Visit)
        Activity.objects.create(
            activity_type="in_school_training",
            school=self.school,
            fy="2026",
            planned_date=date(2026, 9, 23),
            status="scheduled",
            responsible_staff_id=str(self.cceo.id),
        )

        # 6. Test CD (leadership oversight) access
        url = reverse("frontend:country_planning_oversight_team", args=[self.pl.id])
        self.client.force_login(self.cd)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        # Verify all 4 tables are present
        self.assertContains(resp, "1. Client School Visits")
        self.assertContains(resp, "2. Core School Visits")
        self.assertContains(resp, "3. Cluster Meetings")
        self.assertContains(resp, "4. Schools with Planned Training")

        # Table 1 columns
        self.assertContains(resp, "Purpose of Visit")
        self.assertContains(resp, "Teacher Professional Development")

        # Table 2 columns
        self.assertContains(resp, "Core Diagnostic Verification")

        # Table 3 columns
        self.assertContains(resp, "Purpose (Meeting Topic)")
        self.assertContains(resp, "Termly Cluster Alignment")

        # Table 4 columns & in-school rules
        self.assertContains(resp, "Cluster Planned From")
        self.assertContains(resp, "Delivery Type")
        self.assertContains(resp, "in-school")
        self.assertContains(
            resp, "School Visit"
        )  # For in-school training, cluster is "School Visit"

        # Verify role-aware action: CD sees View action button, NOT edit/reschedule/cancel dropdown
        self.assertContains(resp, "View")
        self.assertNotContains(resp, ">Reschedule<")
        self.assertNotContains(resp, ">Cancel<")

    def test_cluster_participants_sum_invited_school_composition(self):
        from apps.frontend.views.oversight_views import (
            _partition_owner_groups_by_stream,
        )
        from apps.planning import oversight_service

        second_school = School.objects.create(
            name="Beta Academy",
            school_id="SCH-002",
            region=self.region,
            district=self.district,
            cluster_id=str(self.cluster.id),
        )
        meeting = Activity.objects.create(
            activity_type="cluster_meeting",
            cluster=self.cluster,
            fy="2026",
            planned_date=date(2026, 9, 22),
            status="scheduled",
            responsible_staff_id=str(self.cceo.id),
            participants_per_school=2,
        )
        training = Activity.objects.create(
            activity_type="cluster_training",
            cluster=self.cluster,
            fy="2026",
            planned_date=date(2026, 9, 23),
            status="scheduled",
            responsible_staff_id=str(self.cceo.id),
            participants_per_school=2,
        )
        for activity in (meeting, training):
            ClusterActivityAttendance.objects.create(
                activity=activity,
                school=self.school,
                invited=True,
                teachers=2,
                leaders=1,
            )
            ClusterActivityAttendance.objects.create(
                activity=activity,
                school=second_school,
                invited=True,
                teachers=1,
                other=1,
            )

        items = oversight_service.build_items(self.cd, fy="2026")
        groups = oversight_service.group_by_owner(items)
        _partition_owner_groups_by_stream(groups, self.cd)
        officer = next(group for group in groups if group["id"] == str(self.cceo.id))

        self.assertEqual(officer["cluster_meetings"][0].participants, 5)
        self.assertEqual(
            officer["planned_trainings_grouped"][0]["participants_total"], 5
        )
