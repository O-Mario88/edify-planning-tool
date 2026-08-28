"""Journey 17 — the loan, walked end to end.

Eleven steps and the platform's third money path: Funding Facility, MFI loan
entry, Enrolment, Purpose, Disbursement, BT Salesforce confirmation, IA
validation, Repayment, Loan-use verification, Impact, Geographic analytics.

It is the money path this audit had walked least, and the one with the most
parties: Edify refers, a microfinance institution lends, a funding facility
supplies the principal, Impact & Analytics verifies what the money did, and
the district analytics behind it decide where the next facility goes. Money
moves twice in opposite directions — out as a disbursement, back as repayment
— and none of it is Edify's own budget, which is why the ledger governs so
hard.

WHAT THE WALK IS ACTUALLY TESTING

Not that the eleven calls succeed in order. It is that the ledger is the
authority for every fact about money, and that a party may only assert the
facts it is entitled to assert. Those two rules are what the design says out
loud, and both are driven here as refusals rather than described:

  * a loan record cannot carry typed disbursement facts — "Disbursement facts
    cannot be entered on a loan record; post a facility-backed disbursement",
    and disbursed/active/repaid/defaulted are refused as entered statuses
    because they are "ledger-derived"
  * a repayment schedule's principal must equal the confirmed net disbursed
    principal, so a schedule cannot quietly describe a different loan
  * the partner reports what the money was used for; Impact & Analytics
    verifies it, and cannot verify more than the partner reported

The last one is this audit's recurring question — can one party both do the
work and certify it — asked of lending. It cannot: reporting takes the loan
write permission and verifying takes the IA validation permission, and the two
sit on different roles.

The eleventh step is the one that is easy to get wrong in a way nobody notices.
`geographic_equity` builds a COMPLETE district spine, so a district with
eligible schools and no lending reports zero rather than being absent from the
result. Zero and missing are different findings — one says the programme has
not reached a district, the other says nobody knows — and an equity analysis
that silently drops unfinanced districts would report perfect coverage of
wherever it already lends. The walk asserts a never-financed district is
present with its zero.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.core.exceptions import BadRequest, ConflictError, Forbidden
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School

from . import lending_impact, lending_ledger, services
from .models import (
    EnrolmentSnapshotKind,
    LoanPurpose,
    LoanPurposeAllocation,
    LoanStatus,
    LoanVerificationRequirement,
    MfiLoan,
    MfiMembership,
    MfiMembershipRole,
    MfiOrganization,
    PurposeAllocationStatus,
    ReferralStatus,
    TransformationCase,
)

FACILITY = Decimal("50000000.00")
LOAN = Decimal("12000000.00")
BASELINE_LEARNERS = 400
FOLLOW_UP_LEARNERS = 470


class LoanJourneyTest(TestCase):
    """Facility → referral → loan → disbursement → repayment → impact."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Loan Journey Region")
        cls.district = District.objects.create(
            name="Loan Journey District", region=cls.region
        )
        # A second district with an eligible school and no lending at all.
        # Step 11 is only meaningful if something in the spine is a real zero.
        cls.unfinanced_district = District.objects.create(
            name="Loan Journey Unfinanced District", region=cls.region
        )
        cls.school = School.objects.create(
            school_id="UG-LOANJ-001",
            name="Loan Journey School",
            region=cls.region,
            district=cls.district,
            enrollment=BASELINE_LEARNERS,
        )
        cls.unfinanced_school = School.objects.create(
            school_id="UG-LOANJ-002",
            name="Eligible, Never Financed",
            region=cls.region,
            district=cls.unfinanced_district,
        )

        def _user(email, role):
            return User.objects.create_user(
                email=email,
                name=email.split("@")[0],
                roles=[role.value],
                active_role=role.value,
            )

        cls.bt = _user("loanj-bt@edify.org", EdifyRole.BUSINESS_TRANSFORMATION_OFFICER)
        cls.cd = _user("loanj-cd@edify.org", EdifyRole.COUNTRY_DIRECTOR)
        cls.accountant = _user("loanj-acct@edify.org", EdifyRole.PROGRAM_ACCOUNTANT)
        cls.ia = _user("loanj-ia@edify.org", EdifyRole.IMPACT_ASSESSMENT)
        cls.mfi_admin = _user("loanj-mfi@edify.org", EdifyRole.MFI_PARTNER_ADMIN)
        cls.officer = _user("loanj-officer@edify.org", EdifyRole.MFI_LOAN_OFFICER)

        cls.mfi = MfiOrganization.objects.create(
            code="LOANJ-MFI", name="Loan Journey MFI", country_code="UG"
        )
        MfiMembership.objects.create(
            mfi=cls.mfi, user=cls.mfi_admin, role=MfiMembershipRole.ADMIN
        )
        MfiMembership.objects.create(
            mfi=cls.mfi, user=cls.officer, role=MfiMembershipRole.LOAN_OFFICER
        )

        # A governed purpose from the platform's own reference data, not one
        # invented for the test — `register_or_update_loan` refuses a retired
        # purpose, and the point of the reference list is that it is the list.
        cls.purpose = LoanPurpose.objects.filter(
            code="CLASSROOM_CONSTRUCTION", active=True
        ).first()
        cls.case = TransformationCase.objects.create(
            school=cls.school, status="active", opened_fy="2026"
        )

    def setUp(self):
        self.today = timezone.localdate()
        # The whole loan sits in the past. The ledger refuses a repayment
        # dated in the future — rightly, since a receipt is a fact about money
        # that has arrived — so a walk that ends in repayment has to start far
        # enough back for the schedule to have fallen due.
        self.disbursed_on = self.today - timedelta(days=120)
        self.first_due = self.today - timedelta(days=90)
        self.second_due = self.today - timedelta(days=60)
        self.follow_up_on = self.today - timedelta(days=30)

    # ── Step 1: the facility the principal comes from ────────────────────
    def _funded_facility(self):
        facility = lending_ledger.create_funding_facility(
            {
                "mfiId": self.mfi.id,
                "externalReference": "LOANJ-FAC-1",
                "name": "Loan Journey Facility",
                "commitmentAmount": str(FACILITY),
                "currency": "UGX",
                "countryCode": "UG",
                "revolving": True,
                "startsOn": (self.today - timedelta(days=30)).isoformat(),
                "endsOn": (self.today + timedelta(days=700)).isoformat(),
                "agreementReference": "LOANJ-AGREEMENT-1",
            },
            self.bt,
        )
        facility = lending_ledger.approve_funding_facility(facility.id, self.cd)
        lending_ledger.confirm_facility_tranche(
            {
                "facilityId": facility.id,
                "externalReference": "LOANJ-BANK-IN-1",
                "idempotencyKey": "loanj-receipt-1",
                "amount": str(FACILITY),
                "receivedOn": (self.today - timedelta(days=29)).isoformat(),
                "valueDate": (self.today - timedelta(days=29)).isoformat(),
                "evidenceReference": "LOANJ-NETSUITE-1",
            },
            self.accountant,
        )
        return facility

    def test_step_1_a_facility_needs_three_different_people(self):
        """Author, approver and the person who says the money arrived."""
        facility = lending_ledger.create_funding_facility(
            {
                "mfiId": self.mfi.id,
                "externalReference": "LOANJ-FAC-SEP",
                "name": "Separation Facility",
                "commitmentAmount": str(FACILITY),
                "currency": "UGX",
                "countryCode": "UG",
                "revolving": True,
                "startsOn": (self.today - timedelta(days=30)).isoformat(),
                "endsOn": (self.today + timedelta(days=700)).isoformat(),
                "agreementReference": "LOANJ-AGREEMENT-SEP",
            },
            self.bt,
        )
        with self.assertRaises(Forbidden):
            lending_ledger.approve_funding_facility(facility.id, self.bt)
        lending_ledger.approve_funding_facility(facility.id, self.cd)

        with self.assertRaises(Forbidden):
            lending_ledger.confirm_facility_tranche(
                {
                    "facilityId": facility.id,
                    "externalReference": "LOANJ-BANK-SEP",
                    "idempotencyKey": "loanj-receipt-sep",
                    "amount": str(FACILITY),
                    "receivedOn": self.today.isoformat(),
                    "valueDate": self.today.isoformat(),
                    "evidenceReference": "LOANJ-NETSUITE-SEP",
                },
                self.bt,
            )

    # ── Step 2: the loan is entered against a real Edify referral ────────
    def _referred_loan(self, reference="LOANJ-LN-1"):
        referral = services.create_referral(
            {
                "caseId": self.case.id,
                "mfiId": self.mfi.id,
                "purposeId": self.purpose.id,
                "requestedAmount": str(LOAN),
                "intendedUse": "Two classroom blocks for the growing lower school.",
                "consentRecordedAt": timezone.now().isoformat(),
            },
            # The Country Director refers, not the Business Transformation
            # Officer. Referral commits Edify's name and a school's consent to
            # a lender, and BUSINESS_TRANSFORMATION_REFERRAL_MANAGE sits on
            # the CD alone. The BT Officer's authority in this journey is the
            # Salesforce confirmation at step 6 — recording that the loan
            # exists, not deciding that it should.
            self.cd,
        )
        services.record_referral_decision(
            referral["id"], {"status": ReferralStatus.APPROVED}, self.mfi_admin
        )
        loan_data = services.register_or_update_loan(
            {
                "referralId": referral["id"],
                "externalLoanReference": reference,
                "status": LoanStatus.PROCESSING,
                "approvedAmount": str(LOAN),
                "approvedAt": timezone.now().isoformat(),
                "termMonths": 18,
            },
            self.officer,
        )
        return MfiLoan.objects.get(id=loan_data["id"])

    def test_step_2_a_loan_record_may_not_carry_typed_money_facts(self):
        """The rule the whole ledger rests on, driven rather than described."""
        referral = services.create_referral(
            {
                "caseId": self.case.id,
                "mfiId": self.mfi.id,
                "purposeId": self.purpose.id,
                "requestedAmount": str(LOAN),
                "intendedUse": "Classrooms.",
                "consentRecordedAt": timezone.now().isoformat(),
            },
            self.cd,
        )
        services.record_referral_decision(
            referral["id"], {"status": ReferralStatus.APPROVED}, self.mfi_admin
        )
        base = {
            "referralId": referral["id"],
            "externalLoanReference": "LOANJ-LN-TYPED",
            "approvedAmount": str(LOAN),
            "approvedAt": timezone.now().isoformat(),
            "termMonths": 18,
        }

        with self.assertRaises(BadRequest) as typed:
            services.register_or_update_loan(
                {**base, "disbursedAmount": str(LOAN)}, self.officer
            )
        self.assertIn("facility-backed disbursement", str(typed.exception))

        with self.assertRaises(BadRequest) as derived:
            services.register_or_update_loan(
                {**base, "status": LoanStatus.DISBURSED}, self.officer
            )
        self.assertIn("ledger-derived", str(derived.exception))

        self.assertFalse(
            MfiLoan.objects.filter(external_loan_reference="LOANJ-LN-TYPED").exists(),
            "a refused entry must not leave a loan behind",
        )

    # ── Steps 3–5: enrolment, purpose, and money out ─────────────────────
    def _disbursed_loan(self, reference="LOANJ-LN-1"):
        facility = self._funded_facility()
        loan = self._referred_loan(reference)

        lending_impact.set_purpose_allocation_plan(
            loan.id,
            [
                {
                    "purposeId": self.purpose.id,
                    "plannedAmount": str(LOAN),
                    "intendedOutput": "Two completed classroom blocks.",
                }
            ],
            self.officer,
        )
        baseline = lending_impact.capture_enrolment_snapshot(
            loan.id,
            {
                "kind": "baseline",
                "asOfDate": self.disbursed_on.isoformat(),
                "learnerCount": BASELINE_LEARNERS,
                "cohortDefinition": "All learners enrolled at first disbursement",
                "evidenceReference": f"LOANJ-ENROL-{reference}",
            },
            self.officer,
        )
        lending_impact.verify_enrolment_snapshot(baseline.id, {}, self.ia)

        lending_ledger.reserve_facility_for_loan(
            {
                "facilityId": facility.id,
                "loanId": loan.id,
                "amount": str(LOAN),
                "idempotencyKey": f"loanj-alloc-{reference}",
            },
            self.bt,
        )
        lending_ledger.post_loan_disbursement(
            {
                "loanId": loan.id,
                "sequence": 1,
                "externalReference": f"LOANJ-DISB-{reference}",
                "idempotencyKey": f"loanj-disb-{reference}",
                "amount": str(LOAN),
                "disbursedOn": self.disbursed_on.isoformat(),
                "valueDate": self.disbursed_on.isoformat(),
                "bankReference": f"LOANJ-BANK-OUT-{reference}",
                "evidenceReference": f"LOANJ-BANK-OUT-{reference}",
            },
            self.mfi_admin,
        )
        loan.refresh_from_db()
        return facility, loan

    def test_steps_3_to_5_disbursement_moves_the_status_and_opens_monitoring(self):
        _, loan = self._disbursed_loan()

        self.assertIn(loan.status, {LoanStatus.DISBURSED, LoanStatus.ACTIVE})
        self.assertEqual(loan.disbursed_amount, LOAN)
        # Step 7 begins here: disbursement is what creates the obligation to
        # come back and check what the money did.
        requirement = LoanVerificationRequirement.objects.get(loan=loan)
        self.assertGreater(
            requirement.due_date,
            self.disbursed_on,
            "the obligation to check what the money did is dated from the "
            "disbursement, not from whenever anyone next looks",
        )

    def test_a_repayment_cannot_be_posted_before_the_money_went_out(self):
        loan = self._referred_loan("LOANJ-LN-EARLY")
        with self.assertRaises(ConflictError):
            lending_ledger.post_repayment_transaction(
                {
                    "loanId": loan.id,
                    "externalReference": "LOANJ-PAY-EARLY",
                    "idempotencyKey": "loanj-pay-early",
                    "amount": "100.00",
                    "receivedOn": self.today.isoformat(),
                    "valueDate": self.today.isoformat(),
                    "allocations": [],
                },
                self.mfi_admin,
            )

    # ── Steps 6 and 8: the confirmation, and the money coming back ───────
    def _schedule(self, loan):
        half = (LOAN / 2).quantize(Decimal("0.01"))
        return lending_ledger.create_repayment_schedule(
            loan.id,
            [
                {
                    "installmentNumber": 1,
                    "dueDate": self.first_due.isoformat(),
                    "principalDue": str(half),
                    "interestDue": "100000.00",
                    "feeDue": "0.00",
                },
                {
                    "installmentNumber": 2,
                    "dueDate": self.second_due.isoformat(),
                    "principalDue": str(LOAN - half),
                    "interestDue": "100000.00",
                    "feeDue": "0.00",
                },
            ],
            self.mfi_admin,
        )

    def test_step_8_a_schedule_must_describe_the_loan_that_was_disbursed(self):
        _, loan = self._disbursed_loan("LOANJ-LN-SCHED")
        with self.assertRaises(BadRequest) as mismatch:
            lending_ledger.create_repayment_schedule(
                loan.id,
                [
                    {
                        "installmentNumber": 1,
                        "dueDate": self.first_due.isoformat(),
                        "principalDue": "1.00",
                        "interestDue": "0.00",
                        "feeDue": "0.00",
                    }
                ],
                self.mfi_admin,
            )
        self.assertIn("net disbursed principal", str(mismatch.exception))

    # ── Step 9: who reports, and who verifies ────────────────────────────
    def test_step_9_the_lender_reports_the_use_and_only_ia_verifies_it(self):
        _, loan = self._disbursed_loan("LOANJ-LN-USE")
        allocation = LoanPurposeAllocation.objects.get(loan=loan)

        lending_impact.report_purpose_use(
            allocation.id,
            {"reportedAmount": str(LOAN), "note": "Both blocks built."},
            self.officer,
        )

        # The party that moved the money does not get to certify what it did.
        for actor in (self.officer, self.mfi_admin):
            with self.subTest(actor.active_role):
                with self.assertRaises(Forbidden):
                    lending_impact.verify_purpose_use(
                        allocation.id, {"verifiedAmount": str(LOAN)}, actor
                    )

        # And IA cannot verify more than was reported.
        with self.assertRaises(BadRequest):
            lending_impact.verify_purpose_use(
                allocation.id, {"verifiedAmount": str(LOAN + Decimal("1.00"))}, self.ia
            )

        lending_impact.verify_purpose_use(
            allocation.id,
            {"verifiedAmount": str(LOAN), "note": "Site visited; blocks in use."},
            self.ia,
        )
        allocation.refresh_from_db()
        self.assertEqual(allocation.status, PurposeAllocationStatus.VERIFIED)
        self.assertEqual(allocation.verified_amount, LOAN)

    # ── The whole journey, in order, as one walk ─────────────────────────
    def test_the_whole_loan_in_order(self):
        """All eleven steps, one test, because that is what covered means."""
        # 1. Funding facility, 2. referral and loan entry, 3. enrolment
        # baseline verified, 4. purpose plan, 5. disbursement.
        facility, loan = self._disbursed_loan("LOANJ-LN-WALK")
        self.assertEqual(loan.disbursed_amount, LOAN)

        position = lending_ledger.facility_position(facility)
        self.assertEqual(
            position["confirmedDisbursements"],
            LOAN,
            "the facility must know what left it",
        )
        self.assertEqual(
            position["available"],
            FACILITY - LOAN,
            "and what is left to lend, which is the same statement said the "
            "other way round — a facility whose two halves disagree is how "
            "the same shilling gets lent twice",
        )
        self.assertEqual(position["reconciliationDifference"], Decimal("0.00"))

        # 6. BT confirms the loan exists in Salesforce. The lender's facts are
        # not theirs to edit; the Salesforce id is not the lender's to assert.
        with self.assertRaises(Forbidden):
            services.confirm_salesforce_loan(
                loan.id, {"salesforceLoanId": "Loan-77001"}, self.mfi_admin
            )
        services.confirm_salesforce_loan(
            loan.id, {"salesforceLoanId": "Loan-77001"}, self.bt
        )
        loan.refresh_from_db()
        self.assertEqual(loan.salesforce_loan_id, "Loan-77001")

        # 7. IA validation — the obligation disbursement created.
        requirement = LoanVerificationRequirement.objects.get(loan=loan)
        self.assertGreater(
            requirement.due_date,
            self.disbursed_on,
            "the obligation to check what the money did is dated from the "
            "disbursement, not from whenever anyone next looks",
        )

        # 8. Repayment: the schedule, then money actually coming back.
        installments = self._schedule(loan)
        self.assertEqual(len(installments), 2)
        first = installments[0]
        lending_ledger.post_repayment_transaction(
            {
                "loanId": loan.id,
                "externalReference": "LOANJ-PAY-1",
                "idempotencyKey": "loanj-pay-1",
                "amount": str(first.principal_due + first.interest_due),
                "receivedOn": self.first_due.isoformat(),
                "valueDate": self.first_due.isoformat(),
                "evidenceReference": "LOANJ-BANK-IN-PAY-1",
                "allocations": [
                    {
                        "installmentId": first.id,
                        "component": "principal",
                        "amount": str(first.principal_due),
                    },
                    {
                        "installmentId": first.id,
                        "component": "interest",
                        "amount": str(first.interest_due),
                    },
                ],
            },
            self.mfi_admin,
        )

        # 9. Loan-use verification: partner reports, IA verifies.
        allocation = LoanPurposeAllocation.objects.get(loan=loan)
        lending_impact.report_purpose_use(
            allocation.id, {"reportedAmount": str(LOAN)}, self.officer
        )
        lending_impact.verify_purpose_use(
            allocation.id, {"verifiedAmount": str(LOAN)}, self.ia
        )

        # 10. Impact: a follow-up enrolment snapshot, verified.
        follow_up = lending_impact.capture_enrolment_snapshot(
            loan.id,
            {
                "kind": EnrolmentSnapshotKind.FOLLOW_UP,
                "asOfDate": self.follow_up_on.isoformat(),
                "learnerCount": FOLLOW_UP_LEARNERS,
                "cohortDefinition": "All learners one term after the blocks opened",
                "evidenceReference": "LOANJ-ENROL-FOLLOWUP",
            },
            self.officer,
        )
        lending_impact.verify_enrolment_snapshot(follow_up.id, {}, self.ia)

        summary = lending_impact.impact_summary(self.bt)
        self.assertEqual(summary["verifiedBaselineLoans"], 1)
        self.assertEqual(summary["verifiedFollowUpLoans"], 1)
        self.assertEqual(summary["verifiedLearnersObserved"], FOLLOW_UP_LEARNERS)
        self.assertEqual(
            summary["missingBaselineLoans"],
            0,
            "a loan without a verified baseline cannot have its impact read; "
            "this one has both ends",
        )

        # 11. Geographic analytics — and the district that has never borrowed
        # must be present with a zero, not absent.
        rows = {r["districtId"]: r for r in lending_equity_rows(self.bt)}
        financed = rows[self.district.id]
        self.assertEqual(financed["schoolsFinanced"], 1)
        self.assertEqual(financed["verifiedImpactSchools"], 1)

        self.assertIn(
            self.unfinanced_district.id,
            rows,
            "an equity analysis that drops districts with no lending reports "
            "perfect coverage of wherever it already lends",
        )
        untouched = rows[self.unfinanced_district.id]
        self.assertEqual(untouched["loanCount"], 0)
        self.assertEqual(untouched["schoolsFinanced"], 0)
        self.assertGreaterEqual(untouched["eligibleSchools"], 1)

        self.client.force_login(self.bt)
        response = self.client.get("/business-transformation/impact-reports")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Schools financed")
        self.assertContains(response, "Students reached")

    def test_the_follow_up_snapshot_is_what_makes_impact_readable(self):
        """Guard the premise of step 10: unverified evidence counts for nothing."""
        _, loan = self._disbursed_loan("LOANJ-LN-UNVERIFIED")
        lending_impact.capture_enrolment_snapshot(
            loan.id,
            {
                "kind": EnrolmentSnapshotKind.FOLLOW_UP,
                "asOfDate": self.follow_up_on.isoformat(),
                "learnerCount": FOLLOW_UP_LEARNERS,
                "cohortDefinition": "Reported, not yet verified",
                "evidenceReference": "LOANJ-ENROL-PENDING",
            },
            self.officer,
        )

        summary = lending_impact.impact_summary(self.bt)
        self.assertEqual(
            summary["verifiedFollowUpLoans"],
            0,
            "reported is not verified; impact must not count partner claims",
        )
        self.assertGreaterEqual(summary["reportedEvidencePending"], 1)
        self.assertIsNone(summary["verifiedLearnersObserved"])


def lending_equity_rows(principal):
    payload = lending_impact.geographic_equity(principal)
    return payload["rows"] if isinstance(payload, dict) else payload
