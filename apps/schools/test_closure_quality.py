"""Closure quality: the numbers IA acts on, and the ones it must never see.

The rules worth a test are the ones that would send somebody to fix the wrong
thing — a duplicate record counted as a school loss, a missing enrolment
silently read as zero, or a rate that reports 0% when there was nothing to
divide by.
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
from apps.schools.lifecycle_models import ClosureReason, ClosureType, SchoolClosure
from apps.schools.models import School

EXPLANATION = "The owner confirmed the school stopped operating at the end of term."


class ClosureQualityFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(id="r1", name="Central")
        cls.district = District.objects.create(
            id="d1", name="Kampala", region=cls.region
        )
        cls.cceo_user, cls.cceo = cls._staff("james@c.test", "James", EdifyRole.CCEO)
        cls.ia_user, cls.ia = cls._staff(
            "ia@c.test", "Irene", EdifyRole.IMPACT_ASSESSMENT
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

    def school(self, ref, *, enrollment=200):
        school = School.objects.create(
            school_id=ref,
            name=f"School {ref}",
            district=self.district,
            region=self.region,
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


class ADuplicateIsNeverAClosureTest(ClosureQualityFixture):
    """The invariant this page depends on.

    `close_school` refuses a duplicate-record reason outright, so no
    `SchoolClosure` can ever carry one. Anything counting duplicates out of
    closure reasons would therefore be permanently zero and read as a clean
    desk. The signal has to come from the school's own flag instead, and this
    test pins the reason why.
    """

    def test_closing_a_school_as_a_duplicate_is_refused(self):
        from apps.core.exceptions import BadRequest

        with self.assertRaises(BadRequest):
            self.close(self.school("s1"), reason=ClosureReason.DUPLICATE_RECORD)

        self.assertEqual(SchoolClosure.objects.count(), 0)

    def test_no_closure_in_the_table_carries_a_data_quality_reason(self):
        from apps.schools.lifecycle_models import DATA_QUALITY_REASONS

        self.close(self.school("s1"))
        self.close(self.school("s2"), reason=ClosureReason.LOW_ENROLMENT)

        self.assertFalse(
            SchoolClosure.objects.filter(
                reason_category__in=DATA_QUALITY_REASONS
            ).exists()
        )


class StrandedDuplicatesTest(ClosureQualityFixture):
    """Closed while still flagged as a possible duplicate.

    Worse than either problem alone: the closure removes the school from the
    directory, so the merge that would have reconciled the two histories now
    never happens.
    """

    def _flagged(self, ref):
        school = self.school(ref)
        School.objects.filter(id=school.id).update(duplicate_status="potential")
        return school

    def test_it_is_counted_and_flagged(self):
        self.close(self._flagged("s1"))
        self.close(self.school("s2"))  # clean

        summary = ca.closure_quality()
        rows = ca.needs_attention()

        self.assertEqual(summary["recorded"], 2)
        self.assertEqual(summary["stranded_duplicates"], 1)
        self.assertEqual(len(rows), 1)
        self.assertIn("stranded_duplicate", {f["key"] for f in rows[0]["flags"]})

    def test_a_resolved_duplicate_is_not_flagged(self):
        self.close(self.school("s1"))

        self.assertEqual(ca.closure_quality()["stranded_duplicates"], 0)
        self.assertEqual(ca.needs_attention(), [])


class MissingDataIsReportedTest(ClosureQualityFixture):
    def test_a_closure_with_no_enrolment_is_counted_as_a_gap(self):
        self.close(self.school("s1", enrollment=None))

        summary = ca.closure_quality()

        self.assertEqual(summary["missing_enrollment"], 1)
        self.assertEqual(summary["enrollment_removed"], 0)

    def test_it_appears_on_the_worklist_saying_why(self):
        self.close(self.school("s1", enrollment=None))

        rows = ca.needs_attention()

        self.assertEqual(len(rows), 1)
        self.assertIn("no_enrollment", {f["key"] for f in rows[0]["flags"]})

    def test_rates_are_none_rather_than_zero_when_nothing_closed(self):
        """0% reads as a perfect record. There is no record."""
        summary = ca.closure_quality()

        self.assertEqual(summary["recorded"], 0)
        self.assertIsNone(summary["reopening_rate"])
        self.assertIsNone(summary["average_recording_lag"])


class WeakGroundAndLagTest(ClosureQualityFixture):
    def test_closing_on_unconfirmed_operation_is_flagged(self):
        self.close(self.school("s1"), reason=ClosureReason.UNCONFIRMED)

        summary = ca.closure_quality()
        rows = ca.needs_attention()

        self.assertEqual(summary["weak_ground"], 1)
        self.assertIn("weak_ground", {f["key"] for f in rows[0]["flags"]})

    def test_a_closure_recorded_late_reports_its_lag(self):
        """While the gap is open the country reports a school it has lost."""
        long_ago = date.today() - timedelta(days=90)
        self.close(self.school("s1"), effective=long_ago)

        summary = ca.closure_quality()

        self.assertGreaterEqual(summary["average_recording_lag"], 89)
        self.assertEqual(summary["stale_recordings"], 1)

    def test_a_late_recording_reaches_the_worklist(self):
        """Every tile has to lead to the closures it counts.

        This one did not: "recorded late" was counted in the summary and the
        closure appeared in no list, so the number was unfollowable.
        """
        self.close(self.school("s1"), effective=date.today() - timedelta(days=90))

        rows = ca.needs_attention()

        self.assertEqual(len(rows), 1)
        self.assertIn("recorded_late", {f["key"] for f in rows[0]["flags"]})
        self.assertTrue(rows[0]["is_stale"])

    def test_a_closure_recorded_promptly_is_not_stale(self):
        self.close(self.school("s1"))

        summary = ca.closure_quality()

        self.assertEqual(summary["stale_recordings"], 0)
        self.assertEqual(ca.needs_attention(), [])


class ReopeningsAreEvidenceTest(ClosureQualityFixture):
    def test_a_reopened_school_is_counted_and_listed(self):
        school = self.school("s1")
        self.close(school)
        svc.reopen_school(
            school.id,
            {
                "reason": "Confirmed operating again under new management.",
                "enrollment": 260,
            },
            self.cceo_user,
        )

        summary = ca.closure_quality()
        rows = ca.reopenings()

        self.assertEqual(summary["reopened"], 1)
        self.assertEqual(summary["reopening_rate"], 100.0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["school"].school_id, "s1")

    def test_a_reopened_closure_stops_removing_enrolment(self):
        """The school is operating again, so the programme did not lose it."""
        school = self.school("s1", enrollment=200)
        self.close(school)
        self.assertEqual(ca.closure_quality()["enrollment_removed"], 200)

        svc.reopen_school(
            school.id,
            {
                "reason": "Confirmed operating again under new management.",
                "enrollment": 260,
            },
            self.cceo_user,
        )

        self.assertEqual(ca.closure_quality()["enrollment_removed"], 0)

    def test_a_reopening_is_not_outstanding_work(self):
        """It is evidence about decisions, not a queue item."""
        school = self.school("s1")
        self.close(school)
        svc.reopen_school(
            school.id,
            {
                "reason": "Confirmed operating again under new management.",
                "enrollment": 260,
            },
            self.cceo_user,
        )

        self.assertEqual(ca.needs_attention(), [])


class ThePageIsReachableTest(ClosureQualityFixture):
    def _client(self, user):
        from django.test import Client

        c = Client()
        c.force_login(user)
        return c

    def test_ia_can_open_it(self):
        school = self.school("s1")
        School.objects.filter(id=school.id).update(duplicate_status="potential")
        self.close(school)

        response = self._client(self.ia_user).get("/analytics/closure-quality")

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Closure Quality", body)
        self.assertIn("duplicate flag unresolved", body)

    def test_a_cceo_cannot(self):
        """This is a data-quality worklist, not a portfolio view."""
        response = self._client(self.cceo_user).get("/analytics/closure-quality")

        self.assertIn(response.status_code, (302, 403))

    def test_an_empty_country_says_so_rather_than_showing_zeros(self):
        response = self._client(self.ia_user).get("/analytics/closure-quality")

        self.assertEqual(response.status_code, 200)
        self.assertIn("No schools have been closed", response.content.decode())

    def test_the_period_filter_swaps_only_the_body(self):
        self.close(self.school("s1"))

        response = self._client(self.ia_user).get(
            "/analytics/closure-quality?period=fy", headers={"HX-Request": "true"}
        )

        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        # The workspace partial, not the whole page: the header carries the
        # control that fired the request and must survive the swap.
        self.assertNotIn("<h1", body)
        self.assertIn("Closures recorded", body)


class TheSummaryMatchesTheListsTest(ClosureQualityFixture):
    """A tile that disagrees with the rows beneath it is how a dashboard
    quietly stops being trusted."""

    def test_the_attention_count_equals_the_rows_listed(self):
        flagged = self.school("s3")
        School.objects.filter(id=flagged.id).update(duplicate_status="potential")

        self.close(self.school("s1", enrollment=None))
        self.close(self.school("s2"), reason=ClosureReason.UNCONFIRMED)
        self.close(flagged)
        self.close(self.school("s4"))  # clean — must not appear

        summary = ca.closure_quality()
        rows = ca.needs_attention()

        self.assertEqual(len(rows), 3)
        self.assertEqual(summary["missing_enrollment"], 1)
        self.assertEqual(summary["weak_ground"], 1)
        self.assertEqual(summary["stranded_duplicates"], 1)

    def test_the_period_filter_is_half_open(self):
        """An inclusive end would count 1 October in both years."""
        self.close(self.school("s1"), effective=date(2025, 9, 30))
        self.close(self.school("s2"), effective=date(2025, 10, 1))

        # FY2025 = 1 Oct 2024 → 1 Oct 2025 (exclusive).
        summary = ca.closure_quality(date(2024, 10, 1), date(2025, 10, 1))

        self.assertEqual(summary["recorded"], 1)

    def test_by_reason_totals_add_up_to_what_was_recorded(self):
        self.close(self.school("s1"))
        self.close(self.school("s2"), reason=ClosureReason.LOW_ENROLMENT)
        self.close(self.school("s3"), reason=ClosureReason.FACILITY)

        summary = ca.closure_quality()
        total = sum(r["total"] for r in ca.by_reason())

        self.assertEqual(total, summary["recorded"])
        self.assertEqual(total, SchoolClosure.objects.count())
