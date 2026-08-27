from __future__ import annotations

from types import SimpleNamespace

from rest_framework.test import APITestCase

from apps.accounts.jwt import issue_access_token
from apps.accounts.models import User
from apps.budget import services
from apps.budget.costing_service import active_catalogue
from apps.budget.governance_service import list_rate_cards
from apps.budget.models import (
    CostCatalogue,
    CostSetting,
    CountryStrategicActivityReserve,
    RateCardKind,
    RateCardStatus,
    StrategicReserveStatus,
)
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole, permissions_for_role


class DualRateCardSecurityTest(APITestCase):
    def setUp(self):
        self.cd = User.objects.create_user(
            email="dual-cd@example.test",
            name="Dual Card CD",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
            password="x",
        )
        self.cceo = User.objects.create_user(
            email="dual-cceo@example.test",
            name="Dual Card CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
        )
        self.rvp = User.objects.create_user(
            email="dual-rvp@example.test",
            name="Dual Card RVP",
            roles=[EdifyRole.REGIONAL_VICE_PRESIDENT.value],
            active_role=EdifyRole.REGIONAL_VICE_PRESIDENT.value,
            password="x",
        )
        self.fy = get_operational_fy()

    def _as(self, user):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {issue_access_token(user.id, user.active_role)}"
        )

    def _publish_reference_copy_for_test(self):
        operational = active_catalogue(self.fy)
        CostCatalogue.objects.filter(
            country=operational.country,
            fy=self.fy,
            kind=RateCardKind.REFERENCE,
        ).update(is_active=False, status=RateCardStatus.RETIRED)
        reference = CostCatalogue.objects.create(
            country=operational.country,
            fy=self.fy,
            kind=RateCardKind.REFERENCE,
            version=99,
            status=RateCardStatus.PUBLISHED,
            is_active=True,
            currency="UGX",
            label="Approved internal reference test card",
        )
        CostSetting.objects.bulk_create(
            [
                CostSetting(
                    catalogue=reference,
                    key=line.key,
                    label=line.label,
                    unit_cost=line.unit_cost + 100,
                    fy=self.fy,
                    version=1,
                )
                for line in CostSetting.objects.filter(catalogue=operational)
            ]
        )
        return reference

    def test_reference_configuration_is_not_fabricated(self):
        reference = CostCatalogue.objects.filter(
            fy=self.fy, kind=RateCardKind.REFERENCE
        ).first()
        self.assertIsNotNone(reference)
        self.assertNotEqual(reference.status, RateCardStatus.PUBLISHED)
        self.assertFalse(reference.rates.exists())

    def test_staff_preview_never_serializes_reference_fields(self):
        self._publish_reference_copy_for_test()
        self._as(self.cceo)
        response = self.client.post(
            "/api/budget/costing/preview",
            {"activityType": "school_visit", "districtType": "primary"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        self.assertNotIn("referenceCost", payload)
        self.assertNotIn("referenceBreakdown", payload)
        self.assertNotIn("referenceRateCardId", payload)

    def test_management_preview_contains_both_layers_for_cd(self):
        self._publish_reference_copy_for_test()
        self._as(self.cd)
        response = self.client.post(
            "/api/budget/costing/management-preview",
            {"activityType": "school_visit", "districtType": "primary"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNotNone(response.json()["referenceCost"])
        self.assertIn("operationalCost", response.json())

    def test_management_preview_is_forbidden_to_field_staff(self):
        self._as(self.cceo)
        response = self.client.post(
            "/api/budget/costing/management-preview",
            {"activityType": "school_visit", "districtType": "primary"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_pl_permission_set_has_no_reference_or_reserve_visibility(self):
        permissions = set(permissions_for_role(EdifyRole.COUNTRY_PROGRAM_LEAD))
        self.assertNotIn("rateCard.reference.view", permissions)
        self.assertNotIn("activityCost.reference.view", permissions)
        self.assertNotIn("strategicReserve.view", permissions)

    def test_staff_rate_card_list_contains_operational_layer_only(self):
        self._publish_reference_copy_for_test()
        principal = SimpleNamespace(
            active_role=EdifyRole.CCEO.value,
            user_id=self.cceo.id,
        )
        result = list_rate_cards(principal, fy=self.fy)
        self.assertTrue(result["rateCards"])
        self.assertEqual(
            {card["kind"] for card in result["rateCards"]},
            {RateCardKind.OPERATIONAL},
        )

    def test_operational_rate_edit_publishes_new_version_and_preserves_old(self):
        old_card = active_catalogue(self.fy)
        old_line = CostSetting.objects.get(
            catalogue=old_card, key="primary_lunch_per_day"
        )
        old_amount = old_line.unit_cost
        principal = SimpleNamespace(
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
            user_id=self.cd.id,
        )
        result = services.upsert_cost_setting(
            {
                "key": old_line.key,
                "label": old_line.label,
                "unitCost": old_amount + 500,
                "fy": self.fy,
                "reason": "Approved fuel and meal review",
            },
            principal,
        )
        old_line.refresh_from_db()
        old_card.refresh_from_db()
        new_card = active_catalogue(self.fy)
        self.assertEqual(
            CostSetting.objects.get(
                catalogue=old_card, key="primary_lunch_per_day"
            ).unit_cost,
            old_amount,
        )
        self.assertEqual(old_line.unit_cost, old_amount + 500)
        self.assertEqual(old_line.catalogue_id, new_card.id)
        self.assertEqual(old_card.status, RateCardStatus.SUPERSEDED)
        self.assertNotEqual(new_card.id, old_card.id)
        self.assertGreater(new_card.version, old_card.version)
        self.assertEqual(result["unitCost"], old_amount + 500)

    def test_country_director_can_create_and_rvp_can_approve_reserve(self):
        self._as(self.cd)
        create_response = self.client.post(
            "/api/budget/strategic-reserve",
            {
                "country": "Uganda",
                "fy": self.fy,
                "periodKey": "annual",
                "openingReserve": 12_000_000,
                "approvedAdditions": 3_000_000,
                "notes": "Approved annual contingency envelope",
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, 201, create_response.content)
        reserve = CountryStrategicActivityReserve.objects.get(
            id=create_response.json()["id"]
        )
        self.assertEqual(reserve.status, StrategicReserveStatus.DRAFT)
        self.assertEqual(reserve.available_balance, 15_000_000)

        self._as(self.rvp)
        approval_response = self.client.post(
            f"/api/budget/strategic-reserve/{reserve.id}/approve",
            format="json",
        )
        self.assertEqual(approval_response.status_code, 200, approval_response.content)
        reserve.refresh_from_db()
        self.assertEqual(reserve.status, StrategicReserveStatus.APPROVED)
        self.assertEqual(reserve.approved_by, str(self.rvp.id))

    def test_rvp_cannot_create_strategic_reserve(self):
        self._as(self.rvp)
        response = self.client.post(
            "/api/budget/strategic-reserve",
            {"fy": self.fy, "openingReserve": 1_000_000},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
