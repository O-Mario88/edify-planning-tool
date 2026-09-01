from __future__ import annotations

from types import SimpleNamespace

from rest_framework.test import APITestCase

from apps.accounts.jwt import issue_access_token
from apps.accounts.models import User
from apps.budget import services
from apps.budget.costing_service import active_catalogue
from apps.budget.governance_service import list_rate_cards, publish_rate_card
from apps.budget.models import (
    CostCatalogue,
    CostSetting,
    CountryStrategicActivityReserve,
    RateCardKind,
    RateCardStatus,
    StrategicReserveStatus,
)
from apps.core.fy import get_operational_fy
from apps.core.exceptions import BadRequest
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

    def test_every_training_component_uses_the_same_plan_with_its_own_card(self):
        reference = self._publish_reference_copy_for_test()
        operational = active_catalogue(self.fy)
        component_rates = {
            "group_training_participant_meal_cost_per_head": (12_000, 22_000),
            "group_training_facilitation_fee": (30_000, 50_000),
            "group_training_venue_cost": (40_000, 70_000),
            "primary_transport_per_day": (20_000, 35_000),
            "primary_lunch_per_day": (8_000, 12_000),
        }
        for key, (operational_rate, reference_rate) in component_rates.items():
            CostSetting.objects.filter(catalogue=operational, key=key).update(
                unit_cost=operational_rate
            )
            CostSetting.objects.filter(catalogue=reference, key=key).update(
                unit_cost=reference_rate
            )

        self._as(self.cd)
        response = self.client.post(
            "/api/budget/costing/management-preview",
            {
                "activityType": "cluster_training",
                "deliveryType": "staff",
                "expectedParticipants": 10,
                "days": 1,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        operational_lines = {
            line["key"]: line for line in payload["operationalBreakdown"]
        }
        reference_lines = {line["key"]: line for line in payload["referenceBreakdown"]}
        self.assertEqual(
            operational_lines["group_training_participant_meal_cost_per_head"][
                "amount"
            ],
            120_000,
        )
        self.assertEqual(
            reference_lines["group_training_participant_meal_cost_per_head"]["amount"],
            220_000,
        )
        self.assertEqual(payload["operationalCost"], 218_000)
        self.assertEqual(payload["referenceCost"], 387_000)

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

    def test_cd_dashboard_rate_edit_respects_approved_minimum(self):
        card = active_catalogue(self.fy)
        line = CostSetting.objects.filter(catalogue=card, unit_cost__gt=0).first()
        line.approved_minimum = line.unit_cost
        line.save(update_fields=["approved_minimum", "updated_at"])
        principal = SimpleNamespace(
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
            user_id=self.cd.id,
        )
        with self.assertRaisesMessage(BadRequest, "below the approved minimum"):
            services.upsert_cost_setting(
                {
                    "key": line.key,
                    "label": line.label,
                    "unitCost": line.unit_cost - 1,
                    "fy": self.fy,
                    "reason": "Test a non-viable rate",
                },
                principal,
            )
        self.assertEqual(active_catalogue(self.fy).id, card.id)

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

    def test_operational_card_below_approved_minimum_cannot_be_published(self):
        latest = (
            CostCatalogue.objects.filter(fy=self.fy, kind=RateCardKind.OPERATIONAL)
            .order_by("-version")
            .first()
        )
        draft = CostCatalogue.objects.create(
            country="Uganda",
            fy=self.fy,
            kind=RateCardKind.OPERATIONAL,
            version=latest.version + 1,
            status=RateCardStatus.DRAFT,
            is_active=False,
            currency="UGX",
        )
        CostSetting.objects.create(
            catalogue=draft,
            key="primary_transport_per_day",
            label="Primary transport per day",
            unit_cost=50_000,
            approved_minimum=70_000,
        )
        principal = SimpleNamespace(
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
            user_id=self.cd.id,
        )
        with self.assertRaisesMessage(BadRequest, "below the approved minimum"):
            publish_rate_card(principal, draft.id)

    def test_rvp_cannot_create_strategic_reserve(self):
        self._as(self.rvp)
        response = self.client.post(
            "/api/budget/strategic-reserve",
            {"fy": self.fy, "openingReserve": 1_000_000},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
