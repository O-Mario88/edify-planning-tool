"""The CCEO dashboard's four task tiles split the person's work.

Found by the 2026-10-07 calculation check (owner: "do a final logic,
computation and calculation check ... accurate and not missleading").

"Overdue Tasks" was "date passed and not `completed` or `closed`", so work
Impact Assessment had already verified counted as overdue the day after its
date. "Planned Tasks" was every scheduled activity, the overdue ones included,
so one activity sat in two tiles, and the agenda called verified work
"Overdue". The four now come from one split (apps.core.activity_types): done;
under way; not started with its date ahead; not started with its date passed.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.core.activity_types import (
    COMPLETED_WORK_STATUSES,
    NOT_IN_PLAN_ACTIVITY_STATUSES,
    NOT_STARTED_ACTIVITY_STATUSES,
    UNDER_WAY_ACTIVITY_STATUSES,
)
from apps.core.enums import ActivityStatus
from apps.core.fy import get_operational_fy
from apps.frontend.views.dashboard_views import _agenda_status_pill
from apps.geography.models import District, Region
from apps.schools.models import School


class EveryStatusHasOnePlaceTest(TestCase):
    def test_the_groups_do_not_overlap(self):
        groups = (
            set(COMPLETED_WORK_STATUSES),
            set(UNDER_WAY_ACTIVITY_STATUSES),
            set(NOT_STARTED_ACTIVITY_STATUSES),
            set(NOT_IN_PLAN_ACTIVITY_STATUSES),
        )
        for index, group in enumerate(groups):
            for other in groups[index + 1 :]:
                self.assertFalse(group & other)

    def test_every_status_an_activity_can_hold_is_in_one_of_them(self):
        placed = (
            set(COMPLETED_WORK_STATUSES)
            | set(UNDER_WAY_ACTIVITY_STATUSES)
            | set(NOT_STARTED_ACTIVITY_STATUSES)
            | set(NOT_IN_PLAN_ACTIVITY_STATUSES)
            # Asked of a school's owner and not yet anybody's plan.
            | {"awaiting_owner_approval"}
        )
        self.assertEqual(set(ActivityStatus.values) - placed, set())


class TheFourTilesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        region = Region.objects.create(name="Tile Region")
        district = District.objects.create(name="Tile District", region=region)
        cls.school = School.objects.create(
            school_id="TILE-1", name="Tile School", region=region, district=district
        )
        cls.user = User.objects.create(
            email="tiles@edify.org",
            name="Tile Officer",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
            status="active",
        )
        cls.staff = StaffProfile.objects.create(user=cls.user, title="CCEO")

    def activity(self, status, *, days):
        # The platform's day, which is the day the dashboard counts from.
        when = timezone.localdate() + timedelta(days=days)
        return Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            fy=self.fy,
            quarter="Q1",
            planned_date=when,
            planned_month=when.month,
            status=status,
            delivery_type="staff",
            responsible_staff_id=self.staff.id,
        )

    def tiles(self):
        self.client.force_login(self.user)
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        return {
            item["label"]: int(item["display_value"])
            for item in response.context["kpi_strip_items"]
        }

    def test_each_activity_is_in_exactly_one_tile(self):
        self.activity("ia_verified", days=-20)  # done, though its date passed
        self.activity("closed", days=-30)
        self.activity("awaiting_ia_verification", days=-3)  # with a reviewer
        self.activity("in_progress", days=0)
        self.activity("scheduled", days=-2)  # not started, late
        self.activity("rescheduled", days=-1)
        self.activity("scheduled", days=5)  # not started, ahead
        self.activity("planned", days=9)
        self.activity("rescheduled", days=12)
        self.activity("cancelled", days=-4)  # called off: in no tile

        tiles = self.tiles()

        self.assertEqual(
            (
                tiles["Completed Tasks"],
                tiles["In Progress"],
                tiles["Planned Tasks"],
                tiles["Overdue Tasks"],
            ),
            (2, 2, 3, 2),
        )
        self.assertEqual(sum(tiles.values()), 9)

    def test_the_day_is_kampalas_not_utcs(self):
        """Half past midnight in Kampala is 21:30 UTC the day before. Work
        planned for today is planned, and yesterday's is overdue; counted
        from the UTC date, today's was still tomorrow's and yesterday's was
        not overdue yet (owner, 2026-10-09: "yes fix it")."""
        night = datetime(2026, 10, 14, 21, 30, tzinfo=dt_timezone.utc)
        with mock.patch("django.utils.timezone.now", return_value=night):
            self.assertEqual(timezone.localdate(), date(2026, 10, 15))
            self.activity("scheduled", days=0)
            self.activity("scheduled", days=-1)

            tiles = self.tiles()

        self.assertEqual((tiles["Planned Tasks"], tiles["Overdue Tasks"]), (1, 1))

    def test_verified_work_is_never_overdue(self):
        self.activity("ia_verified", days=-20)
        self.activity("accountant_confirmed", days=-20)

        tiles = self.tiles()

        self.assertEqual(tiles["Overdue Tasks"], 0)
        self.assertEqual(tiles["Completed Tasks"], 2)

    def test_an_overdue_activity_is_not_also_planned(self):
        self.activity("scheduled", days=-2)

        tiles = self.tiles()

        self.assertEqual((tiles["Planned Tasks"], tiles["Overdue Tasks"]), (0, 1))

    def test_the_agenda_pill_says_the_same(self):
        today = date.today()

        def pill(status, days):
            activity = Activity(
                status=status, planned_date=today + timedelta(days=days)
            )
            return _agenda_status_pill(activity, today)[0]

        self.assertEqual(pill("ia_verified", -5), "Completed")
        self.assertEqual(pill("awaiting_ia_verification", -5), "In Progress")
        self.assertEqual(pill("scheduled", -5), "Overdue")
        self.assertEqual(pill("scheduled", 5), "Planned")
        self.assertEqual(pill("rescheduled", -1), "Overdue")
