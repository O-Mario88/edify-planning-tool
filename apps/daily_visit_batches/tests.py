from __future__ import annotations

from datetime import date

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.budget.models import CostCatalogue, CostSetting
from apps.core.exceptions import BadRequest
from apps.core.rbac import EdifyRole
from apps.geography.models import (
    District,
    Region,
    SecondaryDistrictGroup,
    SecondaryDistrictGroupMember,
    SubCounty,
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
            name="Batch Primary District",
            region=self.region,
            district_type="primary",
        )
        self.secondary_district_a = District.objects.create(
            name="Batch Secondary District A",
            region=self.region,
            district_type="secondary",
        )
        self.secondary_district_b = District.objects.create(
            name="Batch Secondary District B",
            region=self.region,
            district_type="secondary",
        )
        self.unclassified_district = District.objects.create(
            name="Batch Unclassified District",
            region=self.region,
        )
        self.sub_county = SubCounty.objects.create(
            name="Batch Sub", district=self.primary_district
        )

        # apps.budget migrations 0003/0005 already seed one active "Uganda
        # FY2026 v1" catalogue on every test DB — reuse it (rather than
        # creating a second is_active=True row, which active_catalogue()'s
        # is_active-only lookup would resolve ambiguously) and just set the
        # tight daily target this test suite needs.
        self.catalogue, _ = CostCatalogue.objects.get_or_create(
            country="Uganda",
            fy="2026",
            version=1,
            defaults={
                "is_active": True,
                "label": "Test Catalogue",
                "required_school_visits_per_day": 3,
            },
        )
        self.catalogue.required_school_visits_per_day = 3
        self.catalogue.is_active = True
        self.catalogue.save(
            update_fields=["required_school_visits_per_day", "is_active"]
        )
        for key, cost in (
            PRIMARY_RATES + SECONDARY_RATES + [("partner_visit_lump_sum", 40000)]
        ):
            CostSetting.objects.update_or_create(
                key=key,
                defaults={
                    "label": key,
                    "unit_cost": cost,
                    "fy": "2026",
                    "catalogue": self.catalogue,
                    "version": 1,
                },
            )

        self.staff_user = User.objects.create_user(
            email="batchstaff@test.com",
            name="Batch Staff",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        self.staff_profile = StaffProfile.objects.create(
            user=self.staff_user, title="CCEO"
        )

        self.schools = {}
        for i in range(1, 6):
            s = School.objects.create(
                school_id=f"BATCH-P-{i}",
                name=f"Batch Primary School {i}",
                region=self.region,
                district=self.primary_district,
                sub_county=self.sub_county,
                current_fy_ssa_status="done",
                planning_readiness="ready",
            )
            StaffSchoolAssignment.objects.create(
                staff=self.staff_profile, school_id=s.id
            )
            self.schools[f"p{i}"] = s

        self.sec_school_a = School.objects.create(
            school_id="BATCH-SEC-A",
            name="Batch Secondary School A",
            region=self.region,
            district=self.secondary_district_a,
            sub_county=self.sub_county,
            current_fy_ssa_status="done",
            planning_readiness="ready",
        )
        self.sec_school_b = School.objects.create(
            school_id="BATCH-SEC-B",
            name="Batch Secondary School B",
            region=self.region,
            district=self.secondary_district_b,
            sub_county=self.sub_county,
            current_fy_ssa_status="done",
            planning_readiness="ready",
        )
        for s in (self.sec_school_a, self.sec_school_b):
            StaffSchoolAssignment.objects.create(
                staff=self.staff_profile, school_id=s.id
            )

        self.unclassified_school = School.objects.create(
            school_id="BATCH-UNCL",
            name="Batch Unclassified School",
            region=self.region,
            district=self.unclassified_district,
            sub_county=self.sub_county,
            current_fy_ssa_status="done",
            planning_readiness="ready",
        )
        StaffSchoolAssignment.objects.create(
            staff=self.staff_profile, school_id=self.unclassified_school.id
        )

        self.principal = self.staff_user
        self.base_fields = {
            "activityType": "school_visit",
            "deliveryType": "staff",
            "activityPurposeText": "Routine visit",
            "focusIntervention": "leadership",
        }

    def _schedule(self, school_ids, visit_date, reason=None):
        return schedule_visits(
            school_ids=school_ids,
            scheduled_date=visit_date,
            activity_common_fields=self.base_fields,
            reason=reason,
            principal=self.principal,
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

    # ── 1a. §12 mandated arithmetic: secondary 5-school split = 112,000 each ──
    def test_secondary_five_school_split_equals_112000_each(self):
        """The mandate's explicit worked example (§12): with a secondary
        daily pool of transport 330,000 + lunch 30,000 + accommodation
        150,000 + dinner 50,000 = 560,000, split across 5 schools in one
        batch, every school pays exactly 112,000 and the pool reconciles to
        the shilling. Validated at the pricing-function level so it asserts
        the formula the mandate specifies with exactly its four named rates
        (the full scheduling path additionally layers in any optional
        breakfast/incidentals rates the CD has configured in the catalogue —
        environment-dependent and out of scope for this arithmetic check)."""
        from apps.daily_visit_batches.pricing import (
            allocate_pool,
            compute_daily_pool,
        )

        rates = {
            "secondary_transport_per_day": 330000,
            "secondary_lunch_per_day": 30000,
            "secondary_accommodation_per_night": 150000,
            "secondary_overnight_dinner_per_day": 50000,
        }
        pool = compute_daily_pool(rates, "secondary")
        self.assertEqual(sum(pool.values()), 560000)

        allocations = allocate_pool(pool, 5)
        per_school = [sum(a.values()) for a in allocations]
        self.assertEqual(per_school, [112000, 112000, 112000, 112000, 112000])
        # Exact reconciliation — no shillings created or lost to rounding.
        self.assertEqual(sum(per_school), 560000)

    # ── 1b. Double-submit (double-click) must not create a duplicate visit ───
    def test_double_submit_same_school_same_day_is_idempotent(self):
        """A double-click on 'Schedule Activity' fires schedule_visits() twice
        with identical school_ids/date/staff. The second call must not create
        a second Activity for the same school on the same day."""
        first = self._schedule(["BATCH-P-1"], date(2026, 8, 3), reason="solo visit")
        with self.assertRaises(BadRequest):
            self._schedule(["BATCH-P-1"], date(2026, 8, 3), reason="solo visit")

        # ``scheduled_date`` is a timezone-aware timestamp.  The user-facing
        # duplicate rule is calendar-day based, so use Django's date lookup
        # rather than coercing a naive midnight datetime in the test.
        acts = Activity.objects.filter(
            school__school_id="BATCH-P-1", scheduled_date__date=date(2026, 8, 3)
        )
        self.assertEqual(acts.count(), 1)
        self.assertEqual(acts.first().id, first["activities"][0]["id"])

    # ── 2. Bulk 3-school split, exact-sum remainder distribution ─────────────
    def test_bulk_schedule_splits_pool_exactly(self):
        result = self._schedule(
            ["BATCH-P-1", "BATCH-P-2", "BATCH-P-3"], date(2026, 8, 4)
        )
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
        self._schedule(
            ["BATCH-P-1"], date(2026, 8, 6), reason="under target on purpose"
        )
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

        group = SecondaryDistrictGroup.objects.create(
            name="Batch Secondary Route", status="approved"
        )
        SecondaryDistrictGroupMember.objects.create(
            group=group, district=self.secondary_district_a
        )
        SecondaryDistrictGroupMember.objects.create(
            group=group, district=self.secondary_district_b
        )

        result = self._schedule(
            ["BATCH-SEC-A", "BATCH-SEC-B"],
            date(2026, 8, 7),
            reason="under target on purpose",
        )
        self.assertEqual(len(result["activities"]), 2)

    # ── 5. Over-cap hard reject ──────────────────────────────────────────────
    def test_over_target_cap_rejected(self):
        # required_school_visits_per_day = 3 on the test catalogue.
        with self.assertRaises(BadRequest) as ctx:
            self._schedule(
                ["BATCH-P-1", "BATCH-P-2", "BATCH-P-3", "BATCH-P-4"], date(2026, 8, 8)
            )
        self.assertIn("You can only schedule 3", str(ctx.exception))

    # ── 6. Under-target soft block, then success with reason ───────────────
    def test_under_target_requires_reason(self):
        # 2026-08-11 is a Tuesday — a hardcoded Sunday here would trip the
        # REG-02 scheduling-calendar gate for a reason unrelated to what this
        # test exercises (the under-target reason requirement).
        with self.assertRaises(ReasonRequiredError):
            self._schedule(["BATCH-P-1"], date(2026, 8, 11))
        result = self._schedule(
            ["BATCH-P-1"], date(2026, 8, 11), reason="staff on leave this week"
        )
        from .models import DailyVisitBatch

        batch = DailyVisitBatch.objects.get(id=result["batchId"])
        self.assertEqual(batch.reason, "staff on leave this week")

    # ── 7. Adding a school recalculates existing allocations ────────────────
    def test_adding_school_recalculates_existing(self):
        first = self._schedule(
            ["BATCH-P-1", "BATCH-P-2"],
            date(2026, 8, 10),
            reason="under target on purpose",
        )
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
        result = self._schedule(
            ["BATCH-P-1", "BATCH-P-2", "BATCH-P-3"], date(2026, 8, 11)
        )
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

        # A staff-payable line: school-visit transport is vendor-direct
        # (paid to the transport company) and never joins the weekly request.
        wfr = act.schedule_cost_lines.exclude(line_item_type="transport").first()
        from apps.fund_requests.models import WeeklyFundRequestLine

        wfr_line = WeeklyFundRequestLine.objects.filter(
            activity_budget_line=wfr
        ).first()
        self.assertIsNotNone(
            wfr_line, "expected a WeeklyFundRequest to have been auto-generated"
        )
        request_advance(wfr_line.weekly_fund_request_id, self.principal)

        with self.assertRaises(BadRequest):
            self._schedule(["BATCH-P-2"], date(2026, 8, 12), reason="test")

    # ── 10. Partner-conducted visits are entirely unaffected ────────────────
    def test_partner_visit_not_batched(self):
        from apps.activities.services import create as create_activity

        result = create_activity(
            {
                "activityType": "school_visit",
                "deliveryType": "partner",
                "schoolId": "BATCH-P-1",
                "scheduledDate": "2026-08-13T09:00:00+03:00",
                "activityPurposeText": "Partner visit",
                "focusIntervention": "leadership",
            },
            self.principal,
        )
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
            name="Health Primary District",
            region=self.region,
            district_type="primary",
        )
        self.sub_county = SubCounty.objects.create(
            name="Health Sub", district=self.primary_district
        )
        # Reuse the catalogue apps.budget migrations 0003/0005 already seed
        # (see DailyVisitBatchTestCase.setUp for why get_or_create is required).
        self.catalogue, _ = CostCatalogue.objects.get_or_create(
            country="Uganda",
            fy="2026",
            version=1,
            defaults={"is_active": True, "required_school_visits_per_day": 5},
        )
        self.catalogue.required_school_visits_per_day = 5
        self.catalogue.is_active = True
        self.catalogue.save(
            update_fields=["required_school_visits_per_day", "is_active"]
        )
        for key, cost in PRIMARY_RATES:
            CostSetting.objects.update_or_create(
                key=key,
                defaults={
                    "label": key,
                    "unit_cost": cost,
                    "fy": "2026",
                    "catalogue": self.catalogue,
                    "version": 1,
                },
            )
        self.staff_user = User.objects.create_user(
            email="healthstaff@test.com",
            name="Health Staff",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        self.staff_profile = StaffProfile.objects.create(
            user=self.staff_user, title="CCEO"
        )
        self.school = School.objects.create(
            school_id="HEALTH-SCH",
            name="Health School",
            region=self.region,
            district=self.primary_district,
            sub_county=self.sub_county,
            current_fy_ssa_status="done",
            planning_readiness="ready",
        )
        StaffSchoolAssignment.objects.create(
            staff=self.staff_profile, school_id=self.school.id
        )

    def test_scheduled_visit_missing_batch_check_fires(self):
        from apps.activities.services import create as create_activity
        from apps.system_health.services import _workflow_issues

        create_activity(
            {
                "activityType": "school_visit",
                "deliveryType": "staff",
                "schoolId": "HEALTH-SCH",
                "scheduledDate": "2026-08-20T09:00:00+03:00",
                "activityPurposeText": "Direct create bypassing batch service",
                "focusIntervention": "leadership",
            },
            self.staff_user,
            skip_cost_snapshot=True,
        )

        health = _workflow_issues()
        self.assertGreaterEqual(health["scheduledVisitsMissingBatch"], 1)
        self.assertFalse(health["clean"])

    def test_catalogue_missing_batch_keys_check_fires(self):
        from apps.system_health.services import _workflow_issues

        CostSetting.objects.filter(key__in=[k for k, _ in PRIMARY_RATES]).delete()
        health = _workflow_issues()
        self.assertGreater(health["catalogueMissingDailyBatchKeys"], 0)


class OneMissionCostPerDayTest(DailyVisitBatchTestCase):
    """Transport and personal per-diems accrue once per DAY, irrespective of
    how many activities fill it (owner rule, 2026-08-19): a training on a
    visit day joins the same pool instead of billing its own transport."""

    def test_training_shares_the_visit_days_single_pool(self):
        from apps.activities.services import create as create_activity
        from apps.activities.models import Activity

        day = date(2026, 8, 5)
        self._schedule(["BATCH-P-1"], day, reason="visit first")

        result = create_activity(
            {
                "activityType": "in_school_training",
                "deliveryType": "staff",
                "schoolId": "BATCH-P-1",
                "scheduledDate": f"{day.isoformat()}T11:00:00+03:00",
                "activityPurposeText": "Same-day training",
                "focusIntervention": "leadership",
                "expectedParticipants": 10,
            },
            self.principal,
        )
        training = Activity.objects.get(id=result["id"])
        self.assertIsNotNone(
            training.daily_visit_batch_id, "training must join the day pool"
        )

        day_activities = Activity.objects.filter(
            daily_visit_batch_id=training.daily_visit_batch_id,
            deleted_at__isnull=True,
        )
        self.assertEqual(day_activities.count(), 2)

        # ONE day of transport across the whole day, split between members.
        transport_total = sum(
            line.amount
            for a in day_activities
            for line in a.schedule_cost_lines.filter(line_item_type="transport")
        )
        self.assertEqual(transport_total, 280000)
        # ONE lunch for the person, likewise split.
        lunch_total = sum(
            line.amount
            for a in day_activities
            for line in a.schedule_cost_lines.filter(
                cost_setting_key="primary_lunch_per_day"
            )
        )
        self.assertEqual(lunch_total, 30000)

        from apps.budget.costing import GROUP_TRAINING_RATE_KEYS

        # In-school training is costed as a school visit, with no participant
        # meal, venue or facilitation line.
        training_keys = set(
            training.schedule_cost_lines.values_list("cost_setting_key", flat=True)
        )
        self.assertEqual(
            training_keys & set(GROUP_TRAINING_RATE_KEYS),
            set(),
        )

    def _session(self, kind, day, participants=12):
        from datetime import datetime
        from django.utils import timezone
        from apps.activities.services import _apply_schedule_cost_snapshot
        from django.db import transaction

        for key, rate in [
            ("group_training_participant_meal_cost_per_head", 5000),
            ("cluster_meeting_participant_meal_cost_per_head", 3000),
            ("group_training_venue_cost", 70000),
            ("group_training_facilitation_fee", 60000),
        ]:
            CostSetting.objects.update_or_create(
                key=key,
                defaults={
                    "label": key,
                    "unit_cost": rate,
                    "approved_minimum": rate // 2,
                    "catalogue": self.catalogue,
                    "fy": "2026",
                    "version": 1,
                },
            )
        from apps.clusters.models import Cluster

        cluster, _ = Cluster.objects.get_or_create(
            name="Daily session cluster",
            defaults={
                "district": self.primary_district,
                "region": self.region,
                "sub_county": self.sub_county,
                "responsible_staff_id": self.staff_profile.id,
            },
        )
        a = Activity.objects.create(
            activity_type=kind,
            delivery_type="staff",
            status="scheduled",
            cluster=cluster,
            responsible_staff_id=self.staff_profile.id,
            scheduled_date=timezone.make_aware(
                datetime.combine(day, datetime.min.time())
            ),
            planned_date=day,
            fy="2026",
            quarter="Q4",
            expected_participants=participants,
        )
        with transaction.atomic():
            _apply_schedule_cost_snapshot(a, {}, self.principal)
        return a

    def test_three_visits_split_operational_and_minimum_without_losing_rounding(self):
        from apps.budget.costing_service import planned_minimum_amounts

        CostSetting.objects.filter(key="primary_transport_per_day").update(
            approved_minimum=100001
        )
        CostSetting.objects.filter(key="primary_lunch_per_day").update(
            approved_minimum=10001
        )
        result = self._schedule(
            ["BATCH-P-1", "BATCH-P-2", "BATCH-P-3"], date(2026, 8, 10)
        )
        activities = list(
            Activity.objects.filter(daily_visit_batch_id=result["batchId"])
        )
        self.assertEqual(sum(a.est_cost_cents for a in activities), 310000)
        minimums = planned_minimum_amounts(activities)
        self.assertEqual(sum(minimums.values()), 110002)
        self.assertTrue(all(36665 <= value <= 36669 for value in minimums.values()))

    def test_visit_training_and_two_meetings_share_daily_transport_and_lunch(self):
        from django.db.models import Sum
        from apps.fund_requests.models import WeeklyFundRequest

        day = date(2026, 8, 10)
        result = self._schedule(["BATCH-P-1"], day, reason="Sessions later")
        training = self._session("cluster_training", day, participants=12)
        meeting = self._session("cluster_meeting", day, participants=8)
        self._session("cluster_meeting", day, participants=4)
        activities = Activity.objects.filter(daily_visit_batch_id=result["batchId"])
        self.assertEqual(activities.count(), 4)
        lines = ActivityScheduleCostLine.objects.filter(activity__in=activities)
        for key, amount in PRIMARY_RATES:
            self.assertEqual(
                lines.filter(cost_setting_key=key).aggregate(total=Sum("amount"))[
                    "total"
                ],
                amount,
            )
        self.assertEqual(
            lines.filter(cost_setting_key="group_training_venue_cost").aggregate(
                total=Sum("amount")
            )["total"],
            210000,
        )
        self.assertEqual(
            lines.filter(cost_setting_key="group_training_facilitation_fee").aggregate(
                total=Sum("amount")
            )["total"],
            60000,
        )
        self.assertFalse(
            meeting.schedule_cost_lines.filter(
                cost_setting_key="group_training_facilitation_fee"
            ).exists()
        )
        self.assertEqual(
            training.schedule_cost_lines.get(
                cost_setting_key="group_training_participant_meal_cost_per_head"
            ).amount,
            60000,
        )
        self.assertEqual(
            sum(activities.values_list("est_cost_cents", flat=True)), 676000
        )
        # Transport may be paid directly to a vendor: request only staff-payable lines.
        from apps.fund_requests.fundable import vendor_direct_filter
        from apps.fund_requests.finance_models import TransportPayment

        payable = lines.exclude(vendor_direct_filter()).aggregate(total=Sum("amount"))[
            "total"
        ]
        request = WeeklyFundRequest.objects.get(
            responsible_user=self.staff_user.id, week_start_date=day
        )
        self.assertEqual(request.total_amount, payable)
        self.assertEqual(
            TransportPayment.objects.get(batch_id=result["batchId"]).amount + payable,
            676000,
        )

    def test_participant_edit_reprices_session_but_does_not_duplicate_daily_pool(self):
        from apps.activities.services import patch_activity
        from django.db.models import Sum

        day = date(2026, 8, 10)
        self._schedule(["BATCH-P-1"], day, reason="Training later")
        training = self._session("cluster_training", day, participants=12)
        result = patch_activity(
            training.id, {"expectedParticipants": 20}, self.principal
        )
        self.assertEqual(result["estCostCents"], 155000 + 100000 + 60000 + 70000)
        self.assertEqual(
            training.schedule_cost_lines.get(
                cost_setting_key="group_training_participant_meal_cost_per_head"
            ).amount,
            100000,
        )
        self.assertEqual(
            ActivityScheduleCostLine.objects.filter(
                activity__daily_visit_batch=training.daily_visit_batch,
                cost_setting_key="primary_transport_per_day",
            ).aggregate(total=Sum("amount"))["total"],
            280000,
        )

    def test_rescheduling_training_rebalances_both_days(self):
        from apps.activities.services import reschedule

        first = self._schedule(
            ["BATCH-P-1"], date(2026, 8, 10), reason="Training later"
        )
        training = self._session("cluster_training", date(2026, 8, 10))
        second = self._schedule(
            ["BATCH-P-2"], date(2026, 8, 11), reason="Training later"
        )
        reschedule(
            training.id,
            {"scheduledDate": "2026-08-11T10:00:00+03:00", "reason": "Move session"},
            self.principal,
        )
        training.refresh_from_db()
        self.assertEqual(training.daily_visit_batch_id, second["batchId"])
        self.assertEqual(
            Activity.objects.get(id=first["activities"][0]["id"]).est_cost_cents, 310000
        )
        self.assertEqual(
            training.schedule_cost_lines.get(
                cost_setting_key="primary_transport_per_day"
            ).amount,
            140000,
        )
        self.assertEqual(
            Activity.objects.get(id=second["activities"][0]["id"]).est_cost_cents,
            155000,
        )

    def test_preview_uses_actual_owner_day_count_and_minimum_rates(self):
        from apps.budget.costing_service import preview

        CostSetting.objects.filter(key="primary_transport_per_day").update(
            approved_minimum=100000
        )
        CostSetting.objects.filter(key="primary_lunch_per_day").update(
            approved_minimum=20000
        )
        self._schedule(
            ["BATCH-P-1", "BATCH-P-2"], date(2026, 8, 10), reason="Two visits"
        )
        result = preview(
            {
                "activityType": "school_visit",
                "plannedDate": "2026-08-10",
                "schoolId": "BATCH-P-3",
            },
            minimum=True,
            responsible_user_id=self.staff_user.id,
        )
        self.assertEqual(result["dailyActivityCount"], 3)
        self.assertEqual(result["amount"], 40001)
        self.assertFalse(result["costMissing"])
        other = preview(
            {"activityType": "school_visit", "plannedDate": "2026-08-11"},
            minimum=True,
            responsible_user_id=self.staff_user.id,
        )
        self.assertEqual(other["amount"], 120000)

    def test_secondary_daily_components_are_charged_once_across_schools(self):
        from django.db.models import Sum
        from apps.budget.costing_service import planned_minimum_amounts

        CostSetting.objects.filter(key="secondary_incidentals_per_day").delete()

        CostSetting.objects.update_or_create(
            key="secondary_breakfast_per_day",
            defaults={
                "label": "Breakfast",
                "unit_cost": 15001,
                "approved_minimum": 7001,
                "catalogue": self.catalogue,
                "fy": "2026",
            },
        )
        for key, rate in SECONDARY_RATES:
            CostSetting.objects.filter(key=key).update(approved_minimum=rate // 2)
        self.sec_school_b.district = self.secondary_district_a
        self.sec_school_b.save(update_fields=["district"])
        result = self._schedule(
            ["BATCH-SEC-A", "BATCH-SEC-B"], date(2026, 8, 10), reason="Two schools"
        )
        members = list(Activity.objects.filter(daily_visit_batch_id=result["batchId"]))
        for key, rate in SECONDARY_RATES + [("secondary_breakfast_per_day", 15001)]:
            self.assertEqual(
                ActivityScheduleCostLine.objects.filter(
                    activity__in=members, cost_setting_key=key
                ).aggregate(total=Sum("amount"))["total"],
                rate,
            )
        self.assertEqual(sum(planned_minimum_amounts(members).values()), 287001)

    def test_refresh_command_preserves_frozen_requests_and_only_applies_explicitly(
        self,
    ):
        from io import StringIO
        from django.core.management import call_command
        from apps.budget.models import ActivityCostSnapshot
        from apps.fund_requests.models import WeeklyFundRequest

        result = self._schedule(
            ["BATCH-P-1", "BATCH-P-2"], date(2026, 8, 10), reason="Two schools"
        )
        ids = [a["id"] for a in result["activities"]]
        for snapshot in ActivityCostSnapshot.objects.filter(
            activity_id__in=ids, is_current=True
        ):
            for line in snapshot.operational_breakdown:
                line.pop("dailyAllocation", None)
            snapshot.save(update_fields=["operational_breakdown"])
        before = ActivityCostSnapshot.objects.count()
        output = StringIO()
        call_command("refresh_daily_cost_allocations", stdout=output)
        self.assertIn("outdated=1", output.getvalue())
        self.assertEqual(ActivityCostSnapshot.objects.count(), before)
        WeeklyFundRequest.objects.filter(responsible_user=self.staff_user.id).update(
            status="submitted_to_pl"
        )
        call_command("refresh_daily_cost_allocations", apply=True, stdout=StringIO())
        self.assertEqual(ActivityCostSnapshot.objects.count(), before)
        WeeklyFundRequest.objects.filter(responsible_user=self.staff_user.id).update(
            status="pending_responsible_confirmation"
        )
        call_command("refresh_daily_cost_allocations", apply=True, stdout=StringIO())
        self.assertEqual(ActivityCostSnapshot.objects.count(), before + 2)
        current = ActivityCostSnapshot.objects.filter(
            activity_id__in=ids, is_current=True
        )
        self.assertTrue(
            all(
                line.get("dailyAllocation", {}).get("count") == 2
                for snapshot in current
                for line in snapshot.operational_breakdown
            )
        )

    def test_zero_operational_rate_still_splits_a_configured_minimum_exactly(self):
        from apps.budget.costing_service import planned_minimum_amounts

        CostSetting.objects.filter(key="primary_transport_per_day").update(
            unit_cost=0, approved_minimum=5
        )
        CostSetting.objects.filter(key="primary_lunch_per_day").update(
            unit_cost=0, approved_minimum=2
        )
        result = self._schedule(
            ["BATCH-P-1", "BATCH-P-2", "BATCH-P-3"], date(2026, 8, 10)
        )
        members = list(Activity.objects.filter(daily_visit_batch_id=result["batchId"]))
        self.assertEqual(sum(a.est_cost_cents for a in members), 0)
        self.assertEqual(sorted(planned_minimum_amounts(members).values()), [1, 3, 3])

    def test_preview_cannot_use_an_unrelated_staff_members_day(self):
        from apps.budget.costing_service import planning_preview_owner
        from apps.core.exceptions import Forbidden

        self.assertEqual(
            planning_preview_owner(self.staff_user, self.staff_profile.id),
            self.staff_user.id,
        )
        with self.assertRaises(Forbidden):
            planning_preview_owner(self.staff_user, "another-staff-profile")

    def test_cluster_drawer_preview_uses_the_selected_day_and_planned_headcount(self):
        CostSetting.objects.filter(key="primary_transport_per_day").update(
            approved_minimum=100000
        )
        CostSetting.objects.filter(key="primary_lunch_per_day").update(
            approved_minimum=20000
        )
        self._schedule(
            ["BATCH-P-1", "BATCH-P-2"], date(2026, 8, 10), reason="Two visits"
        )
        session = self._session("cluster_training", date(2026, 8, 11))
        self.client.force_login(self.staff_user)
        response = self.client.get(
            "/clusters/cost-preview",
            {
                "activity_type": "training",
                "cluster_id": session.cluster_id,
                "scheduled_date": "2026-08-10",
                "expected_participants": "12",
                "responsible_staff_id": self.staff_profile.id,
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["success"])
        self.assertEqual(response.context["preview"]["amount"], 135001)
        self.assertContains(response, "3 planned activities")
        self.assertNotContains(response, "280,000")

    def test_paid_transport_prevents_redistribution_into_a_staff_request(self):
        from apps.fund_requests.finance_models import TransportPayment

        day = date(2026, 8, 10)
        result = self._schedule(["BATCH-P-1"], day, reason="One visit")
        TransportPayment.objects.filter(batch_id=result["batchId"]).update(
            status="paid"
        )
        with self.assertRaisesMessage(BadRequest, "already been paid"):
            self._session("cluster_training", day)
        payment = TransportPayment.objects.get(batch_id=result["batchId"])
        self.assertEqual(payment.amount, 280000)
        self.assertEqual(payment.status, "paid")

    def test_returned_day_redistributes_the_share_of_deferred_work(self):
        from apps.daily_visit_batches.services import resync_stale_batches
        from apps.fund_requests.models import WeeklyFundRequest

        day = date(2026, 8, 10)
        result = self._schedule(["BATCH-P-1", "BATCH-P-2"], day, reason="Two schools")
        first, second = [item["id"] for item in result["activities"]]
        # A change made while finance was locked can leave the old batch link.
        Activity.objects.filter(id=first).update(status="deferred")
        self.assertEqual(
            resync_stale_batches(self.staff_user.id, day, date(2026, 8, 16)), 1
        )
        remaining = Activity.objects.get(id=second)
        self.assertEqual(remaining.est_cost_cents, 310000)
        self.assertEqual(remaining.daily_visit_batch.school_count, 1)
        self.assertEqual(
            WeeklyFundRequest.objects.get(
                responsible_user=self.staff_user.id, week_start_date=day
            ).total_amount,
            30000,
        )
