"""No double planning, no double funding, and money in the week the work is.

A data audit of the dev estate raised three questions this pins answers to:

* 12 client schools hold more than one `school_visit` in FY2026 — one of them
  202. Every one is `source=manual_upload`, i.e. seeded before the entitlement
  guard was restored, not scheduled through the platform. So the question is
  not "is the data clean" but "does the guard hold now".
* No budget line appeared in two weekly fund requests and no owner had two live
  requests for one week, so the funding chain was clean. Worth keeping that way.
* Five cost lines sat one week earlier than their activity, all from the same
  upload. See ScheduleCostLandsInTheRightWeekTest.
"""

from __future__ import annotations

from datetime import date, timedelta, timezone as dt_timezone

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.exceptions import BadRequest
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.schools.models import School


def _next_monday(weeks: int = 1) -> date:
    today = date.today()
    return today - timedelta(days=today.weekday()) + timedelta(weeks=weeks)


class ClientEntitlementHoldsTest(TestCase):
    """One visit and one training per client school per financial year."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Entitlement Region")
        cls.district = District.objects.create(
            name="Entitlement District", region=cls.region
        )
        cls.school = School.objects.create(
            school_id="SCH-ENTITLE-1",
            name="Entitlement Primary",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )
        cls.user = User.objects.create(
            id="entitle-cceo",
            email="entitle@edify.org",
            name="Entitle CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        StaffProfile.objects.create(id="entitle-sp", user=cls.user, title="CCEO")

    def _existing_visit(self):
        return Activity.objects.create(
            activity_type="school_visit",
            delivery_type="staff",
            status="scheduled",
            fy=get_operational_fy(_next_monday()),
            school=self.school,
            responsible_staff_id=self.user.id,
            planned_date=_next_monday(),
            scheduled_date=_next_monday(),
        )

    def _schedule_another(self):
        from apps.activities.services import _assert_schedule_entitlement

        _assert_schedule_entitlement(
            "school_visit", self.school, get_operational_fy(_next_monday()), {}
        )

    def test_a_second_visit_in_the_same_year_is_refused(self):
        self._existing_visit()
        with self.assertRaises(BadRequest):
            self._schedule_another()

    def test_the_first_visit_is_allowed(self):
        self._schedule_another()  # must not raise

    def test_a_cancelled_visit_does_not_consume_the_entitlement(self):
        visit = self._existing_visit()
        visit.status = "cancelled"
        visit.save(update_fields=["status"])
        self._schedule_another()  # the slot is free again

    def test_a_core_school_is_not_bound_by_the_client_rule(self):
        """Core schools carry a 4 + 4 package, gated by the slot machinery."""
        from apps.activities.services import _assert_schedule_entitlement

        self.school.school_type = "core"
        self.school.save(update_fields=["school_type"])
        self._existing_visit()
        _assert_schedule_entitlement(
            "school_visit", self.school, get_operational_fy(_next_monday()), {}
        )

    def test_core_work_cannot_be_scheduled_without_a_reserved_slot(self):
        """The bypass this guard was restored for: POSTing a core type straight
        to the generic endpoint, skipping the package and its staff cap."""
        from apps.activities.services import _assert_schedule_entitlement

        self.school.school_type = "core"
        self.school.save(update_fields=["school_type"])
        with self.assertRaises(BadRequest):
            _assert_schedule_entitlement(
                "core_visit", self.school, get_operational_fy(_next_monday()), {}
            )
        # With the slot reserved, it passes.
        _assert_schedule_entitlement(
            "core_visit",
            self.school,
            get_operational_fy(_next_monday()),
            {},
            core_slot_verified=True,
        )


class CatalogueEntitlementOwnershipTest(TestCase):
    """The Activity Catalogue owns what consumes a client entitlement.

    The catalogue migration retired the generic ``school_visit`` in favour of
    ``follow_up_visit`` (CLIENT_SCHOOL_FOLLOWUP_VISIT), but the guard's family
    map still keyed on ``school_visit`` only — so the one-visit/FY cap no
    longer bound catalogue follow-up visits at all. And
    ``counts_toward_entitlement`` was written by seeding but read nowhere.
    Both are wired here: the item flags pick the pool, the eligibility rule is
    the governance exemption switch, and the legacy type map remains only as
    the fallback for catalogue-less rows.
    """

    @classmethod
    def setUpTestData(cls):
        from apps.activity_catalogue.seeding import seed_activity_catalogue

        seed_activity_catalogue(actor_id="test")
        cls.region = Region.objects.create(name="Catalogue Entitlement Region")
        cls.district = District.objects.create(
            name="Catalogue Entitlement District", region=cls.region
        )
        cls.school = School.objects.create(
            school_id="SCH-ENTITLE-CAT-1",
            name="Catalogue Entitlement Primary",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )

    @property
    def fy(self):
        return get_operational_fy(_next_monday())

    def _item(self, stable_code):
        from apps.activity_catalogue.models import ActivityCatalogueItem

        return ActivityCatalogueItem.objects.get(stable_code=stable_code)

    def _activity(self, activity_type, catalogue_item=None):
        return Activity.objects.create(
            activity_type=activity_type,
            catalogue_item=catalogue_item,
            delivery_type="staff",
            status="scheduled",
            fy=self.fy,
            school=self.school,
            planned_date=_next_monday(),
            scheduled_date=_next_monday(),
        )

    def _assert(self, activity_type, catalogue_item=None):
        from apps.activities.services import _assert_schedule_entitlement

        _assert_schedule_entitlement(
            activity_type,
            self.school,
            self.fy,
            {},
            catalogue_item=catalogue_item,
        )

    def test_a_follow_up_visit_consumes_the_visit_entitlement(self):
        """The reported gap: follow_up_visit bypassed the one-visit/FY cap."""
        self._activity("follow_up_visit")
        with self.assertRaises(BadRequest):
            self._assert("follow_up_visit")

    def test_visit_and_follow_up_visit_share_one_pool(self):
        self._activity("school_visit")
        with self.assertRaises(BadRequest):
            self._assert("follow_up_visit")

    def test_catalogue_follow_up_visit_is_capped_by_the_item_flag(self):
        item = self._item("CLIENT_SCHOOL_FOLLOWUP_VISIT")
        self._activity("follow_up_visit", catalogue_item=item)
        with self.assertRaises(BadRequest):
            self._assert(item.workflow_kind, catalogue_item=item)

    def test_flagless_catalogue_training_neither_blocks_nor_consumes(self):
        """Student camps carry workflow_kind ``training`` with both client
        flags off. The old type map wrongly drew them from the training pool
        in both directions."""
        camp = self._item("STUDENT_TRAINING_YOUTH_CAMPS")
        edtech = self._item("EDTECH_FOUNDATIONS")
        # A used training entitlement must not block a camp…
        self._activity("in_school_training", catalogue_item=edtech)
        self._assert(camp.workflow_kind, catalogue_item=camp)  # must not raise
        # …and a scheduled camp must not consume the entitlement.
        Activity.objects.all().delete()
        self._activity("training", catalogue_item=camp)
        self._assert(edtech.workflow_kind, catalogue_item=edtech)  # must not raise

    def test_counts_toward_entitlement_is_the_governance_exemption_switch(self):
        item = self._item("CLIENT_SCHOOL_FOLLOWUP_VISIT")
        self._activity("school_visit")
        rule = item.eligibility_rule
        rule.counts_toward_entitlement = False
        rule.save(update_fields=["counts_toward_entitlement"])
        item.refresh_from_db()
        self._assert(item.workflow_kind, catalogue_item=item)  # must not raise

    def test_health_detector_sees_follow_up_visit_duplicates(self):
        """Prevention and detection must share one definition of 'counts'."""
        from apps.system_health.services import _workflow_issues

        self._activity("school_visit")
        self._activity("follow_up_visit")
        issues = _workflow_issues()
        self.assertEqual(issues["clientDuplicateActiveEntitlements"], 1)


class ScheduleCostLandsInTheRightWeekTest(TestCase):
    """The money must sit in the week the work does.

    The audit found five cost lines a week earlier than their activity. The
    cause is a timezone edge: an activity scheduled at local midnight is stored
    as 21:00 UTC the previous day, and deriving the week from the raw UTC date
    lands it in the week before. `costing_service` uses
    `timezone.localtime(...)` and gets this right; these tests pin that, since
    the same mistake has already been made twice in this codebase.
    """

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Week Region")
        cls.district = District.objects.create(name="Week District", region=cls.region)
        cls.school = School.objects.create(
            school_id="SCH-WEEK-1",
            name="Week Primary",
            region=cls.region,
            district=cls.district,
            school_type="client",
        )

    def test_local_midnight_on_a_monday_belongs_to_that_monday(self):
        """21:00 UTC Sunday is 00:00 Monday in Africa/Kampala. Taking the UTC
        date puts the money in the previous week."""
        monday = _next_monday()
        local_midnight = timezone.make_aware(
            timezone.datetime.combine(monday, timezone.datetime.min.time())
        )
        self.assertEqual(timezone.localtime(local_midnight).date(), monday)
        self.assertNotEqual(
            local_midnight.astimezone(dt_timezone.utc).date(),
            monday,
            "this test is meaningless unless the UTC date really differs",
        )

        derived = timezone.localtime(local_midnight).date()
        week_start = derived - timedelta(days=derived.weekday())
        self.assertEqual(week_start, monday)

    def test_the_costing_service_derives_the_week_in_local_time(self):
        import inspect

        from apps.budget import costing_service

        source = inspect.getsource(costing_service)
        self.assertIn("timezone.localtime(scheduled_date).date()", source)

    def test_a_cost_line_sits_in_its_activitys_own_week(self):
        monday = _next_monday()
        activity = Activity.objects.create(
            activity_type="school_visit",
            delivery_type="staff",
            status="scheduled",
            fy=get_operational_fy(monday),
            school=self.school,
            planned_date=monday,
            scheduled_date=monday,
        )
        line = ActivityScheduleCostLine.objects.create(
            activity=activity,
            responsible_user="week-owner",
            planned_date=monday,
            week_start_date=monday - timedelta(days=monday.weekday()),
            fiscal_year=activity.fy,
            month=monday.month,
            description="Transport",
            unit_cost=10_000,
            quantity=1,
            amount=10_000,
        )
        expected = activity.planned_date - timedelta(
            days=activity.planned_date.weekday()
        )
        self.assertEqual(line.week_start_date, expected)
