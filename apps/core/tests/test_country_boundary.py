"""A country role sees their country, not the deployment (owner, 2026-09-03).

"Country scope" used to mean every row in the database. With a second
country on the register a Uganda Country Director would have read Kenya's
schools, activities, clusters, projects and dashboards. The boundary is the
region's country matched against the staff profile's country; Admin and a
country role with no country on file keep the old deployment-wide reach.
"""

from __future__ import annotations

from datetime import date

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity
from apps.clusters.models import Cluster
from apps.core.rbac import EdifyRole
from apps.core.scoping import (
    aggregate_school_filter,
    cluster_in_scope,
    cluster_queryset,
    resolve_user_scope,
    school_queryset,
    scoped_school_queryset,
)
from apps.geography.models import District, Region
from apps.schools.models import School


def _user(email, name, role, country="Uganda"):
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


class CountryBoundaryTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ug_region = Region.objects.create(name="Central UG", country="Uganda")
        cls.ke_region = Region.objects.create(name="Nairobi KE", country="Kenya")
        cls.ug_district = District.objects.create(name="Wakiso", region=cls.ug_region)
        cls.ke_district = District.objects.create(name="Kiambu", region=cls.ke_region)
        cls.ug_school = School.objects.create(
            name="Kampala Primary",
            school_id="UG-CB-001",
            region=cls.ug_region,
            district=cls.ug_district,
        )
        cls.ke_school = School.objects.create(
            name="Nairobi Primary",
            school_id="KE-CB-001",
            region=cls.ke_region,
            district=cls.ke_district,
        )
        cls.ug_cluster = Cluster.objects.create(
            name="UG Cluster", region=cls.ug_region, district=cls.ug_district
        )
        cls.ke_cluster = Cluster.objects.create(
            name="KE Cluster", region=cls.ke_region, district=cls.ke_district
        )
        cls.cd = _user("cb-cd@t.org", "Uganda CD", EdifyRole.COUNTRY_DIRECTOR.value)
        cls.ia = _user("cb-ia@t.org", "Uganda IA", EdifyRole.IMPACT_ASSESSMENT.value)
        cls.admin = _user("cb-admin@t.org", "Admin", EdifyRole.ADMIN.value)
        cls.homeless_cd = _user(
            "cb-cd0@t.org",
            "No-country CD",
            EdifyRole.COUNTRY_DIRECTOR.value,
            country=None,
        )
        cls.ug_cceo = _user("cb-ug-cceo@t.org", "UG CCEO", EdifyRole.CCEO.value)
        cls.ke_cceo = _user(
            "cb-ke-cceo@t.org", "KE CCEO", EdifyRole.CCEO.value, country="Kenya"
        )
        StaffSchoolAssignment.objects.create(
            staff=cls.ug_cceo.staff_profile, school_id=cls.ug_school.id
        )
        StaffSchoolAssignment.objects.create(
            staff=cls.ke_cceo.staff_profile, school_id=cls.ke_school.id
        )
        fy = "2026"
        cls.ug_visit = Activity.objects.create(
            activity_type="school_visit",
            status="scheduled",
            school=cls.ug_school,
            fy=fy,
            planned_date=date(2026, 3, 2),
            responsible_staff_id=cls.ug_cceo.staff_profile.id,
        )
        cls.ke_visit = Activity.objects.create(
            activity_type="school_visit",
            status="scheduled",
            school=cls.ke_school,
            fy=fy,
            planned_date=date(2026, 3, 2),
            responsible_staff_id=cls.ke_cceo.staff_profile.id,
        )
        cls.ke_general = Activity.objects.create(
            activity_type="general_training",
            status="scheduled",
            fy=fy,
            planned_date=date(2026, 3, 3),
            responsible_staff_id=cls.ke_cceo.staff_profile.id,
        )

    def test_the_scope_carries_the_country_from_the_staff_profile(self):
        self.assertEqual(resolve_user_scope(self.cd).country, "Uganda")
        self.assertEqual(resolve_user_scope(self.ia).country, "Uganda")
        self.assertEqual(resolve_user_scope(self.admin).country, "")
        self.assertEqual(resolve_user_scope(self.homeless_cd).country, "")

    def test_school_querysets_stop_at_the_border(self):
        scope = resolve_user_scope(self.cd)
        names = set(scoped_school_queryset(scope).values_list("name", flat=True))
        self.assertEqual(names, {"Kampala Primary"})
        self.assertEqual(
            set(
                School.objects.filter(aggregate_school_filter(scope)).values_list(
                    "name", flat=True
                )
            ),
            {"Kampala Primary"},
        )
        ia_scope = resolve_user_scope(self.ia)
        self.assertEqual(
            set(school_queryset(ia_scope).values_list("name", flat=True)),
            {"Kampala Primary"},
        )

    def test_clusters_stop_at_the_border(self):
        scope = resolve_user_scope(self.cd)
        self.assertEqual(
            set(cluster_queryset(scope).values_list("name", flat=True)), {"UG Cluster"}
        )
        self.assertTrue(cluster_in_scope(scope, self.ug_cluster))
        self.assertFalse(cluster_in_scope(scope, self.ke_cluster))

    def test_activities_stop_at_the_border_including_schoolless_ones(self):
        from apps.activities.services import _assert_in_scope, list_activities
        from apps.core.exceptions import Forbidden

        ids = {a.id for a in list_activities({}, self.cd)}
        self.assertIn(self.ug_visit.id, ids)
        self.assertNotIn(self.ke_visit.id, ids)
        self.assertNotIn(self.ke_general.id, ids)
        _assert_in_scope(self.ug_visit, self.cd)
        with self.assertRaises(Forbidden):
            _assert_in_scope(self.ke_visit, self.cd)

    def test_admin_and_a_country_less_cd_keep_the_deployment(self):
        from apps.activities.services import list_activities

        for who in (self.admin, self.homeless_cd):
            scope = resolve_user_scope(who)
            self.assertEqual(scoped_school_queryset(scope).count(), 2, who.name)
            self.assertEqual(cluster_queryset(scope).count(), 2, who.name)
            self.assertEqual(len(list_activities({}, who)), 3, who.name)

    def test_the_cd_analytics_scope_and_its_activities_are_bounded(self):
        from apps.analytics.cd_analytics_service import (
            _country_activities,
            country_for,
            resolve_cd_scope,
        )

        self.assertEqual(country_for(self.cd), "Uganda")
        cd = resolve_cd_scope("2026", country=country_for(self.cd))
        self.assertEqual(cd.school_ids, [self.ug_school.id])
        self.assertEqual(cd.cceo_user_ids, [self.ug_cceo.id])
        acts = {a.id for a in _country_activities(cd)}
        self.assertEqual(acts, {self.ug_visit.id})
        everywhere = resolve_cd_scope("2026")
        self.assertEqual(len(everywhere.school_ids), 2)

    def test_projects_reach_the_country_through_their_schools(self):
        from apps.projects.models import Project, ProjectSchoolAssignment
        from apps.projects.scoping import scoped_projects

        ug = Project.objects.create(name="UG Project")
        ke = Project.objects.create(name="KE Project")
        ProjectSchoolAssignment.objects.create(project=ug, school=self.ug_school)
        ProjectSchoolAssignment.objects.create(project=ke, school=self.ke_school)
        Project.objects.create(name="Unplaced Project")
        Project.objects.create(
            name="KE-run Project", manager_staff_id=self.ke_cceo.staff_profile.id
        )
        self.assertEqual(
            sorted(scoped_projects(self.cd).values_list("name", flat=True)),
            ["UG Project", "Unplaced Project"],
        )
        self.assertEqual(scoped_projects(self.admin).count(), 4)

    def test_the_cd_pages_do_not_show_the_other_country(self):
        self.client.force_login(self.cd)
        for url in ("/coverage", "/dashboard", "/analytics/country-director"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertNotContains(response, "Nairobi Primary", msg_prefix=url)
        coverage = self.client.get("/coverage")
        self.assertEqual(coverage.context["total_schools"], 1)
