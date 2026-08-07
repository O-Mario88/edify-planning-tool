"""The country picture of closure: what was lost, where, and at what cost.

The rules worth a test are the ones that would misreport a country — a school
counted as lost after it reopened, a learner total that quietly reads missing
enrolment as zero, or a concentration hidden inside a national average.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools import closure_analytics as ca
from apps.schools import lifecycle_service as svc
from apps.schools.lifecycle_models import ClosureReason, ClosureType
from apps.schools.models import School

EXPLANATION = "The owner confirmed the school stopped operating at the end of term."
REOPENING = "Confirmed operating again under new management."


class ClosureImpactFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(id="r1", name="Central")
        cls.other_region = Region.objects.create(id="r2", name="Eastern")
        cls.kampala = District.objects.create(
            id="d1", name="Kampala", region=cls.region
        )
        cls.jinja = District.objects.create(
            id="d2", name="Jinja", region=cls.other_region
        )
        cls.cceo_user, cls.cceo = cls._staff("james@c.test", "James", EdifyRole.CCEO)
        cls.cd_user, cls.cd = cls._staff(
            "cd@c.test", "Clare", EdifyRole.COUNTRY_DIRECTOR
        )
        cls.pl_user, cls.pl = cls._staff(
            "mary@c.test", "Mary", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        StaffSupervisorAssignment.objects.create(supervisee=cls.cceo, supervisor=cls.pl)

    @classmethod
    def _staff(cls, email, name, role):
        user = User.objects.create(
            email=email,
            name=name,
            roles=[role.value],
            active_role=role.value,
            status="active",
            is_active=True,
        )
        return user, StaffProfile.objects.create(user=user, title=name)

    def school(self, ref, *, enrollment=200, district=None):
        district = district or self.kampala
        school = School.objects.create(
            school_id=ref,
            name=f"School {ref}",
            district=district,
            region=district.region,
            enrollment=enrollment,
            account_owner_id=self.cceo.id,
            account_owner_name_raw="James",
        )
        StaffSchoolAssignment.objects.create(staff=self.cceo, school_id=school.id)
        return school

    def close(self, school, *, reason=ClosureReason.FINANCIAL, effective=None):
        return svc.close_school(
            school.id,
            {
                "closure_type": ClosureType.PERMANENT,
                "reason_category": reason,
                "reason": EXPLANATION,
                "effective_date": effective or date.today(),
            },
            self.cceo_user,
        )


class WhatTheCountryLostTest(ClosureImpactFixture):
    def test_losses_count_schools_and_their_actual_enrolment(self):
        self.close(self.school("s1", enrollment=200))
        self.close(self.school("s2", enrollment=340))

        summary = ca.country_summary()

        self.assertEqual(summary["schools_lost"], 2)
        self.assertEqual(summary["learners_lost"], 540)

    def test_a_reopened_school_is_not_a_loss(self):
        """It is operating again. Counting it reports a smaller programme."""
        school = self.school("s1", enrollment=200)
        self.close(school)
        self.close(self.school("s2", enrollment=340))

        svc.reopen_school(
            school.id, {"reason": REOPENING, "enrollment": 210}, self.cceo_user
        )
        summary = ca.country_summary()

        self.assertEqual(summary["schools_lost"], 1)
        self.assertEqual(summary["learners_lost"], 340)
        self.assertEqual(summary["reopened"], 1)

    def test_missing_enrolment_is_stated_as_coverage_not_read_as_zero(self):
        """A bare total implies a completeness this data does not have."""
        self.close(self.school("s1", enrollment=200))
        self.close(self.school("s2", enrollment=None))

        summary = ca.country_summary()

        self.assertEqual(summary["schools_lost"], 2)
        self.assertEqual(summary["learners_lost"], 200)
        self.assertEqual(summary["schools_counted"], 1)
        self.assertEqual(summary["schools_without_enrollment"], 1)

    def test_the_average_school_size_divides_by_what_was_counted(self):
        """Dividing by all closed schools would report an average smaller than
        any real school, because the uncounted ones contribute nothing."""
        self.close(self.school("s1", enrollment=200))
        self.close(self.school("s2", enrollment=400))
        self.close(self.school("s3", enrollment=None))

        summary = ca.country_summary()

        self.assertEqual(summary["average_school_size"], 300)

    def test_the_average_is_none_when_nothing_carries_a_count(self):
        self.close(self.school("s1", enrollment=None))

        self.assertIsNone(ca.country_summary()["average_school_size"])

    def test_an_empty_period_reports_zeros_and_no_average(self):
        summary = ca.country_summary()

        self.assertEqual(summary["schools_lost"], 0)
        self.assertEqual(summary["learners_lost"], 0)
        self.assertIsNone(summary["average_school_size"])


class WhatItCostThePlanTest(ClosureImpactFixture):
    """Closing a school stops work already committed to it."""

    def test_delivery_impact_comes_from_the_closure_snapshots(self):
        from apps.activities.models import Activity, ActivityScheduleCostLine
        from apps.core.fy import get_operational_fy

        fy = get_operational_fy()
        school = self.school("s1")
        when = date.today() + timedelta(days=10)
        activity = Activity.objects.create(
            activity_type="school_visit",
            school=school,
            fy=fy,
            quarter="Q1",
            planned_date=when,
            planned_month=when.month,
            status="scheduled",
            responsible_staff_id=self.cceo.id,
        )
        ActivityScheduleCostLine.objects.create(
            activity=activity,
            cost_setting_key="school_visit_transport",
            label="Transport",
            unit_cost=90_000,
            quantity=1,
            amount=90_000,
            fiscal_year=fy,
            month=when.month,
        )

        self.close(school)
        summary = ca.country_summary()

        self.assertEqual(summary["activities_cancelled"], 1)
        self.assertEqual(summary["budget_released"], 90_000)


class WhereTheLossesAreTest(ClosureImpactFixture):
    def test_districts_are_ranked_worst_first(self):
        self.close(self.school("s1", district=self.kampala))
        self.close(self.school("s2", district=self.kampala))
        self.close(self.school("s3", district=self.jinja))

        rows = ca.by_place("district")

        self.assertEqual(rows[0]["name"], "Kampala")
        self.assertEqual(rows[0]["schools"], 2)
        self.assertEqual(rows[1]["name"], "Jinja")
        self.assertEqual(rows[1]["schools"], 1)

    def test_concentration_is_visible_where_a_national_total_hides_it(self):
        """Three lost in one district and three spread across three are the
        same national number and completely different problems."""
        for i in range(3):
            self.close(self.school(f"k{i}", district=self.kampala))

        rows = ca.by_place("district")
        summary = ca.country_summary()

        self.assertEqual(summary["schools_lost"], 3)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["schools"], 3)

    def test_regions_group_too(self):
        self.close(self.school("s1", district=self.kampala))
        self.close(self.school("s2", district=self.jinja))

        rows = {r["name"]: r for r in ca.by_place("region")}

        self.assertEqual(rows["Central"]["schools"], 1)
        self.assertEqual(rows["Eastern"]["schools"], 1)

    def test_a_reopened_school_leaves_its_district_total(self):
        school = self.school("s1", district=self.kampala)
        self.close(school)
        svc.reopen_school(
            school.id, {"reason": REOPENING, "enrollment": 210}, self.cceo_user
        )

        self.assertEqual(ca.by_place("district"), [])

    def test_grouping_by_anything_else_is_refused(self):
        """An unchecked field would let a query string reach the ORM."""
        with self.assertRaises(ValueError):
            ca.by_place("account_owner_id")

    def test_place_totals_add_up_to_the_country_total(self):
        self.close(self.school("s1", enrollment=200, district=self.kampala))
        self.close(self.school("s2", enrollment=340, district=self.jinja))
        self.close(self.school("s3", enrollment=None, district=self.jinja))

        summary = ca.country_summary()
        rows = ca.by_place("district")

        self.assertEqual(sum(r["schools"] for r in rows), summary["schools_lost"])
        self.assertEqual(sum(r["learners"] for r in rows), summary["learners_lost"])
        self.assertEqual(
            sum(r["schools_without_enrollment"] for r in rows),
            summary["schools_without_enrollment"],
        )


class ThePageIsReachableTest(ClosureImpactFixture):
    def _client(self, user):
        from django.test import Client

        c = Client()
        c.force_login(user)
        return c

    def test_the_cd_can_open_it(self):
        self.close(self.school("s1", district=self.kampala))

        response = self._client(self.cd_user).get("/analytics/school-closures")

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("School Closures", body)
        self.assertIn("Kampala", body)

    def test_a_cceo_cannot(self):
        response = self._client(self.cceo_user).get("/analytics/school-closures")

        self.assertIn(response.status_code, (302, 403))

    def test_an_empty_period_says_so_rather_than_showing_zeros(self):
        response = self._client(self.cd_user).get("/analytics/school-closures")

        self.assertEqual(response.status_code, 200)
        self.assertIn("No schools closed in this period", response.content.decode())

    def test_grouping_by_region_is_honoured(self):
        self.close(self.school("s1", district=self.kampala))

        body = (
            self._client(self.cd_user)
            .get("/analytics/school-closures?by=region&period=all")
            .content.decode()
        )

        self.assertIn("Central", body)

    def test_an_unknown_grouping_falls_back_rather_than_erroring(self):
        self.close(self.school("s1", district=self.kampala))

        response = self._client(self.cd_user).get(
            "/analytics/school-closures?by=account_owner_id&period=all"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Kampala", response.content.decode())

    def test_the_filter_swaps_only_the_body(self):
        self.close(self.school("s1", district=self.kampala))

        response = self._client(self.cd_user).get(
            "/analytics/school-closures?period=all", headers={"HX-Request": "true"}
        )

        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("<h1", body)
        self.assertIn("Schools lost", body)


class TheTwoClosurePagesStaySeparateTest(ClosureImpactFixture):
    """IA asks which records are wrong; the CD asks what the country lost.

    One page mixing work-to-fix with country performance leaves nobody sure
    which numbers they are accountable for, so the split is deliberate and the
    permissions differ.
    """

    def _client(self, user):
        from django.test import Client

        c = Client()
        c.force_login(user)
        return c

    def test_the_cd_does_not_get_the_ia_worklist(self):
        response = self._client(self.cd_user).get("/analytics/closure-quality")

        self.assertIn(response.status_code, (302, 403))

    def test_the_country_page_counts_losses_not_records(self):
        """A reopened school is a record IA still cares about and a school the
        country did not lose. The two pages must disagree here, on purpose."""
        school = self.school("s1", enrollment=200)
        self.close(school)
        svc.reopen_school(
            school.id, {"reason": REOPENING, "enrollment": 210}, self.cceo_user
        )

        self.assertEqual(ca.country_summary()["schools_lost"], 0)
        self.assertEqual(ca.closure_quality()["recorded"], 1)


class RvpSeesTheirRegionsOnlyTest(ClosureImpactFixture):
    """RVP is summary-only and region-scoped.

    Two rules, and they are separate: *which* closures are counted (their
    assigned regions) and *what detail* is shown (aggregates, never a school
    row). Getting the first right while leaking the second would still be a
    breach, so both are tested.
    """

    def _client(self, user):
        from django.test import Client

        c = Client()
        c.force_login(user)
        return c

    def _rvp(self, *regions, email="rvp@c.test"):
        from apps.accounts.models import StaffGeographyAssignment

        user, staff = self._staff(email, "Rita", EdifyRole.REGIONAL_VICE_PRESIDENT)
        for region in regions:
            StaffGeographyAssignment.objects.create(staff=staff, region_id=region.id)
        return user

    def _close_one_each(self):
        self.close(self.school("s1", enrollment=200, district=self.kampala))
        self.close(self.school("s2", enrollment=340, district=self.jinja))

    def test_closures_outside_their_regions_are_not_counted(self):
        from apps.core.scoping import resolve_user_scope

        self._close_one_each()
        scope = resolve_user_scope(self._rvp(self.region))  # Central only

        summary = ca.country_summary(scope=scope)

        self.assertEqual(summary["schools_lost"], 1)
        self.assertEqual(summary["learners_lost"], 200)

    def test_the_place_breakdown_is_scoped_too(self):
        """A total that respects scope and a table that does not is worse than
        neither — the numbers disagree and the wider one is believed."""
        from apps.core.scoping import resolve_user_scope

        self._close_one_each()
        scope = resolve_user_scope(self._rvp(self.region))

        rows = ca.by_place("district", scope=scope)

        self.assertEqual([r["name"] for r in rows], ["Kampala"])

    def test_reasons_and_trend_are_scoped_as_well(self):
        from apps.core.scoping import resolve_user_scope

        self._close_one_each()
        scope = resolve_user_scope(self._rvp(self.region))

        self.assertEqual(sum(r["total"] for r in ca.by_reason(scope=scope)), 1)
        self.assertEqual(sum(r["total"] for r in ca.monthly_trend(scope=scope)), 1)

    def test_an_rvp_covering_both_regions_sees_both(self):
        from apps.core.scoping import resolve_user_scope

        self._close_one_each()
        scope = resolve_user_scope(self._rvp(self.region, self.other_region))

        self.assertEqual(ca.country_summary(scope=scope)["schools_lost"], 2)

    def test_an_rvp_with_no_geography_oversees_everything(self):
        """Treating "unassigned" as "assigned to nothing" empties the pages
        built for this role. `rvp_region_scoped` records which case applies."""
        from apps.core.scoping import resolve_user_scope

        self._close_one_each()
        user, _ = self._staff(
            "rvp2@c.test", "Raymond", EdifyRole.REGIONAL_VICE_PRESIDENT
        )
        scope = resolve_user_scope(user)

        self.assertFalse(scope.rvp_region_scoped)
        self.assertEqual(ca.country_summary(scope=scope)["schools_lost"], 2)

    def test_no_school_identity_reaches_an_rvp(self):
        """The invariant that makes this page safe to share with a
        summary-only role. If a per-school list is ever added, this fails."""
        self._close_one_each()
        rvp = self._rvp(self.region, self.other_region)

        body = (
            self._client(rvp)
            .get("/analytics/school-closures?period=all")
            .content.decode()
        )

        self.assertEqual(
            self._client(rvp).get("/analytics/school-closures").status_code, 200
        )
        self.assertNotIn("School s1", body)
        self.assertNotIn("School s2", body)
        self.assertNotIn(">s1<", body)
        # The aggregates it IS entitled to are present.
        self.assertIn("Kampala", body)
        self.assertIn("Schools lost", body)

    def test_the_page_names_the_scope_rather_than_calling_it_the_country(self):
        """ "The country lost 40 schools" reads as the country. It is not."""
        self._close_one_each()

        body = (
            self._client(self._rvp(self.region))
            .get("/analytics/school-closures?period=all")
            .content.decode()
        )

        self.assertIn("Central", body)

    def test_the_cd_still_sees_the_whole_country(self):
        from apps.core.scoping import resolve_user_scope

        self._close_one_each()
        scope = resolve_user_scope(self.cd_user)

        self.assertEqual(ca.country_summary(scope=scope)["schools_lost"], 2)

    def test_no_scope_means_country_not_nothing(self):
        """`scope=None` is the unscoped call, not a locked door."""
        self._close_one_each()

        self.assertEqual(ca.country_summary()["schools_lost"], 2)
