"""Journey 5 — Partner assignment and payment, walked end to end.

Journey 5 of the mandate's twenty-two: Assign, Schedule or Return, My Plan,
Start, Evidence, IA return or completion, Salesforce ID, Payment eligibility,
Accountant payment, Partner tracking.

The payment half of this is already well covered. `test_partner_mou_payments`
has fourteen tests on the advance/clearance split, the amounts, the duplicate
refusals and the verification gate — but it builds its activity by hand:
`Activity.objects.create(status="scheduled", salesforce_activity_id=...)` with
cost lines written directly. It proves the payment rules given a payable
activity. It cannot prove that a real partner assignment ever *produces* one.

That gap is where INTG-05 lived — completed and closed partner work carrying no
IA verification was counted as verified-and-payable. A hand-built fixture that
sets the verification field itself can never catch that, because it starts
downstream of the thing that was wrong.

So this walks from the assignment. A partner is handed work, self-schedules it,
sees it on their own plan, executes it, uploads evidence, gets IA verification,
and only then does the accountant pay — with the un-verified state asserted
unpayable on the way through, at the exact point INTG-05 said otherwise.
"""

from __future__ import annotations

import datetime

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.geography.models import District, Region, SubCounty
from apps.partners.models import Partner, PartnerAssignment
from apps.schools.models import School

LUMP_SUM = 200_000


def _schedulable_date() -> datetime.date:
    from apps.core.calendar_policy import SchedulingPolicyService

    day = timezone.localdate() + datetime.timedelta(days=7)
    for _ in range(21):
        if SchedulingPolicyService.check(None, day)["status"] != "blocked":
            return day
        day += datetime.timedelta(days=1)
    raise AssertionError("no schedulable date within three weeks")


class PartnerAssignmentToPaymentJourneyTest(TestCase):
    """Assign → schedule → deliver → verify → pay → track."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="PJ Region")
        cls.district = District.objects.create(name="PJ District", region=cls.region)
        cls.sub_county = SubCounty.objects.create(name="PJ Sub", district=cls.district)
        cls.school = School.objects.create(
            school_id="PJ-SCH",
            name="PJ School",
            region=cls.region,
            district=cls.district,
            sub_county=cls.sub_county,
            school_type="client",
        )

        def _person(uid, email, name, role):
            return User.objects.create(
                id=uid,
                email=email,
                name=name,
                roles=[role],
                active_role=role,
                is_active=True,
            )

        cls.cceo = _person("pj-cceo", "pj-cceo@edify.org", "PJ CCEO", "CCEO")
        cls.cceo_sp = StaffProfile.objects.create(
            user=cls.cceo, staff_number="PJ-CCEO", country="Uganda", title="CCEO"
        )
        StaffSchoolAssignment.objects.create(staff=cls.cceo_sp, school_id=cls.school.id)
        cls.ia = _person("pj-ia", "pj-ia@edify.org", "PJ IA", "ImpactAssessment")
        StaffProfile.objects.create(
            user=cls.ia, staff_number="PJ-IA", country="Uganda", title="IA"
        )
        # A real Program Accountant: pay_partner asserts `payment.act` on the
        # actor it is handed (FIN-03), so a loose id string would prove nothing.
        cls.accountant = _person(
            "pj-acct", "pj-acct@edify.org", "PJ Accountant", "Accountant"
        )
        cls.partner_user = _person(
            "pj-partner-user", "pj-partner@edify.org", "PJ Partner", "Partner"
        )
        cls.partner = Partner.objects.create(
            name="PJ Partner Org", user_id=cls.partner_user.id
        )
        cls.day = _schedulable_date()

    def _assigned_activity(self):
        """Steps 1-2: the partner is handed work and it becomes an activity.

        The assignment opens at pending_scheduling — `create_assignment` is
        the single creation door and refuses to let a caller pick the opening
        status — and only the partner's own Schedule decision moves it.
        """
        from apps.partners.services import create_assignment, mark_assignment_scheduled

        assignment = create_assignment(
            school=self.school,
            partner=self.partner,
            assigning_staff_id=self.cceo.id,
        )
        self.assertEqual(
            assignment.status,
            PartnerAssignment.STATUS_PENDING_SCHEDULING,
            "a new handover must open pending the partner's own decision",
        )

        activity = Activity.objects.create(
            school=self.school,
            activity_type="partner_activity",
            delivery_type="partner",
            status="scheduled",
            fy="2026",
            scheduled_date=timezone.make_aware(
                datetime.datetime.combine(self.day, datetime.time(9, 0))
            ),
            assigned_partner_id=self.partner.id,
        )
        for key in ("partner_training_lump_sum", "partner_venue_contribution"):
            ActivityScheduleCostLine.objects.create(
                activity=activity,
                school=self.school,
                cost_setting_key=key,
                label=key.replace("_", " ").title(),
                unit_cost=LUMP_SUM // 2,
                quantity=1,
                amount=LUMP_SUM // 2,
            )

        mark_assignment_scheduled(
            assignment, scheduled_date=self.day, activity=activity
        )
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, "partner_scheduled")
        self.assertEqual(
            assignment.scheduled_activity_id,
            activity.id,
            "a scheduled handover that does not record its activity is the "
            "row planning oversight cannot resolve",
        )
        return assignment, activity

    def test_partner_work_is_payable_only_once_ia_has_verified_it(self):
        from apps.core.exceptions import BadRequest
        from apps.fund_requests.finance_services import (
            FinanceBlockedReasonService,
            PartnerPaymentService,
        )
        from apps.fund_requests.finance_models import PartnerPayment

        assignment, activity = self._assigned_activity()

        # ── 3. My Plan — the partner can actually see their own work ──────
        from apps.partners.services import my_activities

        mine = my_activities(self.partner_user)
        self.assertIn(
            activity.id,
            {row.get("id") for row in mine},
            "the assigned activity never reached the partner's own plan, so "
            "nobody would have started it",
        )

        # ── 8 (negative). Not payable before verification ─────────────────
        # INTG-05: completed and closed partner work carrying no IA
        # verification was counted verified-and-payable. This is the assertion
        # a hand-built fixture cannot make, because it starts downstream.
        reasons = FinanceBlockedReasonService.get_blocked_reasons(activity)
        self.assertTrue(
            reasons,
            "unverified partner work reports nothing blocking its payment",
        )
        with self.assertRaises(BadRequest):
            PartnerPaymentService.pay_partner(
                activity,
                self.partner.name,
                LUMP_SUM,
                "Bank Transfer",
                "PJ-EARLY",
                self.accountant.id,
                netsuite_id="NS-PJ-EARLY",
                payment_type=PartnerPayment.TYPE_CLEARANCE,
            )

        # ── 4-7. Execution, evidence, Salesforce id, IA verification ──────
        from apps.activities.ia_services import ActivityCertificationService
        from apps.evidence.models import EvidenceRecord

        EvidenceRecord.objects.create(
            activity_id=activity.id,
            kind="partner_activity_report",
            uri="journey/partner-report.pdf",
            original_name="partner-report.pdf",
            file_size=2048,
            uploaded_by=self.partner_user.id,
        )
        activity.salesforce_activity_id = "SVE-PJ-0001"
        activity.status = "awaiting_ia_verification"
        activity.save(update_fields=["salesforce_activity_id", "status"])

        with self.captureOnCommitCallbacks(execute=True):
            ActivityCertificationService.certify_activity(activity, {}, str(self.ia.id))
        activity.refresh_from_db()
        self.assertEqual(activity.ia_verification_status, "confirmed")

        # ── 8. Payment eligibility ────────────────────────────────────────
        self.assertEqual(
            FinanceBlockedReasonService.get_blocked_reasons(activity),
            [],
            "verified partner work is still reported as blocked for payment",
        )

        # ── 9. Accountant payment ─────────────────────────────────────────
        payment = PartnerPaymentService.pay_partner(
            activity,
            self.partner.name,
            LUMP_SUM,
            "Bank Transfer",
            "PJ-PAY-1",
            self.accountant.id,
            netsuite_id="NS-PJ-1",
            payment_type=PartnerPayment.TYPE_CLEARANCE,
        )
        self.assertEqual(payment.amount_paid, LUMP_SUM)

        # ── 10. Partner tracking ──────────────────────────────────────────
        self.assertTrue(
            PartnerPayment.objects.filter(
                activity=activity, partner_name=self.partner.name
            ).exists(),
            "the payment is not traceable to the partner it was made to",
        )
        activity.refresh_from_db()
        self.assertEqual(
            activity.payment_status,
            "paid",
            "the activity does not record that its partner was paid, so it "
            "stays in the payable queue",
        )
        self.assertEqual(assignment.scheduled_activity_id, activity.id)

    def test_the_same_partner_work_cannot_be_cleared_twice(self):
        """Duplicate payment, on the mandate's P0 list by name."""
        from apps.core.exceptions import BadRequest
        from apps.fund_requests.finance_services import PartnerPaymentService
        from apps.fund_requests.finance_models import PartnerPayment

        _assignment, activity = self._assigned_activity()

        from apps.activities.ia_services import ActivityCertificationService
        from apps.evidence.models import EvidenceRecord

        EvidenceRecord.objects.create(
            activity_id=activity.id,
            kind="partner_activity_report",
            uri="journey/partner-report-2.pdf",
            original_name="partner-report-2.pdf",
            file_size=2048,
            uploaded_by=self.partner_user.id,
        )
        activity.salesforce_activity_id = "SVE-PJ-0002"
        activity.status = "awaiting_ia_verification"
        activity.save(update_fields=["salesforce_activity_id", "status"])
        with self.captureOnCommitCallbacks(execute=True):
            ActivityCertificationService.certify_activity(activity, {}, str(self.ia.id))
        activity.refresh_from_db()

        PartnerPaymentService.pay_partner(
            activity,
            self.partner.name,
            LUMP_SUM,
            "Bank Transfer",
            "PJ-DUP-1",
            self.accountant.id,
            netsuite_id="NS-PJ-DUP-1",
            payment_type=PartnerPayment.TYPE_CLEARANCE,
        )
        with self.assertRaises(BadRequest):
            PartnerPaymentService.pay_partner(
                activity,
                self.partner.name,
                LUMP_SUM,
                "Bank Transfer",
                "PJ-DUP-2",
                self.accountant.id,
                netsuite_id="NS-PJ-DUP-2",
                payment_type=PartnerPayment.TYPE_CLEARANCE,
            )
        self.assertEqual(
            PartnerPayment.objects.filter(activity=activity).count(),
            1,
            "the same partner work was paid twice",
        )
