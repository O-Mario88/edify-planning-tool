"""A staff member's day of school visits (apps.budget.school_visit_costing).

Who travels decides whether the day is primary or secondary; a client school
visit costs exactly what a core one costs; and the day's money is shared
equally across every visit on it.
"""

from __future__ import annotations

from decimal import Decimal

from django.test import SimpleTestCase

from apps.budget.school_visit_costing import (
    PrimaryDistrictRates,
    SecondaryDistrictRates,
    StaffUser,
    cost_school_visit_day,
    resolve_visit_district_type,
)
from apps.budget.session_costing import CostingValidationError
from apps.daily_visit_batches.pricing import allocate_pool, compute_daily_pool

PRIMARY = PrimaryDistrictRates(transport=50_000, lunch=12_000)
SECONDARY = SecondaryDistrictRates(
    transport=80_000, breakfast=8_000, lunch=12_000, dinner=12_000, accommodation=40_000
)
CD = StaffUser(id="u-cd", name="Country Director", role="CountryDirector")
IA = StaffUser(id="u-ia", name="Impact Assessor", role="ImpactAssessment")
CCEO_GULU = StaffUser(
    id="u-cceo", name="Gulu CCEO", role="CCEO", primary_district="Gulu"
)
PL_MBARARA = StaffUser(
    id="u-pl", name="Mbarara Lead", role="Program Lead", primary_district="Mbarara"
)


class DistrictResolutionTests(SimpleTestCase):
    def test_head_office_is_primary_in_the_kampala_wakiso_mukono_zone(self):
        for user in (
            CD,
            IA,
            StaffUser("u-ed", "Executive", "ED"),
            StaffUser("u-acc", "Accountant", "Accountant"),
        ):
            for district in ("Kampala", "Wakiso", "Mukono", "kampala", " WAKISO "):
                with self.subTest(role=user.role, district=district):
                    self.assertEqual(
                        resolve_visit_district_type(user, district), "primary"
                    )

    def test_head_office_is_secondary_anywhere_else(self):
        for district in ("Jinja", "Gulu", "Mbarara"):
            with self.subTest(district=district):
                self.assertEqual(resolve_visit_district_type(CD, district), "secondary")

    def test_a_head_office_profile_district_does_not_move_the_zone(self):
        cd = StaffUser("u", "CD", "CountryDirector", primary_district="Jinja")
        self.assertEqual(resolve_visit_district_type(cd, "Jinja"), "secondary")
        self.assertEqual(resolve_visit_district_type(cd, "Kampala"), "primary")

    def test_field_staff_are_primary_only_in_their_own_district(self):
        self.assertEqual(resolve_visit_district_type(CCEO_GULU, "Gulu"), "primary")
        self.assertEqual(resolve_visit_district_type(CCEO_GULU, " GULU "), "primary")
        for district in ("Kampala", "Wakiso", "Mukono", "Jinja"):
            with self.subTest(district=district):
                self.assertEqual(
                    resolve_visit_district_type(CCEO_GULU, district), "secondary"
                )
        self.assertEqual(resolve_visit_district_type(PL_MBARARA, "Mbarara"), "primary")
        self.assertEqual(
            resolve_visit_district_type(PL_MBARARA, "Kampala"), "secondary"
        )

    def test_the_spec_spells_the_field_roles_pl_and_cceo(self):
        pl = {"id": "u", "name": "Lead", "role": "PL", "primaryDistrict": "Gulu"}
        self.assertEqual(resolve_visit_district_type(pl, "Gulu"), "primary")
        self.assertEqual(resolve_visit_district_type(pl, "Kampala"), "secondary")

    def test_a_field_user_without_a_primary_district_is_refused(self):
        for role in ("CCEO", "PL", "Program Lead"):
            with self.subTest(role=role):
                with self.assertRaises(CostingValidationError):
                    resolve_visit_district_type(StaffUser("u", "n", role), "Gulu")
                with self.assertRaises(CostingValidationError):
                    cost_school_visit_day(
                        StaffUser("u", "n", role),
                        "Gulu",
                        1,
                        1,
                        primary_rates=PRIMARY,
                        secondary_rates=SECONDARY,
                    )

    def test_a_blank_target_district_is_refused(self):
        with self.assertRaises(CostingValidationError):
            resolve_visit_district_type(CD, "  ")
        with self.assertRaises(CostingValidationError):
            cost_school_visit_day(CD, "", 1, 0, primary_rates=PRIMARY)


class PrimaryDayTests(SimpleTestCase):
    def test_two_core_and_three_client_visits_share_the_day_equally(self):
        cost = cost_school_visit_day(CCEO_GULU, "Gulu", 2, 3, primary_rates=PRIMARY)
        self.assertEqual(cost.district_type, "primary")
        self.assertTrue(cost.is_field_staff)
        self.assertEqual(cost.total_visits, 5)
        self.assertEqual(cost.daily_operational.transport, 50_000)
        self.assertEqual(cost.daily_operational.lunch, 12_000)
        self.assertEqual(cost.daily_operational.total_daily_cost, 62_000)
        share = cost.allocated_per_visit
        self.assertEqual(share.allocated_transport, 10_000)
        self.assertEqual(share.allocated_lunch, 2_400)
        self.assertEqual(share.cost_per_school_visit, 12_400)
        self.assertEqual(cost.totals.cost_per_core_visit, 12_400)
        self.assertEqual(cost.totals.cost_per_client_visit, 12_400)
        self.assertEqual(cost.totals.core_visits_total, 24_800)
        self.assertEqual(cost.totals.client_visits_total, 37_200)
        self.assertEqual(cost.totals.total_day_cost, 62_000)

    def test_only_the_primary_rates_are_needed_on_a_primary_day(self):
        cost = cost_school_visit_day(CD, "Kampala", 4, 0, primary_rates=PRIMARY)
        self.assertEqual(cost.totals.cost_per_school_visit, 15_500)
        with self.assertRaises(CostingValidationError) as ctx:
            cost_school_visit_day(CD, "Kampala", 4, 0, secondary_rates=SECONDARY)
        self.assertIn("primary_rates", str(ctx.exception))

    def test_a_single_visit_carries_the_whole_day(self):
        cost = cost_school_visit_day(CD, "Mukono", 0, 1, primary_rates=PRIMARY)
        self.assertEqual(cost.totals.cost_per_school_visit, 62_000)
        self.assertEqual(cost.totals.client_visits_total, 62_000)
        self.assertEqual(cost.totals.core_visits_total, 0)


class SecondaryDayTests(SimpleTestCase):
    def test_head_office_in_jinja_carries_the_per_diem_and_a_night(self):
        cost = cost_school_visit_day(CD, "Jinja", 1, 3, secondary_rates=SECONDARY)
        self.assertEqual(cost.district_type, "secondary")
        self.assertFalse(cost.is_field_staff)
        day = cost.daily_operational
        self.assertEqual(day.daily_per_diem, 32_000)
        self.assertEqual(day.total_daily_cost, 152_000)
        share = cost.allocated_per_visit
        self.assertEqual(share.allocated_transport, 20_000)
        self.assertEqual(share.allocated_breakfast, 2_000)
        self.assertEqual(share.allocated_lunch, 3_000)
        self.assertEqual(share.allocated_dinner, 3_000)
        self.assertEqual(share.allocated_accommodation, 10_000)
        self.assertEqual(share.cost_per_school_visit, 38_000)
        self.assertEqual(
            share.allocated_transport
            + share.allocated_breakfast
            + share.allocated_lunch
            + share.allocated_dinner
            + share.allocated_accommodation,
            share.cost_per_school_visit,
        )
        self.assertEqual(cost.totals.core_visits_total, 38_000)
        self.assertEqual(cost.totals.client_visits_total, 114_000)
        self.assertEqual(cost.totals.total_day_cost, 152_000)

    def test_a_cceo_visiting_kampala_is_a_secondary_day(self):
        cost = cost_school_visit_day(
            CCEO_GULU, "Kampala", 2, 2, primary_rates=PRIMARY, secondary_rates=SECONDARY
        )
        self.assertEqual(cost.district_type, "secondary")
        self.assertEqual(cost.totals.cost_per_school_visit, 38_000)

    def test_only_the_secondary_rates_are_needed_on_a_secondary_day(self):
        with self.assertRaises(CostingValidationError) as ctx:
            cost_school_visit_day(CD, "Gulu", 1, 1, primary_rates=PRIMARY)
        self.assertIn("secondary_rates", str(ctx.exception))


class CostParityTests(SimpleTestCase):
    def test_every_mix_of_core_and_client_visits_prices_each_visit_the_same(self):
        for core, client in ((1, 0), (0, 1), (2, 2), (1, 3), (4, 0), (3, 5)):
            with self.subTest(core=core, client=client):
                cost = cost_school_visit_day(
                    CD, "Kampala", core, client, primary_rates=PRIMARY
                )
                self.assertEqual(
                    cost.totals.cost_per_core_visit, cost.totals.cost_per_client_visit
                )
                self.assertEqual(
                    cost.totals.cost_per_core_visit,
                    Decimal(62_000) / (core + client),
                )

    def test_the_visits_add_back_up_to_the_day(self):
        for total in (1, 2, 4, 5, 8):
            with self.subTest(total=total):
                cost = cost_school_visit_day(
                    CD, "Kampala", total - total // 2, total // 2, primary_rates=PRIMARY
                )
                self.assertEqual(
                    cost.totals.core_visits_total + cost.totals.client_visits_total,
                    62_000,
                )
                self.assertEqual(cost.totals.total_day_cost, 62_000)


class ValidationTests(SimpleTestCase):
    def test_a_day_with_no_visits_is_refused(self):
        with self.assertRaises(CostingValidationError) as ctx:
            cost_school_visit_day(CD, "Kampala", 0, 0, primary_rates=PRIMARY)
        self.assertIn("at least one", str(ctx.exception))

    def test_negative_counts_and_rates_are_refused(self):
        with self.assertRaises(CostingValidationError):
            cost_school_visit_day(CD, "Kampala", -1, 2, primary_rates=PRIMARY)
        with self.assertRaises(CostingValidationError):
            cost_school_visit_day(CD, "Kampala", 1, -2, primary_rates=PRIMARY)
        with self.assertRaises(CostingValidationError):
            cost_school_visit_day(
                CD, "Kampala", 1, 1, primary_rates={"transport": -1, "lunch": 0}
            )
        with self.assertRaises(CostingValidationError):
            cost_school_visit_day(
                CD,
                "Jinja",
                1,
                1,
                secondary_rates={**SECONDARY.__dict__, "accommodation": "forty"},
            )

    def test_the_specs_camel_case_payload_prices_like_the_dataclasses(self):
        from_payload = cost_school_visit_day(
            {
                "id": "u-cceo",
                "name": "Gulu CCEO",
                "role": "CCEO",
                "primaryDistrict": "Gulu",
            },
            "Gulu",
            "2",
            "3",
            primary_rates={"transport": "50000", "lunch": 12000.0},
        )
        from_dataclasses = cost_school_visit_day(
            CCEO_GULU, "Gulu", 2, 3, primary_rates=PRIMARY
        )
        self.assertEqual(from_payload, from_dataclasses)
        self.assertEqual(
            from_payload.to_dict()["totals"]["cost_per_school_visit"], 12_400
        )


class EngineParityTests(SimpleTestCase):
    """The Daily Visit Batch shares the same day the same way, in whole
    shillings: every visit's share sits within a shilling per rate of the
    calculator's exact quotient, and the shares add back up to the day."""

    CARD = {
        "primary_transport_per_day": 50_000,
        "lunch_per_day": 12_000,
        "secondary_transport_per_day": 80_000,
        "secondary_breakfast_per_day": 8_000,
        "secondary_overnight_dinner_per_day": 12_000,
        "secondary_accommodation_per_night": 40_000,
    }

    def test_the_batch_agrees_with_the_calculator(self):
        for user, district, district_type, rates in (
            (CCEO_GULU, "Gulu", "primary", PRIMARY),
            (CD, "Kampala", "primary", PRIMARY),
            (CD, "Jinja", "secondary", SECONDARY),
            (CCEO_GULU, "Kampala", "secondary", SECONDARY),
        ):
            pool = compute_daily_pool(self.CARD, district_type)
            for total in (1, 2, 3, 5):
                with self.subTest(user=user.role, district=district, visits=total):
                    cost = cost_school_visit_day(
                        user,
                        district,
                        total // 2,
                        total - total // 2,
                        primary_rates=rates if district_type == "primary" else None,
                        secondary_rates=rates if district_type == "secondary" else None,
                    )
                    self.assertEqual(cost.district_type, district_type)
                    self.assertEqual(sum(pool.values()), cost.totals.total_day_cost)
                    shares = [sum(s.values()) for s in allocate_pool(pool, total)]
                    self.assertEqual(sum(shares), cost.totals.total_day_cost)
                    for share in shares:
                        self.assertLessEqual(
                            abs(Decimal(share) - cost.totals.cost_per_school_visit),
                            len(pool),
                        )
