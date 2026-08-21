"""Field events — MOU travel-profile costing (FIELD_TRAVEL).

District meetings, boot camps, workshops and conferences are planned like any
other activity but price from the travel per-diems: home-district (or same-day
return) work draws transport + lunch; an overnight in another district adds
accommodation, dinner and breakfast per night. The profile derives from the
owner's PRIMARY district vs the event's destination — never self-declared.
"""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity
from apps.activities.services import _field_event_district_type
from apps.budget.costing import cost_for_activity
from apps.budget.models import CostCatalogue, CostSetting
from apps.core.fy import get_operational_fy
from apps.fund_requests.models import WeeklyFundRequest
from apps.fund_requests.pl_approval_service import _category
from apps.geography.models import District, Region

RATES = {
    "primary_transport_per_day": 20_000,
    "primary_lunch_per_day": 10_000,
    "secondary_transport_per_day": 60_000,
    "secondary_lunch_per_day": 15_000,
    "secondary_breakfast_per_day": 8_000,
    "secondary_overnight_dinner_per_day": 12_000,
    "secondary_accommodation_per_night": 80_000,
}


def _line_map(cost):
    return {line.key: line for line in cost.lines}


class FieldTravelCostingTest(TestCase):
    """Pure rate-card math — no database."""

    def test_home_district_day_is_transport_and_lunch(self):
        cost = cost_for_activity(
            {"activityType": "field_event", "districtType": "primary", "days": 1},
            RATES,
        )
        lines = _line_map(cost)
        self.assertEqual(
            set(lines), {"primary_transport_per_day", "primary_lunch_per_day"}
        )
        self.assertEqual(cost.amount, 30_000)

    def test_day_trip_to_another_district_is_transport_and_lunch(self):
        cost = cost_for_activity(
            {"activityType": "field_event", "districtType": "secondary", "days": 1},
            RATES,
        )
        lines = _line_map(cost)
        # Every secondary away-day carries the FULL per-diem set — matching
        # the secondary visit-day policy (owner rule, 2026-08-19).
        self.assertEqual(
            set(lines),
            {
                "secondary_transport_per_day",
                "secondary_lunch_per_day",
                "secondary_accommodation_per_night",
                "secondary_overnight_dinner_per_day",
                "secondary_breakfast_per_day",
            },
        )
        self.assertEqual(cost.amount, 60_000 + 15_000 + 80_000 + 12_000 + 8_000)

    def test_overnight_adds_accommodation_dinner_breakfast_per_night(self):
        cost = cost_for_activity(
            {"activityType": "field_event", "districtType": "secondary", "days": 3},
            RATES,
        )
        lines = _line_map(cost)
        # Transport accrues per day away (owner rule, 2026-08-19).
        self.assertEqual(lines["secondary_transport_per_day"].qty, 3)
        self.assertEqual(lines["secondary_lunch_per_day"].qty, 3)
        self.assertEqual(lines["secondary_accommodation_per_night"].qty, 3)
        self.assertEqual(lines["secondary_overnight_dinner_per_day"].qty, 3)
        self.assertEqual(lines["secondary_breakfast_per_day"].qty, 3)
        self.assertEqual(
            cost.amount,
            3 * (60_000 + 15_000 + 80_000 + 12_000 + 8_000),
        )

    def test_missing_rate_blocks_rather_than_undercosts(self):
        cost = cost_for_activity(
            {"activityType": "field_event", "districtType": "secondary", "days": 2},
            {},
        )
        self.assertTrue(cost.cost_missing)
        self.assertIn("secondary_accommodation_per_night", cost.missing_items)


class FieldEventCategoryTest(TestCase):
    def test_field_events_have_their_own_approval_category(self):
        self.assertEqual(_category("field_event", "staff"), "Field Events")


class TravelProfileDerivationTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="FE Region")
        self.home = District.objects.create(
            name="Home", region=self.region, district_type="primary"
        )
        self.away = District.objects.create(
            name="Away", region=self.region, district_type="secondary"
        )
        user = get_user_model().objects.create(
            id="fe-user-1",
            email="fe1@test.org",
            name="Field Staff",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        self.profile = StaffProfile.objects.create(
            id="fe-sp-1",
            user=user,
            title="CCEO",
            primary_district_id=self.home.id,
        )

    def _activity(self, dest_id):
        return Activity(
            activity_type="field_event",
            responsible_staff_id=self.profile.id,
            event_district_id=dest_id,
            fy="2026",
        )

    def test_destination_in_home_district_is_primary(self):
        self.assertEqual(
            _field_event_district_type(self._activity(self.home.id)), "primary"
        )

    def test_destination_in_another_district_is_secondary(self):
        self.assertEqual(
            _field_event_district_type(self._activity(self.away.id)), "secondary"
        )

    def test_without_home_district_falls_back_to_district_classification(self):
        self.profile.primary_district_id = None
        self.profile.save(update_fields=["primary_district_id"])
        self.assertEqual(
            _field_event_district_type(self._activity(self.home.id)), "primary"
        )
        self.assertEqual(
            _field_event_district_type(self._activity(self.away.id)), "secondary"
        )

    def test_no_destination_prices_as_home_work(self):
        self.assertEqual(_field_event_district_type(self._activity(None)), "primary")


class FieldEventEndToEndTest(TestCase):
    """Plan a district meeting through the canonical funnel: per-day lines from
    the CD catalogue, straight into the owner's weekly fund request."""

    def setUp(self):
        self.region = Region.objects.create(name="FE2 Region")
        self.home = District.objects.create(
            name="FE2 Home", region=self.region, district_type="primary"
        )
        self.away = District.objects.create(
            name="FE2 Away", region=self.region, district_type="secondary"
        )
        User = get_user_model()
        self.owner = User.objects.create(
            id="fe2-user-1",
            email="fe2@test.org",
            name="Deo Field",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        self.owner_sp = StaffProfile.objects.create(
            id="fe2-sp-1",
            user=self.owner,
            title="CCEO",
            primary_district_id=self.home.id,
        )
        fy = get_operational_fy()
        # Reference data seeds the active Uganda catalogue; rate it rather
        # than fighting the one-active-catalogue-per-country constraint.
        catalogue = CostCatalogue.objects.filter(
            country="Uganda", fy=fy, is_active=True
        ).first() or CostCatalogue.objects.create(
            country="Uganda", fy=fy, version=901, is_active=True
        )
        for key, unit in RATES.items():
            CostSetting.objects.update_or_create(
                key=key,
                fy=fy,
                catalogue=catalogue,
                defaults={
                    "label": key.replace("_", " ").title(),
                    "unit_cost": unit,
                },
            )

        class _Principal:
            user_id = self.owner.id
            staff_profile_id = self.owner_sp.id
            active_role = "CCEO"

        self.principal = _Principal()

    def test_overnight_district_meeting_flows_into_the_weekly_request(self):
        from apps.activity_catalogue.models import ActivityCatalogueItem
        from apps.planning.services import schedule_programme_activity

        item = ActivityCatalogueItem.objects.get(stable_code="FIELD_DISTRICT_MEETING")
        start = date.today() + timedelta(days=14)
        start -= timedelta(days=start.weekday())  # Monday, a clean week bucket
        end = start + timedelta(days=2)  # two nights away

        result = schedule_programme_activity(
            {
                "catalogueItemId": item.id,
                "scheduledDate": f"{start.isoformat()}T09:00:00+03:00",
                "endDate": end.isoformat(),
                "districtId": self.away.id,
                "venue": "District Education Office",
                "programmeActivityType": "field_event",
                "programmeDeliveryMode": "group",
                "activityPurposeText": "Quarterly coordination meeting",
                "supportRationale": "organizational_priority",
                "deliveryType": "staff",
                "responsibleStaffId": self.owner_sp.id,
            },
            self.principal,
        )
        activity = Activity.objects.get(id=result["id"])
        self.assertEqual(activity.activity_type, "field_event")
        self.assertEqual(activity.event_district_id, self.away.id)
        self.assertFalse(activity.cost_missing)

        lines = {l.cost_setting_key: l for l in activity.schedule_cost_lines.all()}
        self.assertEqual(lines["secondary_transport_per_day"].amount, 3 * 60_000)
        self.assertEqual(lines["secondary_lunch_per_day"].amount, 3 * 15_000)
        self.assertEqual(lines["secondary_accommodation_per_night"].amount, 3 * 80_000)
        self.assertEqual(lines["secondary_overnight_dinner_per_day"].amount, 3 * 12_000)
        self.assertEqual(lines["secondary_breakfast_per_day"].amount, 3 * 8_000)
        expected_total = 180_000 + 45_000 + 240_000 + 36_000 + 24_000

        # Money trail: the owner's weekly request materialised automatically.
        wfr = WeeklyFundRequest.objects.get(
            responsible_user=self.owner.id, week_start_date=start
        )
        self.assertEqual(wfr.total_amount, expected_total)
        self.assertEqual(wfr.status, "pending_responsible_confirmation")

    def test_home_district_meeting_costs_transport_and_lunch_only(self):
        from apps.activity_catalogue.models import ActivityCatalogueItem
        from apps.planning.services import schedule_programme_activity

        item = ActivityCatalogueItem.objects.get(stable_code="FIELD_DISTRICT_MEETING")
        start = date.today() + timedelta(days=21)
        start -= timedelta(days=start.weekday())

        result = schedule_programme_activity(
            {
                "catalogueItemId": item.id,
                "scheduledDate": f"{start.isoformat()}T09:00:00+03:00",
                "districtId": self.home.id,
                "venue": "District Hall",
                "programmeActivityType": "field_event",
                "programmeDeliveryMode": "group",
                "activityPurposeText": "Home-district planning meeting",
                "supportRationale": "organizational_priority",
                "deliveryType": "staff",
                "responsibleStaffId": self.owner_sp.id,
            },
            self.principal,
        )
        activity = Activity.objects.get(id=result["id"])
        lines = {l.cost_setting_key: l for l in activity.schedule_cost_lines.all()}
        self.assertEqual(
            set(lines), {"primary_transport_per_day", "primary_lunch_per_day"}
        )
        self.assertEqual(activity.est_cost_cents, 30_000)
