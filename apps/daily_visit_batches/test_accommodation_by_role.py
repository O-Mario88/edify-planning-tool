"""The night away is paid at the traveller's accommodation rate.

Owner, 2026-10-05: "the accommodation for program leads, cd, IA and accountant
should be separate from the accommodation of CCEO. add a new accommodation
cost for the above roles. If the role is PL, IA, CD and accountant fetch the
cost for accommodation set for those roles. if it is for the cceos, fetch the
accommodation set for cceos."
"""

from __future__ import annotations

from datetime import date
from importlib import import_module

from django.apps import apps as django_apps
from django.test import SimpleTestCase
from freezegun import freeze_time

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.budget.costing_service import preview
from apps.budget.models import CostCatalogue, CostSetting
from apps.core.rbac import EdifyRole
from apps.schools.models import School

from .districts import (
    MANAGEMENT_ACCOMMODATION_ROLES,
    accommodation_key_for_role,
    accommodation_key_for_staff,
)
from .models import DailyVisitBatch
from .pricing import (
    ACCOMMODATION_KEY,
    ACCOMMODATION_KEYS,
    MANAGEMENT_ACCOMMODATION_KEY,
    compute_daily_pool,
    day_keys,
)
from .services import batch_needs_repricing
from .tests import SECONDARY_RATES, DailyVisitBatchTestCase

CCEO_NIGHT = dict(SECONDARY_RATES)[ACCOMMODATION_KEY]
MANAGEMENT_NIGHT = 210000
# Transport, lunch, breakfast and dinner: the secondary day without its night.
DAY_WITHOUT_NIGHT = sum(dict(SECONDARY_RATES).values()) - CCEO_NIGHT


class AccommodationRateByRoleTest(SimpleTestCase):
    def test_the_four_named_roles_fetch_the_second_rate(self):
        self.assertEqual(
            MANAGEMENT_ACCOMMODATION_ROLES,
            {
                EdifyRole.COUNTRY_PROGRAM_LEAD.value,
                EdifyRole.COUNTRY_DIRECTOR.value,
                EdifyRole.IMPACT_ASSESSMENT.value,
                EdifyRole.PROGRAM_ACCOUNTANT.value,
            },
        )
        for role in MANAGEMENT_ACCOMMODATION_ROLES:
            with self.subTest(role=role):
                self.assertEqual(
                    accommodation_key_for_role(role), MANAGEMENT_ACCOMMODATION_KEY
                )

    def test_a_cceo_and_every_role_not_named_fetch_the_cceo_rate(self):
        others = set(EdifyRole.values()) - MANAGEMENT_ACCOMMODATION_ROLES
        self.assertIn(EdifyRole.CCEO.value, others)
        for role in sorted(others) + [None, ""]:
            with self.subTest(role=role):
                self.assertEqual(accommodation_key_for_role(role), ACCOMMODATION_KEY)

    def test_the_role_is_read_as_an_enum_member_too(self):
        self.assertEqual(
            accommodation_key_for_role(EdifyRole.COUNTRY_DIRECTOR),
            MANAGEMENT_ACCOMMODATION_KEY,
        )
        self.assertEqual(accommodation_key_for_role(EdifyRole.CCEO), ACCOMMODATION_KEY)

    def test_only_the_night_changes_in_the_day(self):
        cceo = day_keys("secondary")
        management = day_keys("secondary", MANAGEMENT_ACCOMMODATION_KEY)
        self.assertEqual(
            [key for key in cceo if key not in ACCOMMODATION_KEYS],
            [key for key in management if key not in ACCOMMODATION_KEYS],
        )
        self.assertIn(ACCOMMODATION_KEY, cceo)
        self.assertNotIn(MANAGEMENT_ACCOMMODATION_KEY, cceo)
        self.assertIn(MANAGEMENT_ACCOMMODATION_KEY, management)
        self.assertNotIn(ACCOMMODATION_KEY, management)
        # A primary day has no night, whoever travels.
        self.assertEqual(
            day_keys("primary", MANAGEMENT_ACCOMMODATION_KEY), day_keys("primary")
        )

    def test_a_card_from_before_the_split_prices_every_night_from_its_one_row(self):
        rates = dict(SECONDARY_RATES)
        self.assertNotIn(MANAGEMENT_ACCOMMODATION_KEY, rates)
        pool = compute_daily_pool(rates, "secondary", MANAGEMENT_ACCOMMODATION_KEY)
        self.assertEqual(pool[MANAGEMENT_ACCOMMODATION_KEY], CCEO_NIGHT)
        self.assertEqual(
            sum(pool.values()), sum(compute_daily_pool(rates, "secondary").values())
        )


@freeze_time("2026-07-27")
class NightAwayByRoleTest(DailyVisitBatchTestCase):
    def setUp(self):
        super().setUp()
        CostSetting.objects.update_or_create(
            key=MANAGEMENT_ACCOMMODATION_KEY,
            catalogue=self.catalogue,
            defaults={
                "label": "Accommodation - PL, CD, IA and Accountant",
                "unit_cost": MANAGEMENT_NIGHT,
                "fy": self.catalogue.fy,
                "version": 1,
            },
        )

    def _traveller(self, role):
        user = User.objects.create_user(
            email=f"night-{role.replace(' ', '').lower()}@test.com",
            name=f"Night {role}",
            roles=[role],
            active_role=role,
            password="x",
            is_active=True,
        )
        profile = StaffProfile.objects.create(user=user, title=role)
        for school in (self.sec_school_a, self.sec_school_b):
            StaffSchoolAssignment.objects.create(staff=profile, school_id=school.id)
        return user, profile

    def _own_secondary_school(self, profile, code):
        """A school of its own for each traveller: a school has one staff
        support visit a year, whoever makes it."""
        school = School.objects.create(
            school_id=code,
            name=f"Night School {code}",
            region=self.region,
            district=self.secondary_district_a,
            sub_county=self.sub_county,
            current_fy_ssa_status="done",
            planning_readiness="ready",
        )
        StaffSchoolAssignment.objects.create(staff=profile, school_id=school.id)
        return school

    def _night_lines(self, activity):
        return {
            line.cost_setting_key: line
            for line in ActivityScheduleCostLine.objects.filter(
                activity=activity, line_item_type="accommodation"
            )
        }

    def test_a_cceos_night_is_the_cceo_rate(self):
        result = self._schedule(["BATCH-SEC-A"], date(2026, 8, 6), reason="solo")
        visit = Activity.objects.get(id=result["activities"][0]["id"])
        night = self._night_lines(visit)
        self.assertEqual(set(night), {ACCOMMODATION_KEY})
        self.assertEqual(night[ACCOMMODATION_KEY].amount, CCEO_NIGHT)
        self.assertEqual(visit.est_cost_cents, DAY_WITHOUT_NIGHT + CCEO_NIGHT)

    def test_each_named_roles_night_is_the_second_rate(self):
        for offset, role in enumerate(sorted(MANAGEMENT_ACCOMMODATION_ROLES)):
            user, profile = self._traveller(role)
            self.principal = user
            with self.subTest(role=role):
                self.assertEqual(
                    accommodation_key_for_staff(user.id), MANAGEMENT_ACCOMMODATION_KEY
                )
                self.assertEqual(
                    accommodation_key_for_staff(profile.id),
                    MANAGEMENT_ACCOMMODATION_KEY,
                )
                school = self._own_secondary_school(profile, f"NIGHT-{offset}")
                result = self._schedule(
                    [school.school_id], date(2026, 8, 10 + offset), reason="solo"
                )
                visit = Activity.objects.get(id=result["activities"][0]["id"])
                night = self._night_lines(visit)
                self.assertEqual(set(night), {MANAGEMENT_ACCOMMODATION_KEY})
                self.assertEqual(
                    night[MANAGEMENT_ACCOMMODATION_KEY].amount, MANAGEMENT_NIGHT
                )
                self.assertEqual(night[MANAGEMENT_ACCOMMODATION_KEY].quantity, 1)
                self.assertEqual(
                    visit.est_cost_cents, DAY_WITHOUT_NIGHT + MANAGEMENT_NIGHT
                )
                batch = DailyVisitBatch.objects.get(id=result["batchId"])
                self.assertEqual(
                    batch.daily_pool_amount, DAY_WITHOUT_NIGHT + MANAGEMENT_NIGHT
                )
                self.assertFalse(batch_needs_repricing(batch))

    def test_the_night_is_shared_across_the_days_schools_at_the_second_rate(self):
        user, _profile = self._traveller(EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        self.principal = user
        self.sec_school_b.district = self.secondary_district_a
        self.sec_school_b.save(update_fields=["district"])
        result = self._schedule(
            ["BATCH-SEC-A", "BATCH-SEC-B"], date(2026, 8, 6), reason="two schools"
        )
        visits = Activity.objects.filter(
            id__in=[item["id"] for item in result["activities"]]
        )
        nights = [
            line.amount
            for visit in visits
            for line in self._night_lines(visit).values()
        ]
        self.assertEqual(sorted(nights), [MANAGEMENT_NIGHT // 2] * 2)
        self.assertEqual(
            sum(visit.est_cost_cents for visit in visits),
            DAY_WITHOUT_NIGHT + MANAGEMENT_NIGHT,
        )

    def test_the_drawer_preview_names_the_travellers_rate(self):
        user, _profile = self._traveller(EdifyRole.PROGRAM_ACCOUNTANT.value)
        for traveller, key, amount in (
            (self.staff_user, ACCOMMODATION_KEY, CCEO_NIGHT),
            (user, MANAGEMENT_ACCOMMODATION_KEY, MANAGEMENT_NIGHT),
        ):
            with self.subTest(traveller=traveller.active_role):
                result = preview(
                    {
                        "activityType": "school_visit",
                        "deliveryType": "staff",
                        "schoolId": "BATCH-SEC-A",
                        "plannedDate": "2026-08-06",
                    },
                    responsible_user_id=traveller.id,
                )
                nights = {
                    line["key"]: line["amount"]
                    for line in result["lines"]
                    if line["key"] in ACCOMMODATION_KEYS
                }
                self.assertEqual(nights, {key: amount})
                self.assertEqual(result["amount"], DAY_WITHOUT_NIGHT + amount)

    def test_a_night_priced_before_the_split_is_moved_to_its_travellers_rate(self):
        """A Program Lead's night planned while there was one accommodation
        row sits under the CCEO's. The day reads as stale, and re-pricing it
        (a returned week, the refresh command) moves it."""
        from .services import _recalculate_and_write_lines

        user, _profile = self._traveller(EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        self.principal = user
        result = self._schedule(["BATCH-SEC-A"], date(2026, 8, 6), reason="solo")
        batch = DailyVisitBatch.objects.get(id=result["batchId"])
        visit = Activity.objects.get(id=result["activities"][0]["id"])
        from apps.budget.models import ActivityCostSnapshot

        snapshot = ActivityCostSnapshot.objects.get(activity=visit, is_current=True)
        snapshot.operational_breakdown = [
            {**line, "key": ACCOMMODATION_KEY}
            if line.get("key") == MANAGEMENT_ACCOMMODATION_KEY
            else line
            for line in snapshot.operational_breakdown
        ]
        # A snapshot is frozen to everything but a queryset update.
        ActivityCostSnapshot.objects.filter(pk=snapshot.pk).update(
            operational_breakdown=snapshot.operational_breakdown
        )
        self.assertTrue(batch_needs_repricing(batch))

        _recalculate_and_write_lines(batch, None, batch.responsible_user)
        batch.refresh_from_db()
        self.assertFalse(batch_needs_repricing(batch))
        self.assertEqual(set(self._night_lines(visit)), {MANAGEMENT_ACCOMMODATION_KEY})


@freeze_time("2026-07-27")
class SecondAccommodationRateMigrationTest(DailyVisitBatchTestCase):
    """budget migration 0024, run against the live models."""

    def _run(self):
        migration = import_module(
            "apps.budget.migrations.0024_management_accommodation_rate"
        )
        migration.forwards(django_apps, None)
        return migration

    def test_the_new_row_starts_at_the_figure_the_one_row_had(self):
        CostSetting.objects.filter(
            catalogue=self.catalogue, key=MANAGEMENT_ACCOMMODATION_KEY
        ).delete()
        CostSetting.objects.filter(
            catalogue=self.catalogue, key=ACCOMMODATION_KEY
        ).update(label="Accommodation", approved_minimum=120000)

        migration = self._run()

        new = CostSetting.objects.get(
            catalogue=self.catalogue, key=MANAGEMENT_ACCOMMODATION_KEY
        )
        self.assertEqual(new.unit_cost, CCEO_NIGHT)
        self.assertEqual(new.approved_minimum, 120000)
        self.assertEqual(new.label, migration.NEW_LABEL)
        self.assertEqual(new.unit, "per night")
        cceo = CostSetting.objects.get(catalogue=self.catalogue, key=ACCOMMODATION_KEY)
        self.assertEqual(cceo.label, migration.CCEO_LABEL)
        self.assertEqual(cceo.unit_cost, CCEO_NIGHT)

    def test_a_rate_and_a_name_the_country_director_set_are_kept(self):
        CostSetting.objects.filter(
            catalogue=self.catalogue, key=MANAGEMENT_ACCOMMODATION_KEY
        ).update(unit_cost=MANAGEMENT_NIGHT)
        CostSetting.objects.filter(
            catalogue=self.catalogue, key=ACCOMMODATION_KEY
        ).update(label="Hotel night")

        self._run()

        self.assertEqual(
            CostSetting.objects.get(
                catalogue=self.catalogue, key=MANAGEMENT_ACCOMMODATION_KEY
            ).unit_cost,
            MANAGEMENT_NIGHT,
        )
        self.assertEqual(
            CostSetting.objects.get(
                catalogue=self.catalogue, key=ACCOMMODATION_KEY
            ).label,
            "Hotel night",
        )

    def test_every_rate_card_with_an_accommodation_row_gets_the_second(self):
        other = CostCatalogue.objects.create(
            country=self.catalogue.country,
            fy="2019",
            version=1,
            is_active=False,
            label="An older card",
        )
        CostSetting.objects.create(
            catalogue=other,
            key=ACCOMMODATION_KEY,
            label="Accommodation",
            unit_cost=77000,
            fy="2019",
            version=1,
        )

        self._run()

        new = CostSetting.objects.get(catalogue=other, key=MANAGEMENT_ACCOMMODATION_KEY)
        self.assertEqual(new.unit_cost, 77000)
        self.assertEqual(new.approved_minimum, 77000)
