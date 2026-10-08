"""A scope's ids go to the database as one array, and the pages built on
them read no more than they show (owner, 2026-10-08: "work on heavy and slow
pages").

A Programme Lead's scope is their team's schools: 4,700 ids at production
size. Written out as ``id__in=[...]`` they were 4,700 placeholders in every
statement that read through the scope: Core Schools oversight sent 165,000
values in 107 statements. These tests hold the two halves of the fix: the
rows are the same rows, and the ids travel as one parameter.
"""

from __future__ import annotations

from django.db import connection
from django.db.models import Q
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.clusters.models import Cluster
from apps.core.rbac import EdifyRole
from apps.core.scoping import (
    _school_ids,
    cluster_queryset,
    direct_portfolio_schools,
    id_list,
    resolve_user_scope,
    scoped_school_queryset,
    team_oversight_schools,
)
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


def _array_parameters(queryset) -> list[list]:
    """The parameters of ``queryset``'s statement that are whole arrays."""
    _, params = queryset.query.sql_with_params()
    return [p for p in params if isinstance(p, list)]


class TeamFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Array Region")
        cls.district = District.objects.create(name="Array District", region=region)
        cls.lead = _user(
            "lead@array.test", "Lena Lead", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        cls.lead_sp = StaffProfile.objects.create(
            user=cls.lead, title="PL", country="Uganda"
        )
        cls.officer = _user("officer@array.test", "Otim Officer", EdifyRole.CCEO.value)
        cls.officer_sp = StaffProfile.objects.create(
            user=cls.officer, title="CCEO", country="Uganda"
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.lead_sp, supervisee=cls.officer_sp
        )
        cls.cluster = Cluster.objects.create(
            name="Array Cluster",
            region=region,
            district=cls.district,
            status="active",
            responsible_staff_id=cls.officer_sp.id,
        )
        cls.schools = [
            School.objects.create(
                name=f"Array Primary {n:02d}",
                school_id=f"ARR-{n:02d}",
                region_id=region.id,
                district_id=cls.district.id,
                cluster_id=cls.cluster.id,
                account_owner_id=cls.officer_sp.id,
            )
            for n in range(12)
        ]
        for school in cls.schools:
            StaffSchoolAssignment.objects.create(
                staff=cls.officer_sp, school_id=school.id
            )
        cls.elsewhere = School.objects.create(
            name="Somebody Else Primary",
            school_id="ARR-99",
            region_id=region.id,
            district_id=cls.district.id,
        )
        cls.ids = {school.id for school in cls.schools}


class IdListTest(TestCase):
    def test_nothing_is_still_the_empty_list_and_asks_the_database_nothing(self):
        self.assertEqual(id_list([]), [])
        self.assertEqual(id_list(iter(())), [])
        with self.assertNumQueries(0):
            self.assertEqual(list(School.objects.filter(id__in=id_list([]))), [])

    def test_no_schools_in_scope_asks_the_database_nothing(self):
        """A Programme Lead who holds no school of their own opens the School
        Directory: four statements that were never sent, and still are not."""
        self.assertEqual(_school_ids([]), Q(id__in=[]))
        with self.assertNumQueries(0):
            self.assertEqual(list(School.objects.filter(_school_ids([]))), [])
            self.assertEqual(School.objects.filter(_school_ids([])).count(), 0)


class ScopeBindsOneArrayTest(TeamFixture):
    def test_an_id_list_matches_the_rows_the_written_out_list_matched(self):
        ids = sorted(self.ids)[:5]
        as_array = School.objects.filter(id__in=id_list(ids))
        self.assertEqual(
            set(as_array.values_list("id", flat=True)),
            set(School.objects.filter(id__in=ids).values_list("id", flat=True)),
        )
        self.assertEqual(_array_parameters(as_array), [ids])

    def test_the_officers_own_schools_are_one_parameter(self):
        scope = resolve_user_scope(self.officer)
        for name, queryset in (
            ("directory", direct_portfolio_schools(scope)),
            ("analytics", scoped_school_queryset(scope)),
        ):
            with self.subTest(queryset=name):
                self.assertEqual(set(queryset.values_list("id", flat=True)), self.ids)
                arrays = _array_parameters(queryset)
                self.assertEqual(len(arrays), 1)
                self.assertEqual(set(arrays[0]), self.ids)

    def test_the_leads_team_schools_are_one_parameter(self):
        scope = resolve_user_scope(self.lead)
        team = team_oversight_schools(scope)
        self.assertEqual(set(team.values_list("id", flat=True)), self.ids)
        arrays = _array_parameters(team)
        self.assertEqual(len(arrays), 1)
        self.assertEqual(set(arrays[0]), self.ids)
        # And inside another statement, where the scope is a subquery.
        self.assertEqual(
            School.objects.filter(id__in=team.values("id")).count(), len(self.ids)
        )

    def test_a_person_with_no_team_watches_nothing(self):
        scope = resolve_user_scope(self.officer)
        with self.assertNumQueries(0):
            self.assertEqual(list(team_oversight_schools(scope)), [])

    def test_the_officers_clusters_are_one_parameter(self):
        scope = resolve_user_scope(self.officer)
        clusters = cluster_queryset(scope, direct_only=True)
        self.assertEqual(list(clusters.values_list("id", flat=True)), [self.cluster.id])
        self.assertIn([self.cluster.id], _array_parameters(clusters))


class CountryPortfolioReadsWhatItShowsTest(TeamFixture):
    """The country portfolio built a whole School, with its District, for
    every school in the country on every view, and wrote every school id
    into the two statements that count the plan."""

    def setUp(self):
        self.ia = _user("ia@array.test", "Ines IA", EdifyRole.IMPACT_ASSESSMENT.value)
        StaffProfile.objects.create(user=self.ia, title="IA", country="Uganda")

    def _statements(self):
        from apps.core.fy import get_operational_fy
        from apps.planning.portfolio_service import country_portfolio

        with CaptureQueriesContext(connection) as queries:
            portfolio = country_portfolio(self.ia, fy=get_operational_fy())
        return portfolio, [q["sql"] for q in queries.captured_queries]

    def test_every_school_is_listed_under_its_officer_and_lead(self):
        portfolio, _ = self._statements()
        self.assertEqual(portfolio["totals"]["schools"], len(self.schools) + 1)
        lead = next(g for g in portfolio["leads"] if g.key == self.lead_sp.id)
        officer = lead.officers[0]
        self.assertEqual(officer.name, "Otim Officer")
        row = officer.schools[0]
        self.assertEqual(row["name"], "Array Primary 00")
        self.assertEqual(row["district"], "Array District")
        self.assertEqual(row["cluster_name"], "Array Cluster")
        self.assertEqual(row["url"], "/schools/ARR-00")
        self.assertEqual(row["cluster_url"], f"/clusters/{self.cluster.id}")

    def test_it_reads_the_columns_a_row_is_built_from_not_the_school(self):
        _, statements = self._statements()
        listing = next(s for s in statements if '"school"."name"' in s)
        for column in ("shipping_address", "headteacher_name", "latitude"):
            with self.subTest(column=column):
                self.assertNotIn(column, listing)

    def test_no_statement_carries_an_id_for_every_school(self):
        _, statements = self._statements()
        for sql in statements:
            written_out = sum(1 for school_id in self.ids if f"'{school_id}'" in sql)
            # The cluster and officer lookups name the few they need.
            self.assertLess(written_out, len(self.ids), sql[:160])
