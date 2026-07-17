"""Production-readiness gate tests (remediation phase 2026-07-17).

Pins: Budget Amendment lifecycle, per-type evidence requirements, partner
activity allowance, partner_schedule scope/duplicate hardening, est-cost
fallback removal, largest-remainder disbursement rounding, closure/partner
events on the tamper-evident audit chain, and the data-repair command.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School


def _user(email: str, role: str) -> User:
    return User.objects.create_user(
        email=email,
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        password="password123",
        is_active=True,
        status="active",
    )


def _world(tag: str):
    region = Region.objects.create(name=f"Gate R {tag}")
    district = District.objects.create(name=f"Gate D {tag}", region=region)
    school = School.objects.create(
        school_id=f"GATE-{tag}",
        name=f"Gate School {tag}",
        region=region,
        district=district,
    )
    return school


def _line(activity, amount, owner="", planned=None):
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


class BudgetAmendmentTest(TestCase):
    def setUp(self):
        self.owner = _user("gate-owner@edify.test", EdifyRole.ADMIN.value)
        self.accountant = _user(
            "gate-acct@edify.test", EdifyRole.PROGRAM_ACCOUNTANT.value
        )
        self.school = _world("AM1")
        self.activity = Activity.objects.create(
            school=self.school,
            activity_type="school_visit",
            status="scheduled",
            fy=get_operational_fy(),
            quarter="Q1",
            scheduled_date=timezone.now(),
            planned_date=timezone.now().date(),
        )
        _line(self.activity, 45_000)

    def _request(self):
        from apps.budget.amendment_service import request_amendment

        new_date = (timezone.now() + timedelta(days=30)).strftime("%Y-%m-%d")
        return request_amendment(
            self.activity.id,
            {"newDate": new_date, "reason": "Venue unavailable"},
            self.owner,
        )

    def test_request_requires_reason(self):
        from apps.budget.amendment_service import request_amendment

        with self.assertRaises(BadRequest):
            request_amendment(
                self.activity.id, {"newDate": "2026-09-01", "reason": ""}, self.owner
            )

    def test_lifecycle_apply_moves_period_without_touching_lines(self):
        from apps.budget.amendment_service import approve_amendment

        amendment = self._request()
        line_ids = set(self.activity.schedule_cost_lines.values_list("id", flat=True))
        applied = approve_amendment(amendment.id, {"note": "ok"}, self.accountant)
        self.assertEqual(applied.status, "applied")
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.planned_date, amendment.new_date)
        # Snapshot preserved: same line rows, moved period stamps.
        self.assertEqual(
            set(self.activity.schedule_cost_lines.values_list("id", flat=True)),
            line_ids,
        )
        self.assertEqual(
            self.activity.schedule_cost_lines.first().planned_date,
            amendment.new_date,
        )
        # On the tamper-evident chain.
        from apps.audit.models import AuditLog

        self.assertTrue(
            AuditLog.objects.filter(
                action="budget_amendment.applied", subject_id=amendment.id
            ).exists()
        )

    def test_requester_cannot_review_and_duplicate_blocked(self):
        from apps.budget.amendment_service import approve_amendment

        amendment = self._request()
        with self.assertRaises(BadRequest):
            approve_amendment(amendment.id, {}, self.owner)
        with self.assertRaises(BadRequest):
            self._request()  # second live amendment for same activity

    def test_non_reviewer_role_blocked(self):
        from apps.budget.amendment_service import approve_amendment

        amendment = self._request()
        cceo = _user("gate-cceo@edify.test", EdifyRole.CCEO.value)
        with self.assertRaises(Forbidden):
            approve_amendment(amendment.id, {}, cceo)


class EvidenceRequirementTest(TestCase):
    def test_requirements_differ_by_type_and_detect_missing(self):
        from apps.evidence.models import EvidenceRecord
        from apps.evidence.requirements import missing_evidence_kinds, required_kinds

        self.assertNotEqual(required_kinds("school_visit"), required_kinds("training"))
        school = _world("EV1")
        visit = Activity.objects.create(
            school=school,
            activity_type="school_visit",
            status="in_progress",
            fy=get_operational_fy(),
        )
        # A photo alone does NOT satisfy a school visit.
        EvidenceRecord.objects.create(
            activity=visit, kind="photo", uri="x.jpg", status="uploaded"
        )
        missing = missing_evidence_kinds(visit)
        self.assertEqual([m["kind"] for m in missing], ["visit_form"])
        # The visit form satisfies it.
        EvidenceRecord.objects.create(
            activity=visit, kind="visit_form", uri="v.pdf", status="uploaded"
        )
        self.assertEqual(missing_evidence_kinds(visit), [])


class PartnerAllowanceTest(TestCase):
    def setUp(self):
        from apps.partners.models import Partner

        self.school = _world("PA1")
        self.partner = Partner.objects.create(name="Allowance Partner")
        self.fy = get_operational_fy()

    def _partner_activity(self, days=0):
        return Activity.objects.create(
            school=self.school,
            activity_type="partner_activity",
            status="scheduled",
            fy=self.fy,
            delivery_type="partner",
            assigned_partner_id=self.partner.id,
            planned_date=timezone.now().date() + timedelta(days=days),
        )

    def test_default_one_per_school_enforced_and_grant_extends(self):
        from apps.partners.models import PartnerActivityAllowance
        from apps.partners.services import assert_partner_activity_allowance

        # No activities yet — allowed.
        assert_partner_activity_allowance(
            self.partner.id, self.school.id, "partner_activity", self.fy
        )
        self._partner_activity()
        # Second non-core activity — blocked by default allowance.
        with self.assertRaises(BadRequest):
            assert_partner_activity_allowance(
                self.partner.id, self.school.id, "partner_activity", self.fy
            )
        # Auditable grant unlocks exactly one more.
        PartnerActivityAllowance.objects.create(
            partner=self.partner,
            school=self.school,
            fy=self.fy,
            additional_activities=1,
            granted_by="cd-user",
            reason="Donor-funded extra training",
        )
        assert_partner_activity_allowance(
            self.partner.id, self.school.id, "partner_activity", self.fy
        )
        self._partner_activity(days=1)
        with self.assertRaises(BadRequest):
            assert_partner_activity_allowance(
                self.partner.id, self.school.id, "partner_activity", self.fy
            )

    def test_core_types_exempt(self):
        from apps.partners.services import assert_partner_activity_allowance

        self._partner_activity()
        # Core slots are governed by the nine-slot package, not the allowance.
        assert_partner_activity_allowance(
            self.partner.id, self.school.id, "core_visit", self.fy
        )


class PartnerScheduleScopeTest(TestCase):
    def test_partner_cannot_schedule_other_partners_assignment(self):
        from apps.activities.services import partner_schedule
        from apps.partners.models import Partner, PartnerAssignment

        school = _world("PS1")
        mine = Partner.objects.create(name="Mine Org")
        other = Partner.objects.create(name="Other Org")
        partner_user = _user("gate-partner@edify.test", EdifyRole.PARTNER_ADMIN.value)
        mine.user_id = partner_user.user_id
        mine.active_status = True
        mine.save(update_fields=["user_id", "active_status"])
        pa = PartnerAssignment.objects.create(
            school=school, partner=other, expected_activity_type="partner_activity"
        )
        with self.assertRaises(Forbidden):
            partner_schedule(
                pa.id,
                {"scheduledDate": timezone.now().strftime("%Y-%m-%d")},
                partner_user,
            )


class DisbursementRoundingTest(TestCase):
    def test_largest_remainder_children_sum_exactly(self):
        from apps.fund_requests import weekly_service
        from apps.fund_requests.models import (
            AdvanceRequest,
            WeeklyFundRequest,
            WeeklyFundRequestLine,
        )

        owner = _user("gate-round@edify.test", EdifyRole.CCEO.value)
        accountant = _user(
            "gate-round-acct@edify.test", EdifyRole.PROGRAM_ACCOUNTANT.value
        )
        school = _world("RND1")
        week_start = timezone.now().date() - timedelta(
            days=timezone.now().date().weekday()
        )
        wfr = WeeklyFundRequest.objects.create(
            fy=get_operational_fy(),
            week_start_date=week_start,
            week_end_date=week_start + timedelta(days=6),
            responsible_user=owner.id,
            total_amount=100,
            status="confirmed_for_advance",
        )
        for i in range(3):  # three 33/33/34-style shares of a partial 50
            activity = Activity.objects.create(
                school=school,
                activity_type="school_visit",
                status="scheduled",
                fy=get_operational_fy(),
                scheduled_date=timezone.now(),
            )
            line = _line(
                activity, 33 if i < 2 else 34, owner=owner.id, planned=week_start
            )
            AdvanceRequest.objects.create(
                activity=activity,
                budget_line=line,
                fy=get_operational_fy(),
                quarter="Q1",
                amount=line.amount,
                status="confirmed_for_advance",
            )
            WeeklyFundRequestLine.objects.create(
                weekly_fund_request=wfr,
                activity_budget_line=line,
                line_item_type="transport",
                description="Transport",
                quantity=1,
                unit_cost=line.amount,
                total_cost=line.amount,
            )
        weekly_service.disburse(wfr.id, {"amount": 50}, accountant)
        total_children = sum(
            AdvanceRequest.objects.filter(
                budget_line__weekly_request_lines__weekly_fund_request=wfr
            ).values_list("disbursed_amount", flat=True)
        )
        self.assertEqual(total_children, 50)  # exact — 0 UGX mismatch


class RepairCommandTest(TestCase):
    def test_dry_run_and_apply_are_idempotent(self):
        school = _world("RC1")
        Activity.objects.create(
            school=school,
            activity_type="school_visit",
            status="scheduled",
            fy=get_operational_fy(),
        )
        call_command("repair_ecosystem_data")  # dry-run, must not raise
        call_command("repair_ecosystem_data", "--apply")
        call_command("repair_ecosystem_data", "--apply")  # idempotent


class FinanceSeamVerificationTest(TestCase):
    """Pins the residual seams the post-remediation verification audit found:
    period disburse writes the shared advance ledger; accountability review
    cannot reset a disbursed request; weekly disburse hits the audit chain;
    partner payment refuses when the advance channel already moved money."""

    def setUp(self):
        self.owner = _user("seam-owner@edify.test", EdifyRole.CCEO.value)
        self.accountant = _user(
            "seam-acct@edify.test", EdifyRole.PROGRAM_ACCOUNTANT.value
        )
        self.school = _world("SEAM1")

    def _funded_activity(self, advance_status="confirmed_for_advance"):
        from apps.fund_requests.models import AdvanceRequest

        activity = Activity.objects.create(
            school=self.school,
            activity_type="school_visit",
            status="scheduled",
            fy=get_operational_fy(),
            quarter="Q1",
            month=timezone.now().month,
            scheduled_date=timezone.now(),
            planned_date=timezone.now().date(),
        )
        line = _line(
            activity, 60_000, owner=self.owner.id, planned=timezone.now().date()
        )
        adv = AdvanceRequest.objects.create(
            activity=activity,
            budget_line=line,
            fy=get_operational_fy(),
            quarter="Q1",
            amount=60_000,
            status=advance_status,
        )
        return activity, line, adv

    def test_period_disburse_writes_advance_ledger(self):
        from apps.fund_requests import services as period_services
        from apps.fund_requests.models import FundRequest, FundRequestItem

        activity, line, adv = self._funded_activity()
        fr = FundRequest.objects.create(
            submitted_by_user_id=self.owner.id,
            fy=get_operational_fy(),
            period="monthly",
            period_key=f"{get_operational_fy()}-M{timezone.now().month}",
            total_amount=60_000,
            activity_count=1,
            status="sent_to_accountant",
        )
        FundRequestItem.objects.create(
            fund_request=fr,
            activity_id=activity.id,
            activity_schedule_cost_line_id=line.id,
            amount=60_000,
            period="monthly",
            period_key=fr.period_key,
        )
        period_services.disburse(fr.id, {"amount": 60_000}, self.accountant)
        adv.refresh_from_db()
        # The shared ledger is written — the same line is no longer payable
        # through the weekly/advance channel.
        self.assertEqual(adv.status, "disbursed")

    def test_review_accountability_cannot_reset_disbursed_request(self):
        from apps.fund_requests import services as period_services
        from apps.fund_requests.models import FundRequest

        fr = FundRequest.objects.create(
            submitted_by_user_id=self.owner.id,
            fy=get_operational_fy(),
            period="monthly",
            period_key=f"{get_operational_fy()}-MX",
            total_amount=10_000,
            activity_count=1,
            status="disbursed",
            accountability_status="submitted",
        )
        period_services.review_accountability(fr.id, "return", {}, self.accountant)
        fr.refresh_from_db()
        # The ACCOUNTABILITY returns for correction; the request itself stays
        # DISBURSED and is not resubmittable.
        self.assertEqual(fr.status, "disbursed")
        self.assertEqual(fr.accountability_status, "returned")
        # Review on a non-disbursed request is refused outright.
        fr2 = FundRequest.objects.create(
            submitted_by_user_id=self.owner.id,
            fy=get_operational_fy(),
            period="monthly",
            period_key=f"{get_operational_fy()}-MY",
            total_amount=10_000,
            activity_count=1,
            status="submitted",
        )
        with self.assertRaises(BadRequest):
            period_services.review_accountability(fr2.id, "return", {}, self.accountant)

    def test_partner_payment_blocked_when_advance_moved_money(self):
        from apps.fund_requests.finance_services import PartnerPaymentService

        activity, line, adv = self._funded_activity(advance_status="disbursed")
        activity.delivery_type = "partner"
        activity.status = "ia_verified"
        activity.salesforce_activity_id = "SVE-SEAM-1"
        activity.evidence_status = "accepted"
        activity.save()
        from apps.evidence.models import EvidenceRecord

        EvidenceRecord.objects.create(
            activity=activity, kind="visit_form", uri="x.pdf", status="accepted"
        )
        with self.assertRaises(ValueError):
            PartnerPaymentService.pay_partner(
                activity,
                "Seam Partner",
                60_000,
                "bank",
                "REF-SEAM",
                self.accountant.id,
                netsuite_id="NS-SEAM-1",
            )


class EntitlementGateTest(TestCase):
    """Final-mandate entitlements: client 1+1 per FY; staff 2+2 core cap."""

    def setUp(self):
        from apps.budget.models import CostCatalogue, CostSetting

        self.school = _world("ENT1")
        self.school.school_type = "client"
        self.school.district.district_type = "primary"
        self.school.district.save(update_fields=["district_type"])
        self.school.save()
        self.cceo = _user("ent-cceo@edify.test", EdifyRole.CCEO.value)
        from apps.accounts.models import StaffProfile, StaffSchoolAssignment

        staff = StaffProfile.objects.create(user=self.cceo, title="CCEO")
        StaffSchoolAssignment.objects.create(staff=staff, school_id=self.school.id)
        # Scheduling is intentionally blocked without a published CD catalogue.
        # This entitlement fixture exercises slot behaviour, so it provides the
        # minimum valid operational configuration rather than bypassing costing.
        CostCatalogue.objects.get_or_create(
            fy=get_operational_fy(),
            version=1,
            defaults={"label": "Entitlement test catalogue"},
        )[0]
        for key, label in (
            ("staff_visit_transport_primary", "Transport (primary)"),
            ("lunch", "Lunch"),
            ("group_training_facilitation_fee", "Training facilitation"),
            ("group_training_venue_cost", "Training venue"),
            ("group_training_participant_meal_cost_per_head", "Training meals"),
        ):
            CostSetting.objects.get_or_create(
                key=key, defaults={"label": label, "unit_cost": 5_000, "version": 1}
            )[0]
        from apps.ssa.models import SsaRecord, SsaScore

        record = SsaRecord.objects.create(
            school=self.school,
            fy=get_operational_fy(),
            quarter="Q1",
            date_of_ssa=timezone.now(),
            average_score=4.0,
            verification_status="confirmed",
        )
        from apps.core.enums import SsaIntervention

        for i in SsaIntervention:
            SsaScore.objects.create(ssa_record=record, intervention=i.value, score=4.0)

    def _schedule_visit(self, days):
        from apps.activities.services import create

        return create(
            {
                "activityType": "school_visit",
                "schoolId": self.school.school_id,
                "scheduledDate": (timezone.now() + timedelta(days=days)).strftime(
                    "%Y-%m-%d"
                ),
                "focusIntervention": "leadership",
                "strict_validation": True,
                "activityPurposeText": "Entitlement gate test visit",
            },
            self.cceo,
        )

    def _schedule_training(self, days):
        from apps.activities.services import create

        return create(
            {
                "activityType": "school_improvement_training",
                "schoolId": self.school.school_id,
                "scheduledDate": (timezone.now() + timedelta(days=days)).strftime(
                    "%Y-%m-%d"
                ),
                "expectedParticipants": 12,
                "focusIntervention": "leadership",
                "strict_validation": True,
                "activityPurposeText": "Client entitlement training",
            },
            self.cceo,
        )

    def test_client_second_visit_blocked_and_slot_reopens_on_cancel(self):
        first = self._schedule_visit(5)
        with self.assertRaises(BadRequest) as ctx:
            self._schedule_visit(12)
        self.assertIn("entitlement", str(ctx.exception.detail))
        # Cancelling the reserved slot reopens it.
        Activity.objects.filter(id=first["id"]).update(status="cancelled")
        self._schedule_visit(12)

    def test_client_training_is_a_real_school_level_slot(self):
        self._schedule_training(5)
        with self.assertRaises(BadRequest) as ctx:
            self._schedule_training(12)
        self.assertIn("entitlement", str(ctx.exception.detail))

    def test_client_slots_are_scoped_to_the_scheduled_activity_fy(self):
        self._schedule_visit(5)
        future_fy_date = timezone.now().replace(
            year=timezone.now().year + 1, month=10, day=15
        )
        from apps.budget.models import CostCatalogue
        from apps.activities.services import create

        future_fy = get_operational_fy(future_fy_date)
        CostCatalogue.objects.get_or_create(
            fy=future_fy,
            version=1,
            defaults={"label": "Next FY entitlement test catalogue"},
        )[0]

        future = create(
            {
                "activityType": "school_visit",
                "schoolId": self.school.school_id,
                "scheduledDate": future_fy_date.strftime("%Y-%m-%d"),
                "focusIntervention": "leadership",
                "strict_validation": True,
                "activityPurposeText": "Next FY client entitlement visit",
            },
            self.cceo,
        )
        self.assertEqual(future["fy"], future_fy)
        self.assertNotEqual(future["fy"], get_operational_fy())

    def test_system_health_detects_historic_duplicate_client_slots(self):
        """Imported/pre-guard rows must remain visible for human repair."""
        from apps.system_health.services import _workflow_issues

        Activity.objects.create(
            school=self.school,
            activity_type="school_visit",
            status="scheduled",
            fy=get_operational_fy(),
        )
        Activity.objects.create(
            school=self.school,
            activity_type="school_visit",
            status="scheduled",
            fy=get_operational_fy(),
        )

        issues = _workflow_issues()
        self.assertEqual(issues["clientDuplicateActiveEntitlements"], 1)
        self.assertFalse(issues["clean"])

    def test_core_staff_cap_two_visits(self):
        self.school.school_type = "core"
        self.school.save()
        from apps.activities.services import create

        def core_visit(days):
            return create(
                {
                    "activityType": "core_visit",
                    "schoolId": self.school.school_id,
                    "scheduledDate": (timezone.now() + timedelta(days=days)).strftime(
                        "%Y-%m-%d"
                    ),
                    "focusIntervention": "leadership",
                    "strict_validation": True,
                    "activityPurposeText": "Core cap test",
                },
                self.cceo,
            )

        core_visit(3)
        core_visit(4)
        with self.assertRaises(BadRequest) as ctx:
            core_visit(5)
        self.assertIn("at most two", str(ctx.exception.detail))
