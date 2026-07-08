from __future__ import annotations

from datetime import date

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.budget.models import CostCatalogue, CostSetting
from apps.core.exceptions import BadRequest
from apps.core.rbac import EdifyRole
from apps.geography.models import (
    District, Region, SecondaryDistrictGroup, SecondaryDistrictGroupMember, SubCounty,
)
from apps.schools.models import School

from .exceptions import ReasonRequiredError
from .services import remove_school, schedule_visits


PRIMARY_RATES = [
    ("primary_transport_per_day", 280000),
    ("primary_lunch_per_day", 30000),
]
SECONDARY_RATES = [
    ("secondary_transport_per_day", 330000),
    ("secondary_lunch_per_day", 30000),
    ("secondary_accommodation_per_night", 150000),
    ("secondary_overnight_dinner_per_day", 50000),
]


class DailyVisitBatchTestCase(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Batch Region")
        self.primary_district = District.objects.create(
            name="Batch Primary District", region=self.region, district_type="primary",
        )
        self.secondary_district_a = District.objects.create(
            name="Batch Secondary District A", region=self.region, district_type="secondary",
        )
        self.secondary_district_b = District.objects.create(
            name="Batch Secondary District B", region=self.region, district_type="secondary",
        )
        self.unclassified_district = District.objects.create(
            name="Batch Unclassified District", region=self.region,
        )
        self.sub_county = SubCounty.objects.create(name="Batch Sub", district=self.primary_district)

        # apps.budget migrations 0003/0005 already seed one active "Uganda
        # FY2026 v1" catalogue on every test DB — reuse it (rather than
        # creating a second is_active=True row, which active_catalogue()'s
        # is_active-only lookup would resolve ambiguously) and just set the
        # tight daily target this test suite needs.
        self.catalogue, _ = CostCatalogue.objects.get_or_create(
            country="Uganda", fy="2026", version=1,
            defaults={"is_active": True, "label": "Test Catalogue", "required_school_visits_per_day": 3},
        )
        self.catalogue.required_school_visits_per_day = 3
        self.catalogue.is_active = True
        self.catalogue.save(update_fields=["required_school_visits_per_day", "is_active"])
        for key, cost in PRIMARY_RATES + SECONDARY_RATES + [("partner_visit_lump_sum", 40000)]:
            CostSetting.objects.update_or_create(
                key=key, defaults={"label": key, "unit_cost": cost, "fy": "2026", "catalogue": self.catalogue, "version": 1},
            )

        self.staff_user = User.objects.create_user(
            email="batchstaff@test.com", name="Batch Staff",
            roles=[EdifyRole.CCEO.value], active_role=EdifyRole.CCEO.value,
            password="x", is_active=True,
        )
        self.staff_profile = StaffProfile.objects.create(user=self.staff_user, title="CCEO")

        self.schools = {}
        for i in range(1, 6):
            s = School.objects.create(
                school_id=f"BATCH-P-{i}", name=f"Batch Primary School {i}",
                region=self.region, district=self.primary_district, sub_county=self.sub_county,
                current_fy_ssa_status="done", planning_readiness="ready",
            )
            StaffSchoolAssignment.objects.create(staff=self.staff_profile, school_id=s.id)
            self.schools[f"p{i}"] = s

        self.sec_school_a = School.objects.create(
            school_id="BATCH-SEC-A", name="Batch Secondary School A",
            region=self.region, district=self.secondary_district_a, sub_county=self.sub_county,
            current_fy_ssa_status="done", planning_readiness="ready",
        )
        self.sec_school_b = School.objects.create(
            school_id="BATCH-SEC-B", name="Batch Secondary School B",
            region=self.region, district=self.secondary_district_b, sub_county=self.sub_county,
            current_fy_ssa_status="done", planning_readiness="ready",
        )
        for s in (self.sec_school_a, self.sec_school_b):
            StaffSchoolAssignment.objects.create(staff=self.staff_profile, school_id=s.id)

        self.unclassified_school = School.objects.create(
            school_id="BATCH-UNCL", name="Batch Unclassified School",
            region=self.region, district=self.unclassified_district, sub_county=self.sub_county,
            current_fy_ssa_status="done", planning_readiness="ready",
        )
        StaffSchoolAssignment.objects.create(staff=self.staff_profile, school_id=self.unclassified_school.id)

        self.principal = self.staff_user
        self.base_fields = {
            "activityType": "school_visit", "deliveryType": "staff",
            "activityPurposeText": "Routine visit", "focusIntervention": "leadership",
        }

    def _schedule(self, school_ids, visit_date, reason=None):
        return schedule_visits(
            school_ids=school_ids, scheduled_date=visit_date,
            activity_common_fields=self.base_fields, reason=reason, principal=self.principal,
        )

    # ── 1. Single school = batch of 1 (primary) ──────────────────────────────
    def test_single_school_batch_of_one(self):
        result = self._schedule(["BATCH-P-1"], date(2026, 8, 3), reason="solo visit")
        batch_id = result["batchId"]
        from .models import DailyVisitBatch
        batch = DailyVisitBatch.objects.get(id=batch_id)
        self.assertEqual(batch.school_count, 1)
        expected_pool = sum(c for _, c in PRIMARY_RATES)
        self.assertEqual(batch.daily_pool_amount, expected_pool)
        act = Activity.objects.get(id=result["activities"][0]["id"])
        self.assertEqual(act.est_cost_cents, expected_pool)
        lines = list(ActivityScheduleCostLine.objects.filter(activity=act))
        self.assertEqual(len(lines), 2)  # transport + lunch
        self.assertEqual(sum(l.amount for l in lines), expected_pool)

    # ── 2. Bulk 3-school split, exact-sum remainder distribution ─────────────
    def test_bulk_schedule_splits_pool_exactly(self):
        result = self._schedule(["BATCH-P-1", "BATCH-P-2", "BATCH-P-3"], date(2026, 8, 4))
        activities = [Activity.objects.get(id=a["id"]) for a in result["activities"]]
        pool = sum(c for _, c in PRIMARY_RATES)
        total_allocated = sum(a.est_cost_cents for a in activities)
        self.assertEqual(total_allocated, pool)  # no shillings lost to rounding
        for a in activities:
            self.assertGreater(a.est_cost_cents, 0)

    # ── 3. Mixing primary + secondary rejected ───────────────────────────────
    def test_mixing_primary_and_secondary_rejected(self):
        with self.assertRaises(BadRequest):
            self._schedule(["BATCH-P-1", "BATCH-SEC-A"], date(2026, 8, 5))

    def test_mixing_against_existing_batch_rejected(self):
        self._schedule(["BATCH-P-1"], date(2026, 8, 6), reason="under target on purpose")
        with self.assertRaises(BadRequest):
            self._schedule(["BATCH-SEC-A"], date(2026, 8, 6))

    # ── 4. Unapproved secondary combo rejected, then approved ───────────────
    def test_unapproved_secondary_group_rejected_then_approved(self):
        # 2 schools also happens to be under the target of 3 — but the
        # unapproved-group check runs BEFORE the target check, so this must
        # still fail on the group rule, not the reason-required rule.
        with self.assertRaises(BadRequest) as ctx:
            self._schedule(["BATCH-SEC-A", "BATCH-SEC-B"], date(2026, 8, 7))
        self.assertNotIsInstance(ctx.exception, ReasonRequiredError)

        group = SecondaryDistrictGroup.objects.create(name="Batch Secondary Route", status="approved")
        SecondaryDistrictGroupMember.objects.create(group=group, district=self.secondary_district_a)
        SecondaryDistrictGroupMember.objects.create(group=group, district=self.secondary_district_b)

        result = self._schedule(["BATCH-SEC-A", "BATCH-SEC-B"], date(2026, 8, 7), reason="under target on purpose")
        self.assertEqual(len(result["activities"]), 2)

    # ── 5. Over-cap hard reject ──────────────────────────────────────────────
    def test_over_target_cap_rejected(self):
        # required_school_visits_per_day = 3 on the test catalogue.
        with self.assertRaises(BadRequest) as ctx:
            self._schedule(["BATCH-P-1", "BATCH-P-2", "BATCH-P-3", "BATCH-P-4"], date(2026, 8, 8))
        self.assertIn("You can only schedule 3", str(ctx.exception))

    # ── 6. Under-target soft block, then success with reason ───────────────
    def test_under_target_requires_reason(self):
        with self.assertRaises(ReasonRequiredError):
            self._schedule(["BATCH-P-1"], date(2026, 8, 9))
        result = self._schedule(["BATCH-P-1"], date(2026, 8, 9), reason="staff on leave this week")
        from .models import DailyVisitBatch
        batch = DailyVisitBatch.objects.get(id=result["batchId"])
        self.assertEqual(batch.reason, "staff on leave this week")

    # ── 7. Adding a school recalculates existing allocations ────────────────
    def test_adding_school_recalculates_existing(self):
        first = self._schedule(["BATCH-P-1", "BATCH-P-2"], date(2026, 8, 10), reason="under target on purpose")
        act1_before = Activity.objects.get(id=first["activities"][0]["id"])
        cost_before = act1_before.est_cost_cents

        self._schedule(["BATCH-P-3"], date(2026, 8, 10))
        act1_after = Activity.objects.get(id=first["activities"][0]["id"])
        self.assertNotEqual(act1_after.est_cost_cents, cost_before)
        pool = sum(c for _, c in PRIMARY_RATES)
        # Remainder shillings go to the first school(s) in stable order — allow
        # either the exact third or one shilling-share above it.
        self.assertIn(act1_after.est_cost_cents, (pool // 3, pool // 3 + 1))

    # ── 8. Removing a school recalculates the remainder ─────────────────────
    def test_remove_school_recalculates_remainder(self):
        result = self._schedule(["BATCH-P-1", "BATCH-P-2", "BATCH-P-3"], date(2026, 8, 11))
        ids = [a["id"] for a in result["activities"]]
        remove_school(activity_id=ids[0])
        remaining = [Activity.objects.get(id=i) for i in ids[1:]]
        pool = sum(c for _, c in PRIMARY_RATES)
        for a in remaining:
            self.assertEqual(a.est_cost_cents, pool // 2)

    # ── 9. Locked batch rejects further mutation ─────────────────────────────
    def test_locked_batch_rejects_mutation(self):
        result = self._schedule(["BATCH-P-1"], date(2026, 8, 12), reason="test")
        act = Activity.objects.get(id=result["activities"][0]["id"])

        from apps.fund_requests.weekly_service import request_advance
        wfr = act.schedule_cost_lines.first()
        from apps.fund_requests.models import WeeklyFundRequestLine
        wfr_line = WeeklyFundRequestLine.objects.filter(activity_budget_line=wfr).first()
        self.assertIsNotNone(wfr_line, "expected a WeeklyFundRequest to have been auto-generated")
        request_advance(wfr_line.weekly_fund_request_id, self.principal)

        with self.assertRaises(BadRequest):
            self._schedule(["BATCH-P-2"], date(2026, 8, 12), reason="test")

    # ── 10. Partner-conducted visits are entirely unaffected ────────────────
    def test_partner_visit_not_batched(self):
        from apps.activities.services import create as create_activity

        result = create_activity({
            "activityType": "school_visit", "deliveryType": "partner",
            "schoolId": "BATCH-P-1", "scheduledDate": "2026-08-13T09:00:00+03:00",
            "activityPurposeText": "Partner visit", "focusIntervention": "leadership",
        }, self.principal)
        act = Activity.objects.get(id=result["id"])
        self.assertIsNone(act.daily_visit_batch_id)

    # ── 11. Unclassified district blocked with a clear message ──────────────
    def test_unclassified_district_blocked(self):
        with self.assertRaises(BadRequest) as ctx:
            self._schedule(["BATCH-UNCL"], date(2026, 8, 14), reason="test")
        self.assertIn("not been classified", str(ctx.exception))


class DailyVisitBatchSystemHealthTestCase(TestCase):
    """Constructs broken states directly via the ORM (bypassing the service's
    own guards) to confirm each new System Health check actually fires."""

    def setUp(self):
        self.region = Region.objects.create(name="Health Region")
        self.primary_district = District.objects.create(
            name="Health Primary District", region=self.region, district_type="primary",
        )
        self.sub_county = SubCounty.objects.create(name="Health Sub", district=self.primary_district)
        # Reuse the catalogue apps.budget migrations 0003/0005 already seed
        # (see DailyVisitBatchTestCase.setUp for why get_or_create is required).
        self.catalogue, _ = CostCatalogue.objects.get_or_create(
            country="Uganda", fy="2026", version=1,
            defaults={"is_active": True, "required_school_visits_per_day": 5},
        )
        self.catalogue.required_school_visits_per_day = 5
        self.catalogue.is_active = True
        self.catalogue.save(update_fields=["required_school_visits_per_day", "is_active"])
        for key, cost in PRIMARY_RATES:
            CostSetting.objects.update_or_create(
                key=key, defaults={"label": key, "unit_cost": cost, "fy": "2026", "catalogue": self.catalogue, "version": 1},
            )
        self.staff_user = User.objects.create_user(
            email="healthstaff@test.com", name="Health Staff",
            roles=[EdifyRole.CCEO.value], active_role=EdifyRole.CCEO.value,
            password="x", is_active=True,
        )
        self.staff_profile = StaffProfile.objects.create(user=self.staff_user, title="CCEO")
        self.school = School.objects.create(
            school_id="HEALTH-SCH", name="Health School", region=self.region,
            district=self.primary_district, sub_county=self.sub_county,
            current_fy_ssa_status="done", planning_readiness="ready",
        )
        StaffSchoolAssignment.objects.create(staff=self.staff_profile, school_id=self.school.id)

    def test_scheduled_visit_missing_batch_check_fires(self):
        from apps.activities.services import create as create_activity
        from apps.system_health.services import _workflow_issues

        create_activity({
            "activityType": "school_visit", "deliveryType": "staff",
            "schoolId": "HEALTH-SCH", "scheduledDate": "2026-08-20T09:00:00+03:00",
            "activityPurposeText": "Direct create bypassing batch service",
            "focusIntervention": "leadership", "_skip_cost_snapshot": True,
        }, self.staff_user)

        health = _workflow_issues()
        self.assertGreaterEqual(health["scheduledVisitsMissingBatch"], 1)
        self.assertFalse(health["clean"])

    def test_catalogue_missing_batch_keys_check_fires(self):
        from apps.system_health.services import _workflow_issues

        CostSetting.objects.filter(key__in=[k for k, _ in PRIMARY_RATES]).delete()
        health = _workflow_issues()
        self.assertGreater(health["catalogueMissingDailyBatchKeys"], 0)
