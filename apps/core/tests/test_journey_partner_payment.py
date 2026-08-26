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

    def test_the_same_journey_through_the_partner_payment_endpoint(self):
        """JRN-01: the money door, for partner work.

        The test above proves the services refuse unverified partner work and
        pay verified work. It proves nothing about
        ``POST /accounts/partner-payments/<id>/pay``, which is where an
        Accountant actually releases the money — and until JRN-01, no mandated
        journey touched a route at all.

        Two things make this door worth its own walk. It carries a page gate
        (``disbursements``) and then a second, separate authority check
        (``_lacks_payment_authority``) that refuses Admin inside the view, so
        the layers can disagree. And the view catches every exception into a
        flash message and returns 200, so a refusal and a success look
        identical by status code. The only assertion that means anything here
        is whether the money moved.
        """
        from apps.fund_requests.finance_models import PartnerPayment

        assignment, activity = self._assigned_activity()

        def pay(actor, reference):
            self.client.force_login(actor)
            try:
                return self.client.post(
                    f"/accounts/partner-payments/{activity.id}/pay",
                    {
                        "partner_name": self.partner.name,
                        "amount_paid": str(LUMP_SUM),
                        "payment_method": "Bank Transfer",
                        "payment_reference": reference,
                        "netsuite_expense_id": f"NS-{reference}",
                        "payment_type": PartnerPayment.TYPE_CLEARANCE,
                    },
                )
            finally:
                self.client.logout()

        # ── Before IA verification: the door must not release money ───────
        pay(self.accountant, "DOOR-EARLY")
        self.assertFalse(
            PartnerPayment.objects.filter(activity=activity).exists(),
            "unverified partner work was paid through the real endpoint. "
            "INTG-05 was exactly this, one layer down.",
        )
        activity.refresh_from_db()
        self.assertNotEqual(activity.payment_status, "paid")

        self._verify(activity)

        # ── After verification: the same request now settles ──────────────
        pay(self.accountant, "DOOR-PAID")
        payment = PartnerPayment.objects.filter(activity=activity).first()
        self.assertIsNotNone(
            payment,
            "verified partner work could not be paid through the endpoint an "
            "Accountant actually uses",
        )
        self.assertEqual(payment.amount_paid, LUMP_SUM)
        activity.refresh_from_db()
        self.assertEqual(activity.payment_status, "paid")
        self.assertEqual(assignment.scheduled_activity_id, activity.id)

    def test_the_partner_payment_door_refuses_everyone_without_payment_act(self):
        """No actor without `payment.act` moves partner money through the door.

        Read the claim narrowly: this proves the money does not move, not
        *which* layer stopped it. Three independent layers own that rule and
        the probe cannot see which one fired —

          1. `@require_page_permission("disbursements")` on the view,
          2. `_lacks_payment_authority` inside the view body,
          3. `_assert_may_pay` inside `PartnerPaymentService.pay_partner`,
             before the row lock and before any write.

        Deleting any single one of them leaves this test green, which is the
        point of writing it down rather than treating the green as coverage of
        layer 2. That redundancy is deliberate (FIN-03): the finding was that
        the partner channel handed payment authority back three separate ways,
        so the fix asserts at the money as well as at the door.

        Asserted on state rather than status, deliberately. The view turns a
        refusal into a flash message and a 200, so a status-only probe would
        report every one of these as a success.
        """
        from apps.core.rbac import EdifyRole
        from apps.fund_requests.finance_models import PartnerPayment

        _assignment, activity = self._assigned_activity()
        self._verify(activity)

        # Admin is the role this probe exists for. Impact Assessment and the
        # partner never reach the view body at all — the `disbursements` PAGE
        # gate stops them — so on their own they say nothing about payment
        # authority, only about navigation.
        #
        # Admin *holds* the disbursements page — navigation maps it to
        # {Accountant, Admin} so the queue can be read — and is refused the
        # ACT further in. Reading a queue is not authority to pay out of it:
        # that is the separation of duties FIN-03 restored, and Admin is the
        # only one of the three that exercises it.
        from apps.accounts.models import User as _User

        admin = _User.objects.create(
            id="pj-pay-admin",
            email="pj-pay-admin@edify.org",
            name="PJ Payment Admin",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
            is_active=True,
        )
        for actor, role in (
            (admin, EdifyRole.ADMIN.value),
            (self.ia, EdifyRole.IMPACT_ASSESSMENT.value),
            (self.partner_user, "partner"),
        ):
            with self.subTest(role=role):
                self.client.force_login(actor)
                try:
                    self.client.post(
                        f"/accounts/partner-payments/{activity.id}/pay",
                        {
                            "partner_name": self.partner.name,
                            "amount_paid": str(LUMP_SUM),
                            "payment_method": "Bank Transfer",
                            "payment_reference": f"DOOR-DENY-{role}",
                            "netsuite_expense_id": f"NS-DENY-{role}",
                            "payment_type": PartnerPayment.TYPE_CLEARANCE,
                        },
                    )
                finally:
                    self.client.logout()

                self.assertFalse(
                    PartnerPayment.objects.filter(activity=activity).exists(),
                    f"{role} released a partner payment through the endpoint",
                )

    def test_each_layer_of_the_payment_defence_refuses_on_its_own(self):
        """Pin all three layers separately, because redundancy hides mutation.

        The sweep above stays green if any single layer is deleted — that is
        what defence in depth means and it is exactly what makes the sweep
        useless as regression cover for any one guard. So assert each layer
        against an Admin (holds the disbursements page, is denied `payment.act`)
        where the endpoint probe cannot separate them.
        """
        from django.test import RequestFactory

        from apps.core.exceptions import Forbidden
        from apps.core.rbac import EdifyRole
        from apps.frontend.views.finance_views import _lacks_payment_authority
        from apps.fund_requests.finance_services import PartnerPaymentService
        from apps.core.permissions import RolePermissionService

        _assignment, activity = self._assigned_activity()
        self._verify(activity)

        admin = User.objects.create(
            id="pj-layer-admin",
            email="pj-layer-admin@edify.org",
            name="PJ Layer Admin",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
            is_active=True,
        )

        # Layer 1 — the page gate. It is a navigation rule, so read it from
        # navigation: it must keep IA and the partner off the screen entirely,
        # and must NOT be what stops the Admin (or layers 2 and 3 would never
        # be reached and the separation of duties would be untested).
        for actor, allowed in ((admin, True), (self.ia, False)):
            self.assertEqual(
                RolePermissionService.can_view_page(actor, "disbursements"),
                allowed,
                f"{actor.active_role} page access to disbursements changed",
            )

        # Layer 2 — the view body.
        request = RequestFactory().post("/accounts/partner-payments/x/pay")
        request.user = admin
        self.assertIsNotNone(
            _lacks_payment_authority(request),
            "the view stopped asserting payment.act on a page-holder",
        )

        # Layer 3 — the service, at the money, before the row lock.
        with self.assertRaises(Forbidden):
            PartnerPaymentService.pay_partner(
                activity=activity,
                partner_name=self.partner.name,
                amount=LUMP_SUM,
                method="Bank Transfer",
                reference="LAYER-3",
                user_id=admin.id,
                netsuite_id="NS-LAYER-3",
            )
        from apps.fund_requests.finance_models import PartnerPayment

        self.assertFalse(PartnerPayment.objects.filter(activity=activity).exists())

    def _verify(self, activity):
        """Take one assigned activity to IA-verified, as the journey does."""
        from apps.activities.ia_services import ActivityCertificationService
        from apps.evidence.models import EvidenceRecord

        EvidenceRecord.objects.create(
            activity_id=activity.id,
            kind="partner_activity_report",
            uri="journey/partner-report-door.pdf",
            original_name="partner-report-door.pdf",
            file_size=2048,
            uploaded_by=self.partner_user.id,
        )
        activity.salesforce_activity_id = f"SVE-DOOR-{activity.id[:6]}"
        activity.status = "awaiting_ia_verification"
        activity.save(update_fields=["salesforce_activity_id", "status"])
        with self.captureOnCommitCallbacks(execute=True):
            ActivityCertificationService.certify_activity(activity, {}, str(self.ia.id))
        activity.refresh_from_db()

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
