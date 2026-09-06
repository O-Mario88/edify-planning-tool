"""The planner's figure is real, not a dash.

`approved_minimum` is what a CCEO or Programme Lead sees while planning:
`costing_service.minimum_cost` prices the planned quantities from these rates
and refuses to fall back to the operational card, so a blank field showed the
planner nothing while the plan behind it accumulated the full operational
cost. Nothing had ever written the field (owner, 2026-09-05: "set the minimum
viable costs for all 14 rates").
"""

from __future__ import annotations

from django.test import TestCase

from apps.budget.costing_service import active_catalogue, preview
from apps.budget.models import CostSetting
from apps.budget.reference import CANONICAL_RATE_KEYS


class EveryLiveRateHasAMinimumTest(TestCase):
    def test_no_canonical_rate_is_missing_its_minimum(self):
        rates = CostSetting.objects.filter(
            catalogue=active_catalogue(), key__in=CANONICAL_RATE_KEYS
        )
        self.assertEqual(rates.count(), len(CANONICAL_RATE_KEYS))
        blank = sorted(r.key for r in rates if r.approved_minimum is None)
        self.assertEqual(blank, [])

    def test_no_operational_rate_sits_below_its_own_minimum(self):
        """The governance check flags this state; the default must not create
        it. Equal is fine — the approved rate is its own floor."""
        below = [
            r.key
            for r in CostSetting.objects.filter(catalogue=active_catalogue())
            if r.approved_minimum is not None and r.unit_cost < r.approved_minimum
        ]
        self.assertEqual(below, [])


class ThePlannerSeesANumberTest(TestCase):
    CASES = (
        ({"activityType": "school_visit", "districtType": "primary"}, 62_000),
        # 2026-09-06 catalogue: no incidentals row, so the secondary day is
        # transport + lunch + dinner + accommodation + breakfast.
        ({"activityType": "school_visit", "districtType": "secondary"}, 152_000),
        ({"activityType": "core_visit", "districtType": "primary"}, 62_000),
        ({"activityType": "baseline_ssa_visit", "districtType": "primary"}, 62_000),
        (
            {
                "activityType": "cluster_training",
                "districtType": "primary",
                "expectedParticipants": 20,
            },
            # Facilitation + venue + the staff day. Only a TOT training feeds
            # its participants (owner's list, 2026-09-06); the cluster
            # session's own rate and the materials default to 0.
            142_000,
        ),
    )

    def test_the_minimum_preview_prices_every_planned_shape(self):
        for payload, expected in self.CASES:
            with self.subTest(activityType=payload["activityType"]):
                result = preview({**payload, "deliveryType": "staff"}, minimum=True)
                self.assertEqual(result["costBasis"], "minimum_viable")
                self.assertEqual(result["missingItems"], [])
                self.assertFalse(result["costMissing"])
                self.assertEqual(result["amount"], expected)

    def test_a_new_rate_never_arrives_without_a_minimum(self):
        """`ensure_cost_reference` restores canonical rates after a flush."""
        from apps.budget.reference import ensure_cost_reference

        catalogue = active_catalogue()
        CostSetting.objects.filter(
            catalogue=catalogue, key="lunch_per_day"
        ).delete()
        ensure_cost_reference(catalogue)
        restored = CostSetting.objects.get(
            catalogue=catalogue, key="lunch_per_day"
        )
        self.assertIsNotNone(restored.approved_minimum)
        self.assertEqual(restored.approved_minimum, restored.unit_cost)
