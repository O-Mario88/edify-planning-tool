"""Phase 3: the offline day package's contract under test.

Pins: own-work-only scoping, route grouping by geography, the prefilled
capture contract (planned figures + evidence checklist ride along), geo
override precedence, and the guarded JSON endpoint.
"""

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.geography.models import District, Region, SubCounty
from apps.my_plan.day_package import build_day_package
from apps.routes.models import SchoolGeoPoint
from apps.schools.models import School


class DayPackageFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email="daypack@example.test",
            name="Day Pack CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password="test-password",
            is_active=True,
        )
        cls.staff = StaffProfile.objects.create(user=cls.user, title="CCEO")
        cls.other = User.objects.create_user(
            email="other-daypack@example.test",
            name="Other CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password="test-password",
            is_active=True,
        )
        cls.other_staff = StaffProfile.objects.create(user=cls.other, title="CCEO")
        cls.region = Region.objects.create(name="DP Region")
        cls.district = District.objects.create(name="DP District", region=cls.region)
        cls.sub_a = SubCounty.objects.create(name="Alpha SC", district=cls.district)
        cls.sub_b = SubCounty.objects.create(name="Beta SC", district=cls.district)
        cls.today = timezone.localdate()

    def _school(self, name, sub_county, **overrides):
        return School.objects.create(
            school_id=f"DP-{name}",
            name=name,
            region=self.region,
            district=self.district,
            sub_county=sub_county,
            school_type="client",
            **overrides,
        )

    def _activity(self, school, staff=None, day=None, **overrides):
        defaults = dict(
            activity_type="school_visit",
            status="scheduled",
            planned_date=day or self.today,
            fy="2027",
            school=school,
            responsible_staff_id=(staff or self.staff).id,
            expected_participants=None,
        )
        defaults.update(overrides)
        return Activity.objects.create(**defaults)


class BuildTests(DayPackageFixture):
    def test_only_the_callers_own_day_is_packaged(self):
        mine = self._activity(self._school("Mine", self.sub_a))
        self._activity(self._school("Theirs", self.sub_a), staff=self.other_staff)
        self._activity(
            self._school("Tomorrow", self.sub_a),
            day=self.today + timedelta(days=1),
        )
        package = build_day_package(self.user)
        ids = [
            activity["activityId"]
            for group in package["routeGroups"]
            for activity in group["activities"]
        ]
        self.assertEqual(ids, [mine.id])

    def test_route_groups_cluster_by_geography(self):
        self._activity(self._school("A1", self.sub_a))
        self._activity(self._school("B1", self.sub_b))
        self._activity(self._school("A2", self.sub_a))
        package = build_day_package(self.user)
        areas = {
            group["area"]: len(group["activities"]) for group in package["routeGroups"]
        }
        self.assertEqual(areas, {"Alpha SC": 2, "Beta SC": 1})
        self.assertEqual(package["activityCount"], 3)

    def test_the_capture_contract_prefills_plan_and_evidence(self):
        school = self._school("Prefilled", self.sub_a)
        self._activity(
            school,
            activity_type="training",
            expected_participants=40,
            schools_invited=8,
        )
        package = build_day_package(self.user)
        row = package["routeGroups"][0]["activities"][0]
        self.assertEqual(row["plannedParticipants"], 40)
        self.assertEqual(row["schoolsInvited"], 8)
        self.assertIsInstance(row["evidenceRequired"], list)

    def test_a_geo_point_override_beats_directory_coordinates(self):
        school = self._school("Overridden", self.sub_a, latitude=0.1, longitude=32.1)
        SchoolGeoPoint.objects.create(
            school_id=school.id, latitude=0.9, longitude=32.9, source="manual"
        )
        self._activity(school)
        package = build_day_package(self.user)
        location = package["routeGroups"][0]["activities"][0]["school"]["location"]
        self.assertEqual(location["latitude"], 0.9)
        self.assertEqual(location["source"], "geo_point")

    def test_legacy_rows_with_only_a_scheduled_date_still_appear(self):
        # My Plan's fallback (planned_date NULL, scheduled_date today) —
        # the day package must never show fewer activities than My Plan.
        from datetime import datetime, time as dt_time

        from django.utils import timezone as tz

        school = self._school("Legacy Dated", self.sub_a)
        self._activity(
            school,
            planned_date=None,
            scheduled_date=tz.make_aware(datetime.combine(self.today, dt_time(hour=9))),
        )
        package = build_day_package(self.user)
        self.assertEqual(package["activityCount"], 1)

    def test_partner_delivered_rows_never_enter_a_staff_day_package(self):
        school = self._school("Partnered", self.sub_a)
        self._activity(school, delivery_type="partner")
        package = build_day_package(self.user)
        self.assertEqual(package["activityCount"], 0)


class EndpointTests(DayPackageFixture):
    def test_the_endpoint_serves_the_callers_package(self):
        self._activity(self._school("Endpoint", self.sub_a))
        self.client.force_login(self.user)
        response = self.client.get("/my-plan/day-package")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["date"], self.today.isoformat())
        self.assertEqual(payload["activityCount"], 1)

    def test_an_invalid_date_is_a_clear_400(self):
        self.client.force_login(self.user)
        response = self.client.get("/my-plan/day-package?date=nonsense")
        self.assertEqual(response.status_code, 400)

    def test_a_specific_date_can_be_prefetched(self):
        target = date(2026, 10, 20)
        self._activity(self._school("Future", self.sub_a), day=target)
        self.client.force_login(self.user)
        response = self.client.get("/my-plan/day-package?date=2026-10-20")
        self.assertEqual(response.json()["activityCount"], 1)
