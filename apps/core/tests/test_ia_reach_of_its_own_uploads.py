"""Impact Assessment reaches the schools, SSAs and plans it loaded (owner, 2026-09-18).

Two rules turned the role that runs the school and SSA uploads into the role
that could not read them.

**A school with no region was in no country.** A school carries no country of
its own; it inherits one through ``region -> country``. An upload row whose
district cell matched no district keeps its uploaded text and leaves ``region``
null, so ``region__country`` matched nothing and the row fell out of every
country lens at once — the directory, the analytics queryset, the SSA queue, the
SSA upload's own matching step (which reported it as *outside your country*) and
the planned activities standing at it. Sixteen thousand schools and the
assessments keyed against them were loaded by Impact Assessment and then hidden
from Impact Assessment.

**One ownership row demoted the officer.** The scope resolver narrowed an IA
officer to a portfolio as soon as ``StaffSchoolAssignment`` held a row for them.
That table is account ownership, and the school upload writes a row into it for
every uploaded school whose account-owner cell matches a staff profile by name.
So the officer who ran the upload was demoted by their own file, in the request
that loaded it, with no message to say so. The reporting line says who is an
assistant; an import does not.

Both halves are asserted here together because either one alone empties the same
pages, and a fix for one would look like a fix for both.
"""

from __future__ import annotations

from datetime import date, datetime, timezone as dt_timezone

from django.test import TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity
from apps.core.rbac import EdifyRole
from apps.core.scoping import (
    activity_country_q,
    resolve_user_scope,
    school_queryset,
    scoped_school_queryset,
)
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord


def _user(email, name, role, country="Uganda"):
    user = User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    StaffProfile.objects.create(user=user, title=role, country=country)
    return user


class UnplacedSchoolsAreReachable(TestCase):
    """The region arm cannot be the only arm (see the module docstring)."""

    @classmethod
    def setUpTestData(cls):
        cls.ug_region = Region.objects.create(name="Central UG", country="Uganda")
        cls.ke_region = Region.objects.create(name="Nairobi KE", country="Kenya")
        cls.ug_district = District.objects.create(name="Wakiso", region=cls.ug_region)

        cls.ia = _user("reach-ia@t.org", "Uganda IA", EdifyRole.IMPACT_ASSESSMENT.value)
        cls.cd = _user("reach-cd@t.org", "Uganda CD", EdifyRole.COUNTRY_DIRECTOR.value)
        cls.cceo = _user("reach-cceo@t.org", "UG CCEO", EdifyRole.CCEO.value)
        cls.ke_cceo = _user(
            "reach-ke-cceo@t.org", "KE CCEO", EdifyRole.CCEO.value, country="Kenya"
        )

        cls.placed = School.objects.create(
            name="Kampala Primary",
            school_id="UG-R-001",
            region=cls.ug_region,
            district=cls.ug_district,
        )
        cls.foreign = School.objects.create(
            name="Nairobi Primary", school_id="KE-R-001", region=cls.ke_region
        )
        # The upload row whose district cell matched nothing and whose
        # account-owner cell matched nobody: region null, owner null.
        cls.unplaced = School.objects.create(
            name="Unmatched Primary",
            school_id="UG-R-002",
            uploaded_district_text="Wakisoo",
            account_owner_name_raw="A. Nobody",
            account_owner_status="unmatched",
        )
        # Region null, but an owner who is on the Uganda roster places it.
        cls.unplaced_ug_owned = School.objects.create(
            name="Owned Primary",
            school_id="UG-R-003",
            uploaded_district_text="Wakisoo",
            account_owner_id=cls.cceo.staff_profile.id,
            account_owner_status="matched",
        )
        # Region null, owner on the Kenya roster: Kenya's to fix, not Uganda's.
        cls.unplaced_ke_owned = School.objects.create(
            name="Nairobi Unmatched",
            school_id="KE-R-002",
            account_owner_id=cls.ke_cceo.staff_profile.id,
            account_owner_status="matched",
        )

    def test_the_directory_reaches_a_school_the_upload_could_not_place(self):
        for who in (self.ia, self.cd):
            with self.subTest(who=who.name):
                names = set(
                    school_queryset(resolve_user_scope(who)).values_list(
                        "name", flat=True
                    )
                )
                self.assertIn("Unmatched Primary", names)
                self.assertIn("Owned Primary", names)

    def test_analytics_read_the_same_set_as_the_directory(self):
        names = set(
            scoped_school_queryset(resolve_user_scope(self.ia)).values_list(
                "name", flat=True
            )
        )
        self.assertIn("Unmatched Primary", names)
        self.assertIn("Owned Primary", names)

    def test_the_border_still_holds_for_a_school_that_has_one(self):
        """Reaching the unplaced must not reach the placed-elsewhere."""
        names = set(
            school_queryset(resolve_user_scope(self.ia)).values_list("name", flat=True)
        )
        self.assertNotIn("Nairobi Primary", names)
        self.assertNotIn("Nairobi Unmatched", names)

    def test_an_unplaced_school_is_offered_to_the_lens_that_can_fix_it(self):
        """Owned nowhere means every country sees it; owned somewhere means one."""
        ke_ia = _user(
            "reach-ke-ia@t.org",
            "KE IA",
            EdifyRole.IMPACT_ASSESSMENT.value,
            country="Kenya",
        )
        names = set(
            school_queryset(resolve_user_scope(ke_ia)).values_list("name", flat=True)
        )
        self.assertIn("Unmatched Primary", names)
        self.assertIn("Nairobi Unmatched", names)
        self.assertNotIn("Owned Primary", names)

    def test_an_owner_with_no_country_on_file_places_nobody(self):
        stateless = _user(
            "reach-none@t.org", "No-country CCEO", EdifyRole.CCEO.value, country=""
        )
        School.objects.create(
            name="Stateless-owned Primary",
            school_id="UG-R-004",
            account_owner_id=stateless.staff_profile.id,
            account_owner_status="matched",
        )
        names = set(
            school_queryset(resolve_user_scope(self.ia)).values_list("name", flat=True)
        )
        self.assertIn("Stateless-owned Primary", names)

    def test_the_ssa_queue_reaches_the_records_keyed_against_them(self):
        from apps.ssa.services import readable_records

        record = SsaRecord.objects.create(
            school=self.unplaced,
            date_of_ssa=datetime(2026, 2, 1, tzinfo=dt_timezone.utc),
            fy="2026",
            quarter="Q3",
        )
        self.assertIn(record.id, {r.id for r in readable_records(self.ia)})

    def test_the_ssa_upload_no_longer_calls_them_another_country(self):
        from apps.ssa.upload_service import _schools_in_reach

        inside, outside = _schools_in_reach(
            self.ia, ["UG-R-001", "UG-R-002", "UG-R-003", "KE-R-001", "KE-R-002"]
        )
        self.assertEqual(set(inside), {"UG-R-001", "UG-R-002", "UG-R-003"})
        self.assertEqual(set(outside), {"KE-R-001", "KE-R-002"})

    def test_the_analytics_dashboard_counts_what_the_directory_lists(self):
        """The page's own school filter, not `region__country` written twice.

        Every fixture school is `not_done`, so "Schools without SSA" counts the
        dashboard's whole scope — the reading that showed 1 where the directory
        listed 3.
        """
        from apps.analytics.analytics_dashboard_service import AnalyticsDashboardService

        data = AnalyticsDashboardService.get_analytics_data(self.ia, {})
        counted = next(i for i in data["insights"] if i["key"] == "no_ssa")["count"]
        self.assertEqual(counted, school_queryset(resolve_user_scope(self.ia)).count())
        self.assertEqual(counted, 3)

    def test_the_country_rollup_keeps_the_work_planned_at_them(self):
        from apps.hr.contribution_scope import scope_activities

        here = Activity.objects.create(
            activity_type="school_visit",
            status="scheduled",
            school=self.unplaced,
            fy="2026",
            planned_date=date(2026, 3, 4),
            responsible_staff_id=self.cceo.staff_profile.id,
        )
        there = Activity.objects.create(
            activity_type="school_visit",
            status="scheduled",
            school=self.unplaced_ke_owned,
            fy="2026",
            planned_date=date(2026, 3, 4),
            responsible_staff_id=self.ke_cceo.staff_profile.id,
        )
        ids = set(
            scope_activities(
                Activity.objects.filter(deleted_at__isnull=True), country="Uganda"
            ).values_list("id", flat=True)
        )
        self.assertIn(here.id, ids)
        self.assertNotIn(there.id, ids)

    def test_the_ssa_performance_page_survives_a_school_with_no_district(self):
        """A district table has no row for a school that has no district.

        Reaching these schools put them in front of a by-district grouping
        written inline rather than through `_breakdown_rows`, which skips its
        own ungrouped rows. The district row was built with `name=None`, the
        sort compared None with a string, and the whole page 500ed. They still
        count in the header total and every overall average — the by-district
        grouping is the one place a district-less school cannot appear.
        """
        from apps.analytics.ssa_performance_service import build_dashboard

        data = build_dashboard(self.ia, {})
        self.assertEqual(
            data["kpis"]["total_schools"],
            scoped_school_queryset(resolve_user_scope(self.ia)).count(),
        )
        self.assertNotIn(None, [row["id"] for row in data["districts"]])
        self.assertNotIn(None, [row["name"] for row in data["districts"]])

    def test_no_school_at_all_is_not_an_unplaced_one(self):
        """A null FK reads null in every column behind it.

        `school__region__isnull=True` is true of an activity with no school as
        well as one at an unplaced school, so the unplaced arm would have swept
        up every cluster training in every other country. The row with no school
        is placed by its cluster, or by the person responsible for it.
        """
        from apps.clusters.models import Cluster

        ke_district = District.objects.create(name="Kiambu", region=self.ke_region)
        ke_cluster = Cluster.objects.create(
            name="KE Cluster", region=self.ke_region, district=ke_district
        )
        training = Activity.objects.create(
            activity_type="general_training",
            status="scheduled",
            cluster=ke_cluster,
            fy="2026",
            planned_date=date(2026, 3, 5),
            responsible_staff_id=self.ke_cceo.staff_profile.id,
        )
        scope = resolve_user_scope(self.ia)
        self.assertNotIn(
            training.id,
            set(
                Activity.objects.filter(activity_country_q(scope)).values_list(
                    "id", flat=True
                )
            ),
        )

    def test_country_oversight_reaches_the_work_planned_at_them(self):
        """A CCEO's visit to an unplaced school is the country's planned work."""
        visit = Activity.objects.create(
            activity_type="school_visit",
            status="scheduled",
            school=self.unplaced,
            fy="2026",
            planned_date=date(2026, 3, 2),
            responsible_staff_id=self.cceo.staff_profile.id,
        )
        scope = resolve_user_scope(self.ia)
        ids = set(
            Activity.objects.filter(activity_country_q(scope)).values_list(
                "id", flat=True
            )
        )
        self.assertIn(visit.id, ids)


class OwnershipDoesNotDemoteTheOfficer(TestCase):
    """Account ownership is written by an import; supervision is not."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Central UG", country="Uganda")
        cls.district = District.objects.create(name="Wakiso", region=cls.region)
        cls.school = School.objects.create(
            name="Kampala Primary",
            school_id="UG-D-001",
            region=cls.region,
            district=cls.district,
        )
        cls.other = School.objects.create(
            name="Entebbe Primary",
            school_id="UG-D-002",
            region=cls.region,
            district=cls.district,
        )
        cls.officer = _user(
            "demote-ia@t.org", "Uganda IA", EdifyRole.IMPACT_ASSESSMENT.value
        )

    def test_being_named_account_owner_keeps_the_country_lens(self):
        """The row the school upload writes for a matched account-owner cell."""
        StaffSchoolAssignment.objects.create(
            staff=self.officer.staff_profile, school_id=self.school.id
        )
        scope = resolve_user_scope(self.officer)
        self.assertTrue(scope.country_scope)
        self.assertEqual(
            set(school_queryset(scope).values_list("name", flat=True)),
            {"Kampala Primary", "Entebbe Primary"},
        )

    def test_an_assistant_under_an_ia_officer_is_still_their_portfolio(self):
        assistant = _user(
            "demote-ia2@t.org", "IA Assistant", EdifyRole.IMPACT_ASSESSMENT.value
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.officer.staff_profile, supervisee=assistant.staff_profile
        )
        StaffSchoolAssignment.objects.create(
            staff=assistant.staff_profile, school_id=self.school.id
        )
        scope = resolve_user_scope(assistant)
        self.assertFalse(scope.country_scope)
        self.assertEqual(
            set(school_queryset(scope).values_list("name", flat=True)),
            {"Kampala Primary"},
        )

    def test_reporting_to_the_country_director_is_not_an_assistant(self):
        cd = _user("demote-cd@t.org", "Uganda CD", EdifyRole.COUNTRY_DIRECTOR.value)
        StaffSupervisorAssignment.objects.create(
            supervisor=cd.staff_profile, supervisee=self.officer.staff_profile
        )
        StaffSchoolAssignment.objects.create(
            staff=self.officer.staff_profile, school_id=self.school.id
        )
        self.assertTrue(resolve_user_scope(self.officer).country_scope)

    def test_a_supervisor_holding_the_role_among_several_still_counts(self):
        """A reporting line does not change when its supervisor switches tabs."""
        wearer = _user(
            "demote-multi@t.org", "Two-hat IA", EdifyRole.COUNTRY_DIRECTOR.value
        )
        wearer.roles = [
            EdifyRole.COUNTRY_DIRECTOR.value,
            EdifyRole.IMPACT_ASSESSMENT.value,
        ]
        wearer.save(update_fields=["roles"])
        assistant = _user(
            "demote-ia3@t.org", "IA Assistant", EdifyRole.IMPACT_ASSESSMENT.value
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=wearer.staff_profile, supervisee=assistant.staff_profile
        )
        self.assertFalse(resolve_user_scope(assistant).country_scope)
