"""Closing a school without losing what it did.

A closure is a state transition. The school stops receiving new work and stops
counting toward what the programme currently reaches; everything it did before
stays exactly where it was, because the enrolment it had and the visits it
received are facts about periods already reported.

The rules worth a test are the ones that would misreport a country: the wrong
enrolment number leaving the total, a school counted out twice, or history
quietly rewritten to tidy the present.
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
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools import lifecycle_service as svc
from apps.schools.lifecycle_models import (
    ClosureReason,
    ClosureType,
    SchoolClosure,
    SchoolOperationalStatus,
)
from apps.schools.models import School, SchoolEnrollmentHistory

EXPLANATION = "The owner confirmed the school stopped operating at the end of term."


class ClosureFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        cls.region = Region.objects.create(id="r1", name="Central")
        cls.district = District.objects.create(
            id="d1", name="Kampala", region=cls.region
        )
        cls.cceo_user, cls.cceo = cls._staff("james@c.test", "James", EdifyRole.CCEO)
        cls.pl_user, cls.pl = cls._staff(
            "mary@c.test", "Mary", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        StaffSupervisorAssignment.objects.create(supervisee=cls.cceo, supervisor=cls.pl)

        cls.school = School.objects.create(
            school_id="s1",
            name="Alpha Primary",
            district=cls.district,
            region=cls.region,
            enrollment=420,
            last_enrollment_date=date.today() - timedelta(days=30),
            account_owner_id=cls.cceo.id,
            account_owner_name_raw="James",
        )
        StaffSchoolAssignment.objects.create(staff=cls.cceo, school_id=cls.school.id)

        cls.other = School.objects.create(
            school_id="s2",
            name="Beta Primary",
            district=cls.district,
            region=cls.region,
            enrollment=310,
            account_owner_id=cls.cceo.id,
        )
        # Assigned too, so "the closed one leaves and the open one stays" is a
        # real comparison rather than an empty queryset either way.
        StaffSchoolAssignment.objects.create(staff=cls.cceo, school_id=cls.other.id)

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

    def payload(self, **over):
        base = {
            "closure_type": ClosureType.PERMANENT,
            "reason_category": ClosureReason.FINANCIAL,
            "reason": EXPLANATION,
            "effective_date": date.today(),
        }
        base.update(over)
        return base

    def future_activity(self, *, cost=90_000, school=None, days=7):
        when = date.today() + timedelta(days=days)
        activity = Activity.objects.create(
            activity_type="school_visit",
            school=school or self.school,
            fy=self.fy,
            quarter="Q1",
            planned_date=when,
            planned_month=when.month,
            status="scheduled",
            responsible_staff_id=self.cceo.id,
        )
        if cost:
            ActivityScheduleCostLine.objects.create(
                activity=activity,
                cost_setting_key="school_visit_transport",
                label="Transport",
                unit_cost=cost,
                quantity=1,
                amount=cost,
                fiscal_year=self.fy,
                month=when.month,
            )
        return activity


class TheSchoolIsNotDeletedTest(ClosureFixture):
    def test_the_record_survives_and_says_it_closed(self):
        svc.close_school(self.school.id, self.payload(), self.cceo_user)

        self.school.refresh_from_db()
        self.assertTrue(School.objects.filter(id=self.school.id).exists())
        self.assertIsNone(self.school.deleted_at)
        self.assertEqual(
            self.school.operational_status,
            SchoolOperationalStatus.PERMANENTLY_CLOSED,
        )

    def test_closed_is_not_the_same_as_deleted(self):
        """deleted means the row should never have existed; closed means it ended."""
        svc.close_school(self.school.id, self.payload(), self.cceo_user)

        self.assertIn(self.school, list(svc.closed_schools()))
        self.assertNotIn(self.school, list(svc.active_schools()))

    def test_historical_enrolment_is_untouched(self):
        SchoolEnrollmentHistory.objects.create(
            school=self.school, fy=self.fy, enrollment=420, recorded_at=date.today()
        )

        svc.close_school(self.school.id, self.payload(), self.cceo_user)

        self.assertEqual(
            SchoolEnrollmentHistory.objects.filter(school=self.school).count(), 1
        )


class TheCountsMoveExactlyOnceTest(ClosureFixture):
    def test_the_active_school_count_drops_by_one(self):
        before = svc.active_schools().count()

        svc.close_school(self.school.id, self.payload(), self.cceo_user)

        self.assertEqual(svc.active_schools().count(), before - 1)

    def test_closing_twice_does_not_double_count(self):
        before = svc.active_schools().count()

        first = svc.close_school(self.school.id, self.payload(), self.cceo_user)
        second = svc.close_school(self.school.id, self.payload(), self.cceo_user)

        self.assertEqual(first.id, second.id)
        self.assertEqual(SchoolClosure.objects.count(), 1)
        self.assertEqual(svc.active_schools().count(), before - 1)

    def test_active_enrolment_drops_by_the_actual_count(self):
        before = svc.active_enrollment()

        svc.close_school(self.school.id, self.payload(), self.cceo_user)

        after = svc.active_enrollment()
        self.assertEqual(before["total"] - after["total"], 420)

    def test_the_snapshot_is_the_school_enrolment_count_not_an_ssa_score(self):
        """These have been conflated before. The score is a 1-10 band, so
        subtracting it would take 7 children off the programme, not 420."""
        closure = svc.close_school(self.school.id, self.payload(), self.cceo_user)

        self.assertEqual(closure.enrollment_at_closure, 420)
        self.assertEqual(closure.enrollment_source, "school.enrollment")

    def test_missing_enrolment_is_reported_rather_than_counted_as_zero(self):
        """A sum that treats missing as zero reports a smaller programme with
        the same confidence as a real one."""
        School.objects.create(
            school_id="s3",
            name="Gamma",
            district=self.district,
            region=self.region,
            enrollment=None,
        )

        totals = svc.active_enrollment()

        self.assertEqual(totals["schools_missing_enrollment"], 1)
        self.assertEqual(totals["total"], 730)


class TheClosureSnapshotsWhatWasLostTest(ClosureFixture):
    def test_owner_and_cluster_are_copied_not_looked_up_later(self):
        closure = svc.close_school(self.school.id, self.payload(), self.cceo_user)

        self.assertEqual(closure.owner_at_closure, self.cceo.id)
        self.assertEqual(closure.owner_name_at_closure, "James")

    def test_the_effective_date_is_recorded(self):
        when = date.today() - timedelta(days=14)

        closure = svc.close_school(
            self.school.id, self.payload(effective_date=when), self.cceo_user
        )

        self.assertEqual(closure.effective_date, when)


class FutureWorkStopsTest(ClosureFixture):
    def test_future_unlocked_activities_are_cancelled_not_deleted(self):
        activity = self.future_activity()

        closure = svc.close_school(self.school.id, self.payload(), self.cceo_user)

        activity.refresh_from_db()
        self.assertEqual(activity.status, "cancelled")
        self.assertTrue(Activity.objects.filter(id=activity.id).exists())
        self.assertEqual(closure.activities_cancelled, 1)

    def test_the_released_budget_is_recorded(self):
        self.future_activity(cost=90_000)

        closure = svc.close_school(self.school.id, self.payload(), self.cceo_user)

        self.assertEqual(closure.budget_released, 90_000)

    def test_work_that_already_happened_is_left_alone(self):
        """A closure recorded late must not cancel a visit that took place."""
        past = self.future_activity(days=-14)
        past.status = "completed"
        past.save(update_fields=["status"])

        svc.close_school(self.school.id, self.payload(), self.cceo_user)

        past.refresh_from_db()
        self.assertEqual(past.status, "completed")

    def test_another_schools_work_is_untouched(self):
        theirs = self.future_activity(school=self.other)

        svc.close_school(self.school.id, self.payload(), self.cceo_user)

        theirs.refresh_from_db()
        self.assertEqual(theirs.status, "scheduled")


class AuthorityTest(ClosureFixture):
    def test_the_owning_cceo_may_close_their_own_school(self):
        closure = svc.close_school(self.school.id, self.payload(), self.cceo_user)
        self.assertEqual(closure.closed_by_role, EdifyRole.CCEO.value)

    def test_a_program_lead_may_not_close_a_supervised_cceos_school(self):
        """Supervision is the right to ask. Closing somebody's school cancels
        their work and changes their target denominator — that is not asking."""
        with self.assertRaises(Forbidden) as caught:
            svc.close_school(self.school.id, self.payload(), self.pl_user)

        self.assertIn("closure review", str(caught.exception))

    def test_a_role_without_the_permission_is_refused(self):
        ia, _ = self._staff("ia@c.test", "Verifier", EdifyRole.IMPACT_ASSESSMENT)

        with self.assertRaises(Forbidden):
            svc.close_school(self.school.id, self.payload(), ia)


class ValidationTest(ClosureFixture):
    def test_a_reason_category_is_required(self):
        with self.assertRaises(BadRequest):
            svc.close_school(
                self.school.id, self.payload(reason_category=""), self.cceo_user
            )

    def test_an_explanation_is_required(self):
        with self.assertRaises(BadRequest):
            svc.close_school(
                self.school.id, self.payload(reason=" " * 40), self.cceo_user
            )

    def test_a_closure_type_is_required(self):
        with self.assertRaises(BadRequest):
            svc.close_school(
                self.school.id, self.payload(closure_type=""), self.cceo_user
            )

    def test_a_duplicate_record_is_not_a_closure(self):
        """Recording it as one would report a school loss that never happened."""
        with self.assertRaises(BadRequest) as caught:
            svc.close_school(
                self.school.id,
                self.payload(reason_category=ClosureReason.DUPLICATE_RECORD),
                self.cceo_user,
            )

        self.assertIn("duplicate workflow", str(caught.exception))


class PreviewMatchesWhatHappensTest(ClosureFixture):
    def test_the_preview_names_the_numbers_that_will_move(self):
        self.future_activity(cost=90_000)

        preview = svc.preview(self.school.id)

        self.assertEqual(preview["enrollment"], 420)
        self.assertEqual(preview["active_school_count_change"], -1)
        self.assertEqual(preview["active_enrollment_change"], -420)
        self.assertEqual(preview["activities_to_cancel"], 1)
        self.assertEqual(preview["budget_released"], 90_000)

    def test_the_preview_is_borne_out_by_the_closure(self):
        self.future_activity(cost=90_000)
        preview = svc.preview(self.school.id)
        before = svc.active_enrollment()["total"]

        closure = svc.close_school(self.school.id, self.payload(), self.cceo_user)

        after = svc.active_enrollment()["total"]
        self.assertEqual(before - after, -preview["active_enrollment_change"])
        self.assertEqual(closure.activities_cancelled, preview["activities_to_cancel"])
        self.assertEqual(closure.budget_released, preview["budget_released"])


class ReopeningTest(ClosureFixture):
    def _closed(self):
        return svc.close_school(self.school.id, self.payload(), self.cceo_user)

    def test_reopening_restores_the_school_to_active_counts(self):
        self._closed()
        before = svc.active_schools().count()

        svc.reopen_school(
            self.school.id,
            {
                "reason": "The school has reopened under new management.",
                "enrollment": 380,
            },
            self.cceo_user,
        )

        self.assertEqual(svc.active_schools().count(), before + 1)

    def test_reopening_uses_the_confirmed_current_enrolment(self):
        self._closed()

        svc.reopen_school(
            self.school.id,
            {
                "reason": "The school has reopened under new management.",
                "enrollment": 380,
            },
            self.cceo_user,
        )

        self.school.refresh_from_db()
        self.assertEqual(self.school.enrollment, 380)
        self.assertEqual(svc.active_enrollment()["total"], 380 + 310)

    def test_reopening_needs_a_confirmed_enrolment(self):
        """Restoring the old figure would put back a count nobody confirmed."""
        self._closed()

        with self.assertRaises(BadRequest) as caught:
            svc.reopen_school(
                self.school.id,
                {"reason": "It is operating again, we checked."},
                self.cceo_user,
            )

        self.assertIn("current enrolment", str(caught.exception))

    def test_cancelled_work_does_not_come_back(self):
        activity = self.future_activity()
        self._closed()

        svc.reopen_school(
            self.school.id,
            {
                "reason": "The school has reopened under new management.",
                "enrollment": 380,
            },
            self.cceo_user,
        )

        activity.refresh_from_db()
        self.assertEqual(activity.status, "cancelled")

    def test_the_closure_stays_in_the_history(self):
        closure = self._closed()

        svc.reopen_school(
            self.school.id,
            {
                "reason": "The school has reopened under new management.",
                "enrollment": 380,
            },
            self.cceo_user,
        )

        closure.refresh_from_db()
        self.assertIsNotNone(closure.reopened_at)
        self.assertEqual(SchoolClosure.objects.filter(school=self.school).count(), 1)


class ClosedSchoolsLeaveOperationalSurfacesTest(ClosureFixture):
    """The whole point of the closure. A school that is still returned by the
    operational queryset is still offered for planning, still counted in a
    KPI, and still on somebody's list to visit."""

    def _scope(self, user):
        from apps.core.scoping import resolve_user_scope

        return resolve_user_scope(user)

    def test_the_operational_directory_drops_a_closed_school(self):
        from apps.core.scoping import school_queryset

        before = school_queryset(self._scope(self.cceo_user))
        self.assertIn(self.school, list(before))

        svc.close_school(self.school.id, self.payload(), self.cceo_user)

        after = school_queryset(self._scope(self.cceo_user))
        self.assertNotIn(self.school, list(after))
        self.assertIn(self.other, list(after))

    def test_reopening_puts_it_back(self):
        from apps.core.scoping import school_queryset

        svc.close_school(self.school.id, self.payload(), self.cceo_user)
        svc.reopen_school(
            self.school.id,
            {
                "reason": "The school has reopened under new management.",
                "enrollment": 380,
            },
            self.cceo_user,
        )

        self.assertIn(self.school, list(school_queryset(self._scope(self.cceo_user))))

    def test_the_two_definitions_of_active_agree(self):
        """core.scoping keeps its own tuple to avoid depending on the app it
        scopes. A duplicated constant that drifts is worse than the import."""
        from apps.core.scoping import _operationally_active
        from apps.schools.lifecycle_models import OPERATING_STATUSES

        sql = str(_operationally_active(School.objects.all()).query)
        for status in OPERATING_STATUSES:
            with self.subTest(status=str(status)):
                self.assertIn(str(status), sql)


class ClosureHealthTest(ClosureFixture):
    def _check(self, key):
        from apps.system_health import school_closure_health

        return next(
            c for c in school_closure_health.report()["checks"] if c["key"] == key
        )

    def test_a_clean_closure_reports_nothing(self):
        self.future_activity()
        svc.close_school(self.school.id, self.payload(), self.cceo_user)

        from apps.system_health import school_closure_health

        report = school_closure_health.report()
        self.assertTrue(report["clean"], report["checks"])

    def test_future_work_left_behind_is_an_error(self):
        activity = self.future_activity()
        svc.close_school(self.school.id, self.payload(), self.cceo_user)
        # Simulate the drift: an activity created, or resurrected, afterwards.
        activity.status = "scheduled"
        activity.save(update_fields=["status"])

        finding = self._check("closed_school_future_work")

        self.assertEqual(finding["count"], 1)
        self.assertEqual(finding["severity"], "error")

    def test_a_missing_enrolment_snapshot_is_reported(self):
        self.school.enrollment = None
        self.school.save(update_fields=["enrollment"])

        svc.close_school(self.school.id, self.payload(), self.cceo_user)

        self.assertEqual(self._check("closure_missing_enrolment_snapshot")["count"], 1)


class TheClosureIsReachableTest(ClosureFixture):
    """The service existing is not the same as anybody being able to use it."""

    def _client(self, user):
        from django.test import Client

        c = Client()
        c.force_login(user)
        return c

    def test_the_profile_offers_a_close_action(self):
        body = (
            self._client(self.cceo_user)
            .get(f"/schools/{self.school.school_id}")
            .content.decode()
        )

        self.assertIn("Close School", body)
        self.assertIn(f"/schools/{self.school.school_id}/close-drawer", body)

    def test_the_drawer_shows_the_impact_before_anybody_confirms(self):
        self.future_activity(cost=90_000)

        body = (
            self._client(self.cceo_user)
            .get(f"/schools/{self.school.school_id}/close-drawer")
            .content.decode()
        )

        self.assertIn("420", body)  # the enrolment leaving
        self.assertIn("90,000", body)  # the budget released
        self.assertIn("Nothing is deleted", body)

    def test_closing_through_the_endpoint_works(self):
        response = self._client(self.cceo_user).post(
            f"/schools/{self.school.school_id}/close",
            {
                "closure_type": ClosureType.PERMANENT,
                "reason_category": ClosureReason.FINANCIAL,
                "reason": EXPLANATION,
                "effective_date": date.today().isoformat(),
            },
            headers={"HX-Request": "true"},
        )

        self.school.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.school.is_closed)

    def test_a_program_lead_is_told_why_rather_than_being_let_in(self):
        """Explained in the drawer, not after they have filled the form."""
        body = (
            self._client(self.pl_user)
            .get(f"/schools/{self.school.school_id}/close-drawer")
            .content.decode()
        )

        self.assertIn("closure review", body)
        self.assertNotIn('name="reason_category"', body)

    def test_the_endpoint_refuses_a_program_lead_too(self):
        """A hidden form is not a permission."""
        self._client(self.pl_user).post(
            f"/schools/{self.school.school_id}/close",
            {
                "closure_type": ClosureType.PERMANENT,
                "reason_category": ClosureReason.FINANCIAL,
                "reason": EXPLANATION,
                "effective_date": date.today().isoformat(),
            },
            headers={"HX-Request": "true"},
        )

        self.school.refresh_from_db()
        self.assertFalse(self.school.is_closed)

    def test_a_closed_school_no_longer_offers_the_action(self):
        svc.close_school(self.school.id, self.payload(), self.cceo_user)

        body = (
            self._client(self.cceo_user)
            .get(f"/schools/{self.school.school_id}")
            .content.decode()
        )

        self.assertNotIn("/close-drawer", body)
        self.assertIn("Permanently closed", body)

    def test_the_archive_lists_it_and_the_directory_does_not(self):
        svc.close_school(self.school.id, self.payload(), self.cceo_user)
        client = self._client(self.cceo_user)

        archive = client.get("/schools/closed").content.decode()
        directory = client.get("/schools").content.decode()

        self.assertIn("Alpha Primary", archive)
        self.assertNotIn("Alpha Primary", directory)
        self.assertIn("Beta Primary", directory)

    def test_the_archive_route_is_not_read_as_a_school_id(self):
        """`schools/closed` must be registered before `schools/<school_id>`."""
        response = self._client(self.cceo_user).get("/schools/closed")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Closed Schools", response.content.decode())


class ReopeningIsReachableTest(ClosureFixture):
    """A route nothing calls is a route nobody has."""

    def _client(self, user):
        from django.test import Client

        c = Client()
        c.force_login(user)
        return c

    def test_the_closed_profile_offers_a_reopen_control(self):
        svc.close_school(self.school.id, self.payload(), self.cceo_user)

        body = (
            self._client(self.cceo_user)
            .get(f"/schools/{self.school.school_id}")
            .content.decode()
        )

        self.assertIn(f"/schools/{self.school.school_id}/reopen", body)
        self.assertIn('name="enrollment"', body)

    def test_an_open_school_offers_no_reopen_control(self):
        body = (
            self._client(self.cceo_user)
            .get(f"/schools/{self.school.school_id}")
            .content.decode()
        )

        self.assertNotIn("/reopen", body)

    def test_reopening_through_the_endpoint_restores_it(self):
        svc.close_school(self.school.id, self.payload(), self.cceo_user)

        self._client(self.cceo_user).post(
            f"/schools/{self.school.school_id}/reopen",
            {
                "reason": "Confirmed operating again under new management.",
                "enrollment": 380,
            },
            headers={"HX-Request": "true"},
        )

        self.school.refresh_from_db()
        self.assertFalse(self.school.is_closed)
        self.assertEqual(self.school.enrollment, 380)
        self.assertIn(self.school, list(svc.active_schools()))

    def test_reopening_without_a_confirmed_enrolment_is_refused(self):
        svc.close_school(self.school.id, self.payload(), self.cceo_user)

        response = self._client(self.cceo_user).post(
            f"/schools/{self.school.school_id}/reopen",
            {"reason": "Confirmed operating again under new management."},
            headers={"HX-Request": "true"},
        )

        self.school.refresh_from_db()
        self.assertTrue(self.school.is_closed)
        self.assertIn("enrolment", response.content.decode())


class ArchiveTotalsTest(ClosureFixture):
    """The archive's KPIs describe the archive, not the visible page.

    The table is paged. If the totals were summed from the rows on screen they
    would shrink as somebody paged through, and the enrolment lost would be
    understated the moment there were more closures than fit on one page.
    """

    def _client(self, user):
        from django.test import Client

        c = Client()
        c.force_login(user)
        return c

    def _close(self, school, enrollment):
        school.enrollment = enrollment
        school.save(update_fields=["enrollment"])
        svc.close_school(school.id, self.payload(), self.cceo_user)

    def test_totals_cover_every_closure_not_just_the_rendered_page(self):
        from apps.core.pagination import TABLE_PAGE_SIZE
        from apps.schools.models import School

        self._close(self.school, 100)
        self._close(self.other, 200)

        # Enough extra closures to push the first two off page one.
        extra = TABLE_PAGE_SIZE + 2
        for i in range(extra):
            school = School.objects.create(
                school_id=f"ARCH-{i:03d}",
                name=f"Archive Test {i}",
                district=self.district,
                region=self.region,
                enrollment=10,
                account_owner_id=self.cceo.id,
            )
            self._close(school, 10)

        response = self._client(self.cceo_user).get("/schools/closed")

        self.assertEqual(response.context["closed_count"], extra + 2)
        self.assertEqual(
            response.context["enrollment_removed"], 100 + 200 + (extra * 10)
        )

        # And the table itself is bounded: one page of rows, with a pager to
        # reach the rest. Counting the school-id cells counts rendered rows.
        body = response.content.decode()
        rendered = body.count(
            '<span class="block edify-text-caption edify-text-muted">ARCH-'
        )
        self.assertLessEqual(rendered, TABLE_PAGE_SIZE)
        self.assertIn("closed_page", body)

    def test_a_search_that_matches_nothing_says_so(self):
        self._close(self.school, 100)

        body = (
            self._client(self.cceo_user)
            .get("/schools/closed?q=nothing-matches-this")
            .content.decode()
        )

        self.assertIn("No closed school matches that search", body)
        self.assertNotIn("Alpha Primary", body)
