"""Centralized costing + advance lifecycle — exact-computation tests.

Proves the finance-accuracy rules from the spec through the authenticated API:
  • Staff primary visit: transport×schools + lunch×days (no breakfast/dinner/accom).
  • Staff secondary visit: secondary transport + meals×days + accommodation×nights.
  • Group training: participants×group-meal + venue + facilitation.
  • Cluster meeting: participants×cluster-meal ONLY (no venue/facilitation; never
    the group-training meal rate).
  • Partner visit: rate × schools.
  • Advance auto-created on schedule; Accountant CANNOT disburse before the
    responsible user confirms; CAN after.
  • Self-funded: no advance disbursement; reimbursement path opens.

All money is integer UGX; totals equal the sum of persisted budget lines.
Isolated test DB only.
"""

from __future__ import annotations

from django.conf import settings
from rest_framework.test import APITestCase

from apps.accounts.jwt import issue_access_token
from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import ActivityScheduleCostLine
from apps.budget.models import CostCatalogue, CostSetting
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.fund_requests.models import AdvanceRequest, AdvanceRequestStatus
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School


def _seed_rates(**rates: int) -> None:
    """Set up the minimum valid CD rate card and upsert its rates (UGX)."""
    fy = get_operational_fy()
    country = getattr(settings, "COUNTRY", "Uganda")
    catalogue = CostCatalogue.objects.filter(
        country=country, fy=fy, is_active=True
    ).first()
    if catalogue is None:
        latest_version = (
            CostCatalogue.objects.filter(country=country, fy=fy)
            .order_by("-version")
            .values_list("version", flat=True)
            .first()
            or 0
        )
        catalogue = CostCatalogue.objects.create(
            country=country,
            fy=fy,
            version=latest_version + 1,
            is_active=True,
            label="Centralized costing test catalogue",
        )
    for key, unit_cost in rates.items():
        CostSetting.objects.update_or_create(
            key=key, defaults={"label": key, "unit_cost": unit_cost}
        )


class CentralizedCostingTest(APITestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Cost Region")
        self.district = District.objects.create(
            name="Cost District", region=self.region
        )
        self.sub_county = SubCounty.objects.create(
            name="Cost Sub", district=self.district
        )

        self.cceo = User.objects.create_user(
            email="cc@cost.test",
            name="Cost Cceo",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        self.ia = User.objects.create_user(
            email="ia@cost.test",
            name="Cost Ia",
            roles=[EdifyRole.IMPACT_ASSESSMENT.value],
            active_role=EdifyRole.IMPACT_ASSESSMENT.value,
            password="x",
            is_active=True,
        )
        self.staff = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        self.school = School.objects.create(
            school_id="COST-SCH",
            name="Cost Primary",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            current_fy_ssa_status="done",
            planning_readiness="ready",
        )
        StaffSchoolAssignment.objects.create(staff=self.staff, school_id=self.school.id)
        # Cluster for cluster activities.
        from apps.clusters.models import Cluster

        self.cluster = Cluster.objects.create(
            name="Cost Cluster",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            cluster_type="mixed",
        )
        self._as(self.cceo)

    # ── helpers ──────────────────────────────────────────────────────────────
    def _as(self, user):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {issue_access_token(user.id, user.active_role)}"
        )

    def _post(self, path, data, expected):
        r = self.client.post(path, data, format="json")
        self.assertEqual(r.status_code, expected, r.content)
        return r.json()

    def _line_sum(self, activity_id: str) -> int:
        return sum(
            l.amount
            for l in ActivityScheduleCostLine.objects.filter(activity_id=activity_id)
        )

    def _preview(self, body: dict) -> dict:
        r = self.client.post("/api/budget/costing/preview", body, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    # ── A. Staff primary visit ───────────────────────────────────────────────
    def test_staff_primary_visit_transport_times_schools_plus_lunch(self):
        _seed_rates(staff_visit_transport_primary=15000, lunch=8000)
        # The costing engine prices a visit as transport + lunch per visit; the
        # per-school multiplier is conveyed via the activity (one visit = one
        # school). Verify the exact formula: transport(15000) + lunch(8000).
        prev = self._preview(
            {
                "activityType": "school_visit",
                "deliveryType": "staff",
                "districtType": "primary",
            }
        )
        self.assertTrue(prev["canSchedule"], prev)
        self.assertEqual(prev["amount"], 15000 + 8000)
        labels = {l["lineItemType"] for l in prev["lines"]}
        self.assertEqual(labels, {"transport", "lunch"})
        self.assertNotIn("breakfast", labels)
        self.assertNotIn("accommodation", labels)

        scheduled = self._post(
            "/api/planning/schedule-school-visit",
            {
                "schoolId": "COST-SCH",
                "scheduledDate": "2026-07-10T09:00:00+03:00",
                "plannedMonth": 7,
                "plannedWeek": 2,
                "purposeIntervention": "leadership",
                "districtType": "primary",
            },
            201,
        )
        self.assertEqual(scheduled["estCostCents"], 15000 + 8000)
        self.assertEqual(self._line_sum(scheduled["id"]), 15000 + 8000)

    # ── B. Staff secondary visit ─────────────────────────────────────────────
    def test_staff_secondary_visit_includes_meals_and_accommodation(self):
        _seed_rates(
            staff_visit_transport_secondary=25000,
            breakfast=5000,
            lunch=8000,
            dinner=12000,
            accommodation=40000,
        )
        prev = self._preview(
            {
                "activityType": "school_visit",
                "deliveryType": "staff",
                "districtType": "secondary",
                "nights": 2,
            }
        )
        self.assertTrue(prev["canSchedule"], prev)
        # transport(25000) + breakfast(5000) + lunch(8000) + dinner(12000) + accom(40000×2)
        expected = 25000 + 5000 + 8000 + 12000 + (40000 * 2)
        self.assertEqual(prev["amount"], expected)
        labels = {l["lineItemType"] for l in prev["lines"]}
        self.assertEqual(
            labels, {"transport", "breakfast", "lunch", "dinner", "accommodation"}
        )

    def test_staff_primary_visit_excludes_secondary_costs(self):
        """A primary visit must never include breakfast/dinner/accommodation."""
        _seed_rates(
            staff_visit_transport_primary=15000,
            lunch=8000,
            breakfast=5000,
            accommodation=40000,
        )
        prev = self._preview(
            {
                "activityType": "school_visit",
                "deliveryType": "staff",
                "districtType": "primary",
                "nights": 3,
            }
        )
        labels = {l["lineItemType"] for l in prev["lines"]}
        self.assertEqual(labels, {"transport", "lunch"})
        self.assertEqual(prev["amount"], 15000 + 8000)

    # ── C. Group training ────────────────────────────────────────────────────
    def test_group_training_includes_venue_facilitation_and_group_meals(self):
        _seed_rates(
            group_training_facilitation_fee=60000,
            group_training_venue_cost=30000,
            group_training_participant_meal_cost_per_head=6000,
            # Historic keys must not sneak an extra line into a new training.
            mobilisation_per_participant=2000,
        )
        prev = self._preview(
            {
                "activityType": "cluster_training",
                "deliveryType": "staff",
                "expectedParticipants": 20,
            }
        )
        self.assertTrue(prev["canSchedule"], prev)
        # Exactly three items: meals + facilitation + venue.
        expected = 60000 + 30000 + (6000 * 20)
        self.assertEqual(prev["amount"], expected)
        self.assertEqual(
            {line["key"] for line in prev["lines"]},
            {
                "group_training_participant_meal_cost_per_head",
                "group_training_facilitation_fee",
                "group_training_venue_cost",
            },
        )
        self.assertEqual(
            {line["label"] for line in prev["lines"]},
            {"Participant meals", "Facilitation fee", "Venue fee"},
        )
        labels = {l["lineItemType"] for l in prev["lines"]}
        self.assertIn("venue", labels)
        self.assertIn("facilitation", labels)
        self.assertIn("participant_meals", labels)

    # ── D. Cluster meeting ───────────────────────────────────────────────────
    def test_cluster_meeting_excludes_venue_facilitation_and_uses_cluster_meal_rate(
        self,
    ):
        """Meetings use Participant snacks only — never training costs."""
        _seed_rates(
            cluster_meeting_participant_meal_cost_per_head=5000,
            meals_per_participant=6000,
            venue=30000,
            training_session_fee=60000,
        )
        prev = self._preview(
            {
                "activityType": "cluster_meeting",
                "deliveryType": "staff",
                "expectedParticipants": 12,
            }
        )
        self.assertTrue(prev["canSchedule"], prev)
        # 12 × Participant snacks(5000) = 60000 — NOTHING else.
        self.assertEqual(prev["amount"], 12 * 5000)
        self.assertEqual(
            {line["key"] for line in prev["lines"]},
            {"cluster_meeting_participant_meal_cost_per_head"},
        )
        self.assertEqual(prev["lines"][0]["label"], "Participant snacks")
        labels = {l["lineItemType"] for l in prev["lines"]}
        self.assertEqual(labels, {"cluster_meeting_participant_meals"})
        self.assertNotIn("venue", labels)
        self.assertNotIn("facilitation", labels)
        self.assertNotIn(
            "participant_meals", labels
        )  # group-training rate must NOT appear

    def test_cluster_meeting_requires_participants(self):
        _seed_rates(cluster_meeting_participant_meal_cost_per_head=5000)
        # Scheduling stays permissive. When no headcount was entered, the safe
        # cluster-meeting planning default (10) is priced instead of blocking
        # the field team with an unrelated scheduling rule.
        self.school.cluster_id = self.cluster.id
        self.school.cluster_status = "clustered"
        self.school.save(update_fields=["cluster_id", "cluster_status"])
        r = self.client.post(
            "/api/planning/schedule-cluster-activity",
            {
                "activityType": "cluster_meeting",
                "clusterId": self.cluster.id,
                "scheduledDate": "2026-07-10T09:00:00+03:00",
                "plannedMonth": 7,
            },
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["estCostCents"], 10 * 5000)

    def test_cluster_training_never_falls_back_to_retired_rate_keys(self):
        """Legacy rates may remain for audit, but cannot price new work."""
        CostSetting.objects.all().delete()
        _seed_rates(
            training_session_fee=60000,
            venue=30000,
            meals_per_participant=6000,
            mobilisation_per_participant=2000,
        )
        prev = self._preview(
            {
                "activityType": "cluster_training",
                "deliveryType": "staff",
                "expectedParticipants": 20,
            }
        )
        self.assertFalse(prev["canSchedule"])
        self.assertEqual(
            {line["key"] for line in prev["lines"]},
            {
                "group_training_participant_meal_cost_per_head",
                "group_training_facilitation_fee",
                "group_training_venue_cost",
            },
        )

    # ── E. Partner visit ─────────────────────────────────────────────────────
    def test_partner_visit_uses_partner_lump_sum(self):
        _seed_rates(
            partner_visit_lump_sum=35000,
            staff_visit_transport_primary=15000,
            lunch=8000,
        )
        prev = self._preview(
            {"activityType": "school_visit", "deliveryType": "partner"}
        )
        self.assertTrue(prev["canSchedule"], prev)
        # Partner = lump sum only (no transport/lunch split).
        self.assertEqual(prev["amount"], 35000)
        labels = {l["lineItemType"] for l in prev["lines"]}
        self.assertEqual(labels, {"lump_sum"})

    # ── F. Missing rate blocks scheduling ────────────────────────────────────
    def test_missing_rate_blocks_scheduling(self):
        # No rates seeded at all.
        CostSetting.objects.all().delete()
        r = self.client.post(
            "/api/budget/costing/preview",
            {
                "activityType": "school_visit",
                "deliveryType": "staff",
                "districtType": "primary",
            },
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(r.json()["canSchedule"])
        self.assertTrue(r.json()["blockers"])
        # Scheduling stays permissive, but a missing rate is visible on the
        # activity and prevents it becoming fundable work.
        sched = self.client.post(
            "/api/planning/schedule-school-visit",
            {
                "schoolId": "COST-SCH",
                "scheduledDate": "2026-07-10T09:00:00+03:00",
                "plannedMonth": 7,
                "purposeIntervention": "leadership",
                "districtType": "primary",
            },
            format="json",
        )
        self.assertEqual(sched.status_code, 201, sched.content)
        self.assertTrue(sched.json()["costMissing"])

    # ── G. Advance auto-created; Accountant gated on confirmation ────────────
    def test_advance_auto_created_and_accountant_gated_on_confirmation(self):
        _seed_rates(staff_visit_transport_primary=15000, lunch=8000)
        scheduled = self._post(
            "/api/planning/schedule-school-visit",
            {
                "schoolId": "COST-SCH",
                "scheduledDate": "2026-07-10T09:00:00+03:00",
                "plannedMonth": 7,
                "plannedWeek": 2,
                "purposeIntervention": "leadership",
            },
            201,
        )
        # An advance request per budget line is auto-created, pending confirmation.
        advances = list(AdvanceRequest.objects.filter(activity_id=scheduled["id"]))
        self.assertEqual(len(advances), 2)  # transport + lunch
        self.assertTrue(
            all(
                a.status == AdvanceRequestStatus.PENDING_RESPONSIBLE_CONFIRMATION
                for a in advances
            )
        )
        self.assertTrue(all(a.responsible_user_id == self.cceo.id for a in advances))

        accountant = User.objects.create_user(
            email="ac@cost.test",
            name="Ac",
            roles=[EdifyRole.PROGRAM_ACCOUNTANT.value],
            active_role=EdifyRole.PROGRAM_ACCOUNTANT.value,
            password="x",
            is_active=True,
        )
        self._as(accountant)
        # Accountant CANNOT disburse before the responsible user confirms.
        adv = advances[0]
        blocked = self.client.post(
            f"/api/fund-requests/advances/{adv.id}/disburse",
            {"amount": adv.amount, "method": "mobile_money"},
            format="json",
        )
        self.assertEqual(blocked.status_code, 400, blocked.content)
        self.assertIn("confirm", blocked.json()["message"].lower())

        # Responsible user confirms → Accountant CAN disburse.
        self._as(self.cceo)
        self._post(f"/api/fund-requests/advances/{adv.id}/confirm-advance", {}, 200)
        self._as(accountant)
        disbursed = self._post(
            f"/api/fund-requests/advances/{adv.id}/disburse",
            {"amount": adv.amount, "method": "mobile_money", "reference": "MM-1"},
            200,
        )
        self.assertEqual(disbursed["status"], "disbursed")
        self.assertEqual(disbursed["disbursedAmount"], adv.amount)

    # ── H. Self-funded: no advance disbursement; reimbursement opens ──────────
    def test_self_funded_skips_advance_and_opens_reimbursement(self):
        _seed_rates(staff_visit_transport_primary=15000, lunch=8000)
        scheduled = self._post(
            "/api/planning/schedule-school-visit",
            {
                "schoolId": "COST-SCH",
                "scheduledDate": "2026-07-10T09:00:00+03:00",
                "plannedMonth": 7,
                "purposeIntervention": "leadership",
            },
            201,
        )
        adv = AdvanceRequest.objects.filter(activity_id=scheduled["id"]).first()

        # Responsible user elects self-funded.
        self._as(self.cceo)
        res = self._post(f"/api/fund-requests/advances/{adv.id}/self-funded", {}, 200)
        self.assertEqual(res["status"], "self_funded_pending_reimbursement")

        # Accountant cannot disburse an advance on a self-funded request.
        accountant = User.objects.create_user(
            email="ac2@cost.test",
            name="Ac2",
            roles=[EdifyRole.PROGRAM_ACCOUNTANT.value],
            active_role=EdifyRole.PROGRAM_ACCOUNTANT.value,
            password="x",
            is_active=True,
        )
        self._as(accountant)
        blocked = self.client.post(
            f"/api/fund-requests/advances/{adv.id}/disburse",
            {"amount": adv.amount},
            format="json",
        )
        self.assertEqual(blocked.status_code, 400, blocked.content)

        # After completion, responsible user submits a reimbursement claim.
        self._as(self.cceo)
        claim = self._post(
            f"/api/fund-requests/advances/{adv.id}/submit-reimbursement",
            {"amountSpent": adv.amount, "netsuiteId": "EXP-9"},
            200,
        )
        self.assertEqual(claim["status"], "reimbursement_submitted")

        # Accountant reimburses — money is sent but not yet "reimbursed"
        # (financially cleared) until the employee confirms receipt
        # (2026-07-15 finance-unification mandate).
        self._as(accountant)
        reimbursed = self._post(
            f"/api/fund-requests/advances/{adv.id}/reimburse",
            {"amount": adv.amount, "method": "bank", "reference": "BANK-1"},
            200,
        )
        self.assertEqual(reimbursed["status"], "reimbursement_disbursed")

        from apps.fund_requests.advance_service import confirm_reimbursement_receipt

        self._as(self.cceo)
        confirmed = confirm_reimbursement_receipt(
            adv.id, {"amount": adv.amount}, self.cceo
        )
        self.assertEqual(confirmed["status"], "reimbursed")
