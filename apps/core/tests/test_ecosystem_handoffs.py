"""Ecosystem-audit regression tests (2026-07 full-platform handoff audit).

Each class pins one repaired handoff seam between features:
  - FY-blind SSA readiness poisoning planning/To-Dos
  - school-upload duplicate rows overwriting live schools
  - period FundRequest approval/reset/disbursement guards
  - cross-channel double disbursement (weekly vs advance vs period)
  - reschedule vs confirmed money + vacated-week regeneration
  - partner payment idempotency
  - core package completion counting terminal "closed" slots
  - Special Project assignment requiring verified SSA need or a reason
  - accepted debrief recommendations being discoverable by their owner
"""

from __future__ import annotations

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from freezegun import freeze_time

from apps.accounts.models import User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.enums import SsaIntervention
from apps.core.exceptions import BadRequest
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore


def _user(email: str, role: str) -> User:
    return User.objects.create_user(
        email=email,
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        password="password123",
        is_active=True,
    )


def _school(code: str, district: District) -> School:
    return School.objects.create(
        school_id=code,
        name=f"School {code}",
        region=district.region,
        district=district,
    )


def _ssa(school: School, fy: str, scores: dict | None = None, *, status="confirmed"):
    record = SsaRecord.objects.create(
        school=school,
        fy=fy,
        quarter="Q1",
        date_of_ssa=timezone.now(),
        verification_status=status,
    )
    for intervention in SsaIntervention:
        SsaScore.objects.create(
            ssa_record=record,
            intervention=intervention.value,
            score=(scores or {}).get(intervention.value, 5.0),
        )
    return record


def _cost_line(activity: Activity, amount: int, *, owner: str = "", planned=None):
    return ActivityScheduleCostLine.objects.create(
        activity=activity,
        school=activity.school,
        cost_setting_key="transport",
        label="Transport",
        line_item_type="transport",
        unit_cost=amount,
        quantity=1,
        amount=amount,
        responsible_user=owner,
        planned_date=planned,
    )


class SsaReadinessFyTest(TestCase):
    """current_fy_ssa_status must be FY-aware (Chain 1 HIGH 3.2)."""

    def setUp(self):
        region = Region.objects.create(name="Eco R1")
        self.district = District.objects.create(name="Eco D1", region=region)
        self.school = _school("ECO-FY1", self.district)
        self.fy = get_operational_fy()
        self.prev_fy = str(int(self.fy) - 1)

    def test_prior_fy_confirmed_ssa_does_not_mark_current_fy_done(self):
        from apps.ssa.services import _recompute_readiness

        _ssa(self.school, self.prev_fy)
        _recompute_readiness(self.school)
        self.school.refresh_from_db()
        self.assertNotEqual(self.school.current_fy_ssa_status, "done")

    def test_current_fy_confirmed_ssa_marks_done(self):
        from apps.ssa.services import _recompute_readiness

        _ssa(self.school, self.fy)
        _recompute_readiness(self.school)
        self.school.refresh_from_db()
        self.assertEqual(self.school.current_fy_ssa_status, "done")

    def test_stale_done_resets_when_no_current_fy_record(self):
        from apps.ssa.services import _recompute_readiness

        _ssa(self.school, self.prev_fy)
        self.school.current_fy_ssa_status = "done"  # legacy stale stamp
        self.school.save(update_fields=["current_fy_ssa_status"])
        _recompute_readiness(self.school)
        self.school.refresh_from_db()
        self.assertEqual(self.school.current_fy_ssa_status, "not_done")


class SchoolUploadDuplicateTest(TestCase):
    """Rows staged as "duplicate" must never be imported (Chain 1 HIGH 1.3)."""

    def test_duplicate_rows_do_not_overwrite_live_school(self):
        from apps.schools.models import SchoolImportBatch, SchoolImportRow
        from apps.schools.upload_service import import_school_batch

        region = Region.objects.create(name="Eco R2")
        district = District.objects.create(name="Eco D2", region=region)
        school = _school("ECO-DUP1", district)
        original_name = school.name

        batch = SchoolImportBatch.objects.create(
            file_name="dup.csv", uploaded_by="tester"
        )
        SchoolImportRow.objects.create(
            batch=batch,
            row_number=1,
            school_id="ECO-DUP1",
            name="OVERWRITTEN NAME",
            status="duplicate",
        )
        import_school_batch(batch, None)
        school.refresh_from_db()
        self.assertEqual(school.name, original_name)


class PeriodFundRequestGuardTest(TestCase):
    """Approval chain + resubmit + cross-channel guards (Chain 2 F4.2/F4.3/F4.5)."""

    def setUp(self):
        self.owner = _user("eco-owner@edify.test", EdifyRole.CCEO.value)
        self.reviewer = _user("eco-cd@edify.test", EdifyRole.COUNTRY_DIRECTOR.value)

    def _fund_request(self, status: str):
        from apps.fund_requests.models import FundRequest

        return FundRequest.objects.create(
            submitted_by_user_id=self.owner.id,
            submitted_by_role="CCEO",
            fy="2026",
            period="monthly",
            period_key="2026-M2",
            total_amount=50_000,
            activity_count=1,
            status=status,
        )

    def test_self_approval_blocked(self):
        from apps.fund_requests import services

        fr = self._fund_request("submitted")
        with self.assertRaises(BadRequest):
            services.approve(fr.id, {}, self.owner)

    def test_reviewer_approval_allowed_and_audited(self):
        from apps.audit.models import AuditLog
        from apps.fund_requests import services

        fr = self._fund_request("submitted")
        result = services.approve(fr.id, {}, self.reviewer)
        self.assertEqual(result["status"], "approved")
        self.assertTrue(
            AuditLog.objects.filter(
                action="fund_request.approved", subject_id=fr.id
            ).exists()
        )

    def test_disbursed_request_cannot_be_reapproved(self):
        from apps.fund_requests import services

        fr = self._fund_request("disbursed")
        with self.assertRaises(BadRequest):
            services.approve(fr.id, {}, self.reviewer)

    def test_resubmit_cannot_reset_approved_request(self):
        from apps.fund_requests import services

        self._fund_request("approved")
        with self.assertRaises(BadRequest):
            services.submit({"period": "monthly", "month": 2, "fy": "2026"}, self.owner)

    def test_disburse_blocked_when_advance_already_paid(self):
        from apps.fund_requests import services
        from apps.fund_requests.models import AdvanceRequest, FundRequestItem

        region = Region.objects.create(name="Eco R3")
        district = District.objects.create(name="Eco D3", region=region)
        school = _school("ECO-XCH1", district)
        activity = Activity.objects.create(
            school=school, activity_type="school_visit", status="scheduled", fy="2026"
        )
        line = _cost_line(activity, 40_000, owner=self.owner.id)
        AdvanceRequest.objects.create(
            activity=activity,
            budget_line=line,
            fy="2026",
            quarter="Q2",
            amount=40_000,
            status="disbursed",
            disbursed_amount=40_000,
        )
        fr = self._fund_request("approved")
        FundRequestItem.objects.create(
            fund_request=fr,
            activity_id=activity.id,
            activity_schedule_cost_line_id=line.id,
            amount=40_000,
            period="monthly",
            period_key="2026-M2",
        )
        with self.assertRaises(BadRequest):
            services.disburse(fr.id, {"amount": 40_000}, self.reviewer)


class WeeklyCrossChannelTest(TestCase):
    """Weekly disburse must refuse lines already paid elsewhere (F4.5)."""

    @freeze_time(
        "2026-08-03"
    )  # fixed Monday, matches hardcoded fy="2026" — REG-02 §1.1
    def test_weekly_disburse_blocked_when_child_advance_disbursed(self):
        from apps.fund_requests import weekly_service
        from apps.fund_requests.models import (
            AdvanceRequest,
            WeeklyFundRequest,
            WeeklyFundRequestLine,
        )

        owner = _user("eco-weekly@edify.test", EdifyRole.CCEO.value)
        accountant = _user("eco-acct@edify.test", EdifyRole.PROGRAM_ACCOUNTANT.value)
        region = Region.objects.create(name="Eco R4")
        district = District.objects.create(name="Eco D4", region=region)
        school = _school("ECO-WK1", district)
        activity = Activity.objects.create(
            school=school,
            activity_type="school_visit",
            status="scheduled",
            fy="2026",
            scheduled_date=timezone.now(),
        )
        line = _cost_line(
            activity, 30_000, owner=owner.id, planned=timezone.now().date()
        )
        AdvanceRequest.objects.create(
            activity=activity,
            budget_line=line,
            fy="2026",
            quarter="Q2",
            amount=30_000,
            status="disbursed",
            disbursed_amount=30_000,
        )
        week_start = timezone.now().date() - timedelta(
            days=timezone.now().date().weekday()
        )
        wfr = WeeklyFundRequest.objects.create(
            fy="2026",
            week_start_date=week_start,
            week_end_date=week_start + timedelta(days=6),
            responsible_user=owner.id,
            total_amount=30_000,
            status="confirmed_for_advance",
        )
        WeeklyFundRequestLine.objects.create(
            weekly_fund_request=wfr,
            activity_budget_line=line,
            line_item_type="transport",
            description="Transport",
            quantity=1,
            unit_cost=30_000,
            total_cost=30_000,
        )
        with self.assertRaises(BadRequest):
            weekly_service.disburse(wfr.id, {"amount": 30_000}, accountant)


class RescheduleFinanceSeamTest(TestCase):
    """Confirmed money freezes rescheduling; vacated week is regenerated (F5.1/F5.3)."""

    def test_confirmed_advance_blocks_reprice(self):
        from apps.budget.costing_service import apply_to_activity
        from apps.fund_requests.models import AdvanceRequest

        region = Region.objects.create(name="Eco R5")
        district = District.objects.create(name="Eco D5", region=region)
        school = _school("ECO-RS1", district)
        activity = Activity.objects.create(
            school=school,
            activity_type="school_visit",
            status="scheduled",
            fy="2026",
            scheduled_date=timezone.now(),
        )
        line = _cost_line(activity, 25_000)
        AdvanceRequest.objects.create(
            activity=activity,
            budget_line=line,
            fy="2026",
            quarter="Q2",
            amount=25_000,
            status="confirmed_for_advance",
        )
        with self.assertRaises(BadRequest):
            apply_to_activity(
                activity,
                {"activityType": "school_visit", "deliveryType": "staff"},
            )


class PartnerDoublePayTest(TestCase):
    """One payout per activity (Chain 3 P5c)."""

    def _paid_world(self):
        from apps.fund_requests.finance_models import PartnerPayment

        region = Region.objects.create(name="Eco R6")
        district = District.objects.create(name="Eco D6", region=region)
        school = _school("ECO-PP1", district)
        activity = Activity.objects.create(
            school=school,
            activity_type="partner_activity",
            status="ia_verified",
            fy="2026",
            delivery_type="partner",
            evidence_status="accepted",
            salesforce_activity_id="SVE-ECO-1",
            ia_verification_status="confirmed",
        )
        _cost_line(activity, 60_000)
        PartnerPayment.objects.create(
            activity=activity,
            partner_name="Partner Eco",
            amount_paid=60_000,
            payment_method="bank",
            payment_reference="REF-ECO-1",
            paid_by="acct",
        )
        return activity

    def test_second_pay_partner_raises(self):
        from apps.fund_requests.finance_services import PartnerPaymentService

        activity = self._paid_world()
        with self.assertRaises(ValueError):
            PartnerPaymentService.pay_partner(
                activity,
                "Partner Eco",
                60_000,
                "bank",
                "REF-ECO-2",
                "acct",
                netsuite_id="NS-ECO-1",
            )

    def test_db_constraint_blocks_duplicate_row(self):
        from apps.fund_requests.finance_models import PartnerPayment

        activity = self._paid_world()
        with self.assertRaises(IntegrityError), transaction.atomic():
            PartnerPayment.objects.create(
                activity=activity,
                partner_name="Partner Eco",
                amount_paid=60_000,
                payment_method="bank",
                payment_reference="REF-ECO-3",
                paid_by="acct",
            )


class CoreClosedStatusTest(TestCase):
    """Terminal "closed" slots count toward package completion (Chain 5 C6a)."""

    def test_closed_slot_counts_in_completion(self):
        from apps.core_schools.models import CoreActivitySlot, CorePlan, cslot_id
        from apps.core_schools.services import resync_plan_completion

        region = Region.objects.create(name="Eco R7")
        district = District.objects.create(name="Eco D7", region=region)
        school = _school("ECO-CORE1", district)
        plan = CorePlan.objects.create(
            id="ecoplan1", school_id=school.school_id, fy="2026", status="Active"
        )
        CoreActivitySlot.objects.create(
            id=cslot_id(school.school_id, "v", 1),
            core_plan=plan,
            school_id=school.school_id,
            intervention="leadership",
            activity_type="visit",
            sequence_number=1,
            status="closed",
        )
        resync_plan_completion(plan)
        plan.refresh_from_db()
        self.assertEqual(plan.visits_completed, 1)


class ProjectNeedGateTest(TestCase):
    """Special Project assignment uses verified SSA need or a reason (Chain 4 H2)."""

    def setUp(self):
        from apps.projects.models import Project

        region = Region.objects.create(name="Eco R8")
        self.district = District.objects.create(name="Eco D8", region=region)
        self.project = Project.objects.create(
            name="Leadership Project",
            category="intervention_specific",
            target_interventions=["leadership"],
        )
        self.fy = get_operational_fy()

    def test_strong_school_requires_reason(self):
        from apps.projects.services import assign_school

        school = _school("ECO-PRJ1", self.district)
        _ssa(school, self.fy, {"leadership": 9.0})
        with self.assertRaises(BadRequest):
            assign_school(self.project.id, {"schoolId": school.school_id})

        result = assign_school(
            self.project.id,
            {"schoolId": school.school_id, "reason": "Donor-mandated pilot site"},
        )
        self.assertTrue(result["ok"])
        assignment = self.project.school_assignments.get(school=school)
        self.assertEqual(assignment.assignment_reason, "Donor-mandated pilot site")

    def test_weak_school_assigns_without_reason(self):
        from apps.projects.services import assign_school

        school = _school("ECO-PRJ2", self.district)
        _ssa(school, self.fy, {"leadership": 4.0})
        result = assign_school(self.project.id, {"schoolId": school.school_id})
        self.assertTrue(result["ok"])
        assignment = self.project.school_assignments.get(school=school)
        self.assertEqual(assignment.matched_intervention, "leadership")


class AcceptRecommendationDiscoverabilityTest(TestCase):
    """Accepted debrief follow-ups must be schedulable drafts, not invisible
    not_planned rows (Chain 7 T8)."""

    def test_follow_up_is_planned_with_quarter(self):
        from apps.debriefs.field_debrief_service import FieldDebriefService
        from apps.debriefs.models import DailyDebrief

        admin = _user("eco-admin@edify.test", EdifyRole.ADMIN.value)
        region = Region.objects.create(name="Eco R9")
        district = District.objects.create(name="Eco D9", region=region)
        school = _school("ECO-DBR1", district)
        debrief = DailyDebrief.objects.create(
            fy=get_operational_fy(),
            date=timezone.now(),
            submitted_at=timezone.now(),
            submitted_by_user_id=admin.id,
            debrief_type="staff",
            kind="activity",
            status="submitted",
            title="Eco debrief",
            linked_school_ids=[school.id],
            recommended_next_activity_type="follow_up_visit",
            recommended_intervention="leadership",
            recommendation_status="proposed",
            follow_up_date=timezone.now().date() + timedelta(days=7),
        )
        activity = FieldDebriefService.accept_recommendation(admin, debrief.id)
        self.assertEqual(activity.status, "planned")
        self.assertTrue(activity.quarter)
        self.assertEqual(activity.focus_intervention, "leadership")
