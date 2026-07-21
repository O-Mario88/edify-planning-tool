"""One Scope — the RVP means the same thing on every surface.

Before this, RVP scope resolved at least four different ways: region-filtered
in SSA/impact (empty in practice, because nothing populates region rows),
country-wide on its own dashboard, own-country in HR, and supervisees-only in
leave. The pages the role exists for silently rendered empty.
"""

from __future__ import annotations

from django.test import Client, TestCase

from apps.accounts.models import StaffGeographyAssignment, StaffProfile, User
from apps.core.rbac import EdifyRole
from apps.core.scoping import resolve_user_scope, scoped_school_queryset
from apps.geography.models import District, Region
from apps.schools.models import School


def _user(email, name, role):
    return User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="pw12345678",
        is_active=True,
    )


class RvpScopeResolutionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region_a = Region.objects.create(name="Region A")
        cls.region_b = Region.objects.create(name="Region B")
        cls.district_a = District.objects.create(name="District A", region=cls.region_a)
        cls.district_b = District.objects.create(name="District B", region=cls.region_b)
        cls.school_a = School.objects.create(
            name="School A",
            school_id="SA-1",
            region_id=cls.region_a.id,
            district_id=cls.district_a.id,
        )
        cls.school_b = School.objects.create(
            name="School B",
            school_id="SB-1",
            region_id=cls.region_b.id,
            district_id=cls.district_b.id,
        )

    def test_unassigned_rvp_oversees_the_whole_deployment(self):
        """The seed assigns an RVP no geography. Treating that as 'no data'
        emptied every intelligence page for the role they were built for."""
        rvp = _user("rvp-none@t.org", "Remy", EdifyRole.REGIONAL_VICE_PRESIDENT.value)
        StaffProfile.objects.create(user=rvp, title="RVP", country="Uganda")
        scope = resolve_user_scope(rvp)
        self.assertTrue(scope.can_view_summary_only)
        self.assertFalse(scope.rvp_region_scoped)
        self.assertEqual(scoped_school_queryset(scope).count(), 2)

    def test_region_assigned_rvp_is_narrowed_to_its_regions(self):
        rvp = _user("rvp-a@t.org", "Rita", EdifyRole.REGIONAL_VICE_PRESIDENT.value)
        sp = StaffProfile.objects.create(user=rvp, title="RVP", country="Uganda")
        StaffGeographyAssignment.objects.create(staff=sp, region_id=self.region_a.id)
        scope = resolve_user_scope(rvp)
        self.assertTrue(scope.rvp_region_scoped)
        self.assertEqual(scope.region_ids, [self.region_a.id])
        names = list(scoped_school_queryset(scope).values_list("name", flat=True))
        self.assertEqual(names, ["School A"])

    def test_district_assignment_resolves_to_its_region(self):
        """The staff-setup UI writes district rows, not region rows — an RVP
        set up through the real UI had no region and therefore no data."""
        rvp = _user("rvp-d@t.org", "Ravi", EdifyRole.REGIONAL_VICE_PRESIDENT.value)
        sp = StaffProfile.objects.create(user=rvp, title="RVP", country="Uganda")
        StaffGeographyAssignment.objects.create(
            staff=sp, district_id=self.district_b.id
        )
        scope = resolve_user_scope(rvp)
        self.assertTrue(scope.rvp_region_scoped)
        self.assertEqual(scope.region_ids, [self.region_b.id])
        names = list(scoped_school_queryset(scope).values_list("name", flat=True))
        self.assertEqual(names, ["School B"])

    def test_rvp_never_gains_school_level_identity(self):
        """Widening the aggregate scope must not widen row identity."""
        rvp = _user("rvp-id@t.org", "Rue", EdifyRole.REGIONAL_VICE_PRESIDENT.value)
        StaffProfile.objects.create(user=rvp, title="RVP", country="Uganda")
        scope = resolve_user_scope(rvp)
        self.assertFalse(scope.can_view_school_level_detail)
        from apps.core.scoping import school_queryset

        self.assertEqual(school_queryset(scope).count(), 0)


class RvpPagesReturnDataTests(TestCase):
    """The three sidebar links that were dead ends for the RVP."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Central")
        cls.district = District.objects.create(name="Kampala", region=cls.region)
        for i in range(3):
            School.objects.create(
                name=f"School {i}",
                school_id=f"S-{i}",
                region_id=cls.region.id,
                district_id=cls.district.id,
            )

    def setUp(self):
        self.rvp = _user(
            "rvp-pg@t.org", "Remy", EdifyRole.REGIONAL_VICE_PRESIDENT.value
        )
        StaffProfile.objects.create(user=self.rvp, title="RVP", country="Uganda")
        self.client = Client()
        self.client.force_login(self.rvp)

    def test_ssa_performance_sees_the_school_population(self):
        from apps.analytics.ssa_performance_service import _scoped_schools

        schools, scope = _scoped_schools(self.rvp)
        self.assertEqual(schools.count(), 3)
        self.assertFalse(scope.can_view_school_level_detail)

    def test_impact_analytics_sees_the_school_population(self):
        from apps.analytics.impact_engine import _scoped_schools

        schools, _scope = _scoped_schools(self.rvp)
        self.assertEqual(schools.count(), 3)

    def test_analytics_rollups_are_not_zeroed(self):
        from apps.analytics.services import _scoped_schools

        schools, _scope = _scoped_schools(self.rvp)
        self.assertEqual(schools.count(), 3)

    def test_ssa_page_loads(self):
        self.assertEqual(self.client.get("/ssa").status_code, 200)

    def test_analytics_page_loads(self):
        self.assertEqual(self.client.get("/analytics").status_code, 200)


class CdAggregateScopeTests(TestCase):
    """The CD's role-overview reported '0 schools' beside country-wide SSA,
    because the operational-directory block was applied to aggregates too."""

    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Northern")
        district = District.objects.create(name="Gulu", region=region)
        for i in range(4):
            School.objects.create(
                name=f"CD School {i}",
                school_id=f"CDS-{i}",
                region_id=region.id,
                district_id=district.id,
            )

    def test_cd_aggregates_are_country_wide(self):
        from apps.analytics.services import _scoped_schools

        cd = _user("cd-agg@t.org", "Cody", EdifyRole.COUNTRY_DIRECTOR.value)
        StaffProfile.objects.create(user=cd, title="CD", country="Uganda")
        schools, scope = _scoped_schools(cd)
        self.assertTrue(scope.country_scope)
        self.assertEqual(schools.count(), 4)

    def test_cd_operational_directory_still_honours_its_flag(self):
        """Widening *aggregates* must not change the *operational* directory
        rule, which stays governed by ALLOW_CD_OPERATIONAL_PLANNING (default
        True in this deployment — the CD works the directory; set it false to
        enforce the analytics-only doctrine)."""
        from django.test import override_settings

        from apps.core.scoping import school_queryset

        cd = _user("cd-dir@t.org", "Cody", EdifyRole.COUNTRY_DIRECTOR.value)
        StaffProfile.objects.create(user=cd, title="CD", country="Uganda")
        scope = resolve_user_scope(cd)

        with override_settings(ALLOW_CD_OPERATIONAL_PLANNING=True):
            self.assertEqual(school_queryset(scope).count(), 4)
        with override_settings(ALLOW_CD_OPERATIONAL_PLANNING=False):
            self.assertEqual(school_queryset(scope).count(), 0)

    def test_cd_aggregates_survive_the_directory_flag(self):
        """Aggregates are country-wide either way — that is the whole point of
        separating the two rules."""
        from django.test import override_settings

        from apps.analytics.services import _scoped_schools

        cd = _user("cd-flag@t.org", "Cora", EdifyRole.COUNTRY_DIRECTOR.value)
        StaffProfile.objects.create(user=cd, title="CD", country="Uganda")
        with override_settings(ALLOW_CD_OPERATIONAL_PLANNING=False):
            schools, _ = _scoped_schools(cd)
            self.assertEqual(schools.count(), 4)
