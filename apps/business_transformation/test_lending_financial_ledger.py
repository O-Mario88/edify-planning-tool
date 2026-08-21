from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.core.exceptions import BadRequest, ConflictError, Forbidden
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.integrations.models import IntegrationSync, IntegrationSyncStatus
from apps.outbox.services import drain
from apps.schools.models import School

from . import lending_impact, lending_imports, lending_ledger, services
from .models import (
    FacilityAllocationStatus,
    FundingFacilityAllocation,
    FundingFacilityStatus,
    FundingFacilityTranche,
    LoanDisbursement,
    LoanPurpose,
    LoanPurposeAllocation,
    LoanStatus,
    LoanUseFinding,
    LoanUseResult,
    LoanVerificationRequirement,
    MfiLoan,
    MfiMembership,
    MfiMembershipRole,
    MfiOrganization,
    PortfolioSubmissionStatus,
    RepaymentTransaction,
    TransformationCase,
)


class LendingFinancialLedgerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.bt = User.objects.create_user(
            email="ledger-bt@example.org",
            name="Ledger BT",
            roles=[EdifyRole.BUSINESS_TRANSFORMATION_OFFICER.value],
            active_role=EdifyRole.BUSINESS_TRANSFORMATION_OFFICER.value,
        )
        cls.cd = User.objects.create_user(
            email="ledger-cd@example.org",
            name="Ledger CD",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
        )
        cls.cd_approver = User.objects.create_user(
            email="ledger-cd-approver@example.org",
            name="Ledger CD Approver",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
        )
        cls.accountant = User.objects.create_user(
            email="ledger-accountant@example.org",
            name="Ledger Accountant",
            roles=[EdifyRole.PROGRAM_ACCOUNTANT.value],
            active_role=EdifyRole.PROGRAM_ACCOUNTANT.value,
        )
        cls.ia = User.objects.create_user(
            email="ledger-ia@example.org",
            name="Ledger IA",
            roles=[EdifyRole.IMPACT_ASSESSMENT.value],
            active_role=EdifyRole.IMPACT_ASSESSMENT.value,
        )
        cls.rvp = User.objects.create_user(
            email="ledger-rvp@example.org",
            name="Ledger RVP",
            roles=[EdifyRole.REGIONAL_VICE_PRESIDENT.value],
            active_role=EdifyRole.REGIONAL_VICE_PRESIDENT.value,
        )
        cls.mfi_admin = User.objects.create_user(
            email="ledger-mfi-admin@example.org",
            name="Ledger MFI Admin",
            roles=[EdifyRole.MFI_PARTNER_ADMIN.value],
            active_role=EdifyRole.MFI_PARTNER_ADMIN.value,
        )
        cls.other_mfi_admin = User.objects.create_user(
            email="ledger-other-mfi@example.org",
            name="Other MFI Admin",
            roles=[EdifyRole.MFI_PARTNER_ADMIN.value],
            active_role=EdifyRole.MFI_PARTNER_ADMIN.value,
        )
        cls.mfi = MfiOrganization.objects.create(
            code="LEDGER-MFI", name="Ledger MFI", country_code="UG"
        )
        cls.other_mfi = MfiOrganization.objects.create(
            code="OTHER-MFI", name="Other MFI", country_code="UG"
        )
        MfiMembership.objects.create(
            mfi=cls.mfi,
            user=cls.mfi_admin,
            role=MfiMembershipRole.ADMIN,
        )
        MfiMembership.objects.create(
            mfi=cls.other_mfi,
            user=cls.other_mfi_admin,
            role=MfiMembershipRole.ADMIN,
        )
        cls.region = Region.objects.create(name="Ledger Region")
        cls.district = District.objects.create(
            name="Ledger District", region=cls.region
        )
        cls.zero_district = District.objects.create(
            name="Zero Lending District", region=cls.region
        )
        cls.school = School.objects.create(
            school_id="UG-LEDGER-001",
            name="Ledger School",
            region=cls.region,
            district=cls.district,
        )
        cls.zero_district_school = School.objects.create(
            school_id="UG-LEDGER-ZERO-001",
            name="Eligible School Without Financing",
            region=cls.region,
            district=cls.zero_district,
        )
        cls.case = TransformationCase.objects.create(
            school=cls.school, status="active", opened_fy="2026"
        )
        cls.purpose = LoanPurpose.objects.create(
            code="LEDGER-WC", label="Ledger working capital"
        )

    def setUp(self):
        self.loan = MfiLoan.objects.create(
            mfi=self.mfi,
            school=self.school,
            case=self.case,
            purpose=self.purpose,
            external_loan_reference="LEDGER-LOAN-001",
            approved_amount=Decimal("1000.00"),
            currency="UGX",
            status=LoanStatus.PROCESSING,
            registered_by=self.mfi_admin.id,
        )

    def _approved_facility(self, *, revolving=True):
        facility = lending_ledger.create_funding_facility(
            {
                "mfiId": self.mfi.id,
                "externalReference": "FAC-001",
                "name": "School Growth Facility",
                "commitmentAmount": "2000.00",
                "currency": "UGX",
                "countryCode": "UG",
                "revolving": revolving,
                "startsOn": "2026-01-01",
                "endsOn": "2027-12-31",
                "agreementReference": "AGREEMENT-001",
            },
            self.bt,
        )
        return lending_ledger.approve_funding_facility(facility.id, self.cd)

    def _fund_and_disburse(self, *, revolving=True):
        if not LoanPurposeAllocation.objects.filter(loan=self.loan).exists():
            lending_impact.set_purpose_allocation_plan(
                self.loan.id,
                [
                    {
                        "purposeId": self.purpose.id,
                        "plannedAmount": "1000.00",
                        "intendedOutput": "Governed test output",
                    }
                ],
                self.mfi_admin,
            )
        if not self.loan.enrolment_snapshots.filter(kind="baseline").exists():
            baseline = lending_impact.capture_enrolment_snapshot(
                self.loan.id,
                {
                    "kind": "baseline",
                    "asOfDate": "2026-01-01",
                    "learnerCount": 400,
                    "cohortDefinition": "All learners at first disbursement",
                    "evidenceReference": "ENROLMENT-BASELINE",
                },
                self.mfi_admin,
            )
            lending_impact.verify_enrolment_snapshot(baseline.id, {}, self.ia)
        facility = self._approved_facility(revolving=revolving)
        tranche = lending_ledger.confirm_facility_tranche(
            {
                "facilityId": facility.id,
                "externalReference": "BANK-IN-001",
                "idempotencyKey": "receipt-001",
                "amount": "2000.00",
                "receivedOn": "2026-01-02",
                "valueDate": "2026-01-02",
                "evidenceReference": "NETSUITE-001",
            },
            self.accountant,
        )
        allocation = lending_ledger.reserve_facility_for_loan(
            {
                "facilityId": facility.id,
                "loanId": self.loan.id,
                "amount": "1000.00",
                "idempotencyKey": "allocation-001",
            },
            self.bt,
        )
        disbursement = lending_ledger.post_loan_disbursement(
            {
                "loanId": self.loan.id,
                "sequence": 1,
                "externalReference": "BANK-OUT-001",
                "idempotencyKey": "disbursement-001",
                "amount": "1000.00",
                "disbursedOn": "2026-01-03",
                "valueDate": "2026-01-03",
                "bankReference": "BANK-OUT-001",
            },
            self.mfi_admin,
        )
        return facility, tranche, allocation, disbursement

    def _schedule(self):
        return lending_ledger.create_repayment_schedule(
            self.loan.id,
            [
                {
                    "installmentNumber": 1,
                    "dueDate": "2026-02-01",
                    "principalDue": "500.00",
                    "interestDue": "50.00",
                    "feeDue": "0.00",
                },
                {
                    "installmentNumber": 2,
                    "dueDate": "2026-03-01",
                    "principalDue": "500.00",
                    "interestDue": "50.00",
                    "feeDue": "0.00",
                },
            ],
            self.mfi_admin,
        )

    def _first_repayment(self, installments):
        return lending_ledger.post_repayment_transaction(
            {
                "loanId": self.loan.id,
                "externalReference": "PAY-001",
                "idempotencyKey": "repayment-001",
                "amount": "550.00",
                "receivedOn": "2026-02-01",
                "valueDate": "2026-02-01",
                "evidenceReference": "BANK-PAY-001",
                "allocations": [
                    {
                        "installmentId": installments[0].id,
                        "component": "principal",
                        "amount": "500.00",
                    },
                    {
                        "installmentId": installments[0].id,
                        "component": "interest",
                        "amount": "50.00",
                    },
                ],
            },
            self.mfi_admin,
        )

    def test_facility_requires_creator_approver_separation_and_confirmed_cash(self):
        facility = lending_ledger.create_funding_facility(
            {
                "mfiId": self.mfi.id,
                "externalReference": "FAC-SEPARATION",
                "name": "Separation Facility",
                "commitmentAmount": "1000.00",
                "startsOn": "2026-01-01",
            },
            self.cd,
        )

        with self.assertRaises(Forbidden):
            lending_ledger.approve_funding_facility(facility.id, self.cd)

        facility = lending_ledger.approve_funding_facility(
            facility.id, self.cd_approver
        )
        self.assertEqual(facility.status, FundingFacilityStatus.APPROVED)
        self.assertEqual(lending_ledger.facility_position(facility)["available"], 0)

    def test_receipt_allocation_and_disbursement_reconcile_and_are_idempotent(self):
        facility, tranche, allocation, disbursement = self._fund_and_disburse()

        repeated = lending_ledger.post_loan_disbursement(
            {
                "loanId": self.loan.id,
                "sequence": 1,
                "externalReference": "BANK-OUT-001",
                "idempotencyKey": "disbursement-001",
                "amount": "1000.00",
                "disbursedOn": "2026-01-03",
                "valueDate": "2026-01-03",
                "bankReference": "BANK-OUT-001",
            },
            self.mfi_admin,
        )

        self.assertEqual(repeated.id, disbursement.id)
        self.assertEqual(LoanDisbursement.objects.count(), 1)
        self.assertEqual(tranche.amount, Decimal("2000.00"))
        allocation.refresh_from_db()
        self.assertEqual(allocation.status, FacilityAllocationStatus.CONSUMED)
        position = lending_ledger.facility_position(facility)
        self.assertEqual(position["commitment"], Decimal("2000.00"))
        self.assertEqual(position["confirmedReceipts"], Decimal("2000.00"))
        self.assertEqual(position["originalDisbursements"], Decimal("1000.00"))
        self.assertEqual(position["amountRelended"], Decimal("0.00"))
        self.assertEqual(position["originalCapitalRemaining"], Decimal("1000.00"))
        self.assertEqual(position["available"], Decimal("1000.00"))
        facility_reconciliation = lending_ledger.reconcile_facility(facility)
        loan_reconciliation = lending_ledger.reconcile_loan(self.loan)
        self.assertTrue(facility_reconciliation["reconciled"])
        self.assertEqual(facility_reconciliation["difference"], Decimal("0.00"))
        self.assertTrue(loan_reconciliation["reconciled"])

    def test_unconfirmed_or_insufficient_cash_cannot_be_allocated(self):
        facility = self._approved_facility()

        with self.assertRaises(ConflictError):
            lending_ledger.reserve_facility_for_loan(
                {
                    "facilityId": facility.id,
                    "loanId": self.loan.id,
                    "amount": "1000.00",
                    "idempotencyKey": "allocation-no-cash",
                },
                self.bt,
            )

    def test_cross_tenant_disbursement_is_denied(self):
        _, _, _, _ = self._fund_and_disburse()
        with self.assertRaises(Forbidden):
            lending_ledger.post_loan_disbursement(
                {
                    "loanId": self.loan.id,
                    "sequence": 2,
                    "externalReference": "WRONG-TENANT",
                    "idempotencyKey": "wrong-tenant-disbursement",
                    "amount": "1.00",
                    "disbursedOn": "2026-01-04",
                    "valueDate": "2026-01-04",
                    "bankReference": "WRONG-TENANT",
                },
                self.other_mfi_admin,
            )

    def test_schedule_repayment_position_and_ratios_are_ledger_derived(self):
        facility, _, _, _ = self._fund_and_disburse()
        installments = self._schedule()
        payment = self._first_repayment(installments)

        position = lending_ledger.loan_position(self.loan, as_of=date(2026, 4, 15))
        ratios = lending_ledger.portfolio_ratios(
            MfiLoan.objects.filter(id=self.loan.id),
            period_start=date(2026, 2, 1),
            period_end=date(2026, 3, 31),
            as_of=date(2026, 4, 15),
        )

        self.assertEqual(position["outstandingPrincipal"], Decimal("500.00"))
        self.assertEqual(position["amountOverdue"], Decimal("550.00"))
        self.assertEqual(position["daysPastDue"], 45)
        self.assertEqual(ratios["par30Pct"], Decimal("100.00"))
        self.assertEqual(ratios["par90Pct"], Decimal("0.00"))
        self.assertEqual(ratios["collectionRatePct"], Decimal("50.00"))
        self.assertEqual(ratios["onTimeRatePct"], Decimal("50.00"))
        self.assertEqual(
            lending_ledger.facility_position(facility)["recycledPrincipal"],
            Decimal("500.00"),
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="bt.loan.repayment_posted", subject_id=payment.id
            ).exists()
        )

    def test_portfolio_ratios_use_a_fixed_query_budget(self):
        self._fund_and_disburse()
        self._first_repayment(self._schedule())

        with CaptureQueriesContext(connection) as queries:
            ratios = lending_ledger.portfolio_ratios(
                MfiLoan.objects.filter(id=self.loan.id),
                period_start=date(2026, 2, 1),
                period_end=date(2026, 3, 31),
                as_of=date(2026, 4, 15),
            )

        self.assertEqual(ratios["par30Pct"], Decimal("100.00"))
        self.assertLessEqual(len(queries), 9)

    def test_financial_year_rollover_preserves_the_historical_cohort(self):
        self._fund_and_disburse()
        installments = self._schedule()
        with (
            patch(
                "apps.business_transformation.lending_ledger.timezone.localdate",
                return_value=date(2027, 1, 15),
            ),
            patch(
                "apps.business_transformation.services.timezone.localdate",
                return_value=date(2027, 1, 15),
            ),
        ):
            before = services.portfolio_metrics(self.bt, fy="2026")
            lending_ledger.post_repayment_transaction(
                {
                    "loanId": self.loan.id,
                    "externalReference": "PAY-FY27-001",
                    "idempotencyKey": "repayment-fy27-001",
                    "amount": "550.00",
                    "receivedOn": "2026-10-01",
                    "valueDate": "2026-10-01",
                    "evidenceReference": "BANK-PAY-FY27-001",
                    "allocations": [
                        {
                            "installmentId": installments[0].id,
                            "component": "principal",
                            "amount": "500.00",
                        },
                        {
                            "installmentId": installments[0].id,
                            "component": "interest",
                            "amount": "50.00",
                        },
                    ],
                },
                self.mfi_admin,
            )
            historical = services.portfolio_metrics(self.bt, fy="2026")
            current = services.portfolio_metrics(self.bt, fy="2027")

        self.assertEqual(before["valueDisbursed"], Decimal("1000.00"))
        self.assertEqual(historical["valueDisbursed"], before["valueDisbursed"])
        self.assertEqual(
            historical["activePortfolioValue"], before["activePortfolioValue"]
        )
        self.assertEqual(current["valueDisbursed"], Decimal("0"))
        self.assertEqual(current["amountCollectedDuringPeriod"], Decimal("550.00"))
        self.loan.refresh_from_db()
        self.assertEqual(self.loan.status, LoanStatus.ACTIVE)

    def test_default_classification_requires_date_reason_and_history(self):
        self._fund_and_disburse()
        base = {
            "asOfDate": "2026-08-01",
            "reportingMonth": "2026-08-01",
            "amountDueDuringPeriod": "100.00",
            "amountPaidDuringPeriod": "0.00",
            "principalRepaid": "0.00",
            "outstandingAmount": "1000.00",
            "amountCurrentlyDue": "100.00",
            "amountOverdue": "100.00",
            "daysInArrears": 100,
            "loanStatus": LoanStatus.DEFAULTED,
            "defaultClassifiedAt": "2026-08-01",
        }
        with self.assertRaises(BadRequest):
            services.add_repayment_snapshot(self.loan.id, base, self.mfi_admin)

        services.add_repayment_snapshot(
            self.loan.id,
            {**base, "defaultReason": "Confirmed prolonged non-payment"},
            self.mfi_admin,
        )

        self.loan.refresh_from_db()
        self.assertEqual(self.loan.status, LoanStatus.DEFAULTED)
        self.assertEqual(self.loan.default_classified_at, date(2026, 8, 1))
        self.assertEqual(self.loan.default_reason, "Confirmed prolonged non-payment")
        self.assertTrue(
            self.loan.status_history.filter(
                dimension="lifecycle", new_value=LoanStatus.DEFAULTED
            ).exists()
        )

    def test_repayment_reversal_is_compensating_and_restores_position(self):
        facility, _, _, _ = self._fund_and_disburse()
        payment = self._first_repayment(self._schedule())

        reversal = lending_ledger.reverse_repayment_transaction(
            payment.id,
            {
                "externalReference": "PAY-001-REV",
                "idempotencyKey": "repayment-reversal-001",
                "reason": "Bank returned the payment",
                "evidenceReference": "BANK-RETURN-001",
            },
            self.mfi_admin,
        )

        self.assertEqual(reversal.reversal_of_id, payment.id)
        self.assertEqual(
            lending_ledger.loan_position(self.loan)["outstandingPrincipal"],
            Decimal("1000.00"),
        )
        self.assertEqual(
            lending_ledger.facility_position(facility)["recycledPrincipal"],
            Decimal("0.00"),
        )

    def test_revolving_facility_separates_original_recovered_and_relent_capital(self):
        facility, _, _, _ = self._fund_and_disburse()
        self._first_repayment(self._schedule())
        second_school = School.objects.create(
            school_id="UG-LEDGER-002",
            name="Second Ledger School",
            region=self.region,
            district=self.district,
        )
        second_case = TransformationCase.objects.create(
            school=second_school, status="active", opened_fy="2026"
        )
        second_loan = MfiLoan.objects.create(
            mfi=self.mfi,
            school=second_school,
            case=second_case,
            purpose=self.purpose,
            external_loan_reference="LEDGER-LOAN-002",
            approved_amount=Decimal("400.00"),
            currency="UGX",
            status=LoanStatus.PROCESSING,
            registered_by=self.mfi_admin.id,
        )
        lending_impact.set_purpose_allocation_plan(
            second_loan.id,
            [
                {
                    "purposeId": self.purpose.id,
                    "plannedAmount": "400.00",
                    "intendedOutput": "Recovered-capital test output",
                }
            ],
            self.mfi_admin,
        )
        baseline = lending_impact.capture_enrolment_snapshot(
            second_loan.id,
            {
                "kind": "baseline",
                "asOfDate": "2026-02-01",
                "learnerCount": 200,
                "cohortDefinition": "All learners at first disbursement",
                "evidenceReference": "ENROLMENT-BASELINE-2",
            },
            self.mfi_admin,
        )
        lending_impact.verify_enrolment_snapshot(baseline.id, {}, self.ia)
        allocation = lending_ledger.reserve_facility_for_loan(
            {
                "facilityId": facility.id,
                "loanId": second_loan.id,
                "amount": "400.00",
                "capitalSource": "recovered",
                "idempotencyKey": "allocation-recovered-001",
            },
            self.bt,
        )
        lending_ledger.post_loan_disbursement(
            {
                "loanId": second_loan.id,
                "sequence": 1,
                "externalReference": "BANK-OUT-RECOVERED-001",
                "idempotencyKey": "disbursement-recovered-001",
                "amount": "400.00",
                "disbursedOn": "2026-02-02",
                "valueDate": "2026-02-02",
                "bankReference": "BANK-OUT-RECOVERED-001",
            },
            self.mfi_admin,
        )
        lending_ledger.post_facility_movement(
            {
                "facilityId": facility.id,
                "kind": "capital_return",
                "capitalSource": "recovered",
                "amount": "50.00",
                "externalReference": "RETURN-RECOVERED-001",
                "idempotencyKey": "return-recovered-001",
                "valueDate": "2026-02-03",
                "evidenceReference": "BANK-RETURN-RECOVERED-001",
            },
            self.accountant,
        )

        position = lending_ledger.facility_position(facility)
        self.assertEqual(allocation.capital_source, "recovered")
        self.assertEqual(position["confirmedReceipts"], Decimal("2000.00"))
        self.assertEqual(position["originalCapitalRemaining"], Decimal("1000.00"))
        self.assertEqual(position["principalRecovered"], Decimal("500.00"))
        self.assertEqual(position["amountRelended"], Decimal("400.00"))
        self.assertEqual(
            position["recoveredPrincipalAvailableForRelending"], Decimal("50.00")
        )
        self.assertEqual(position["capitalReturned"], Decimal("50.00"))

    @override_settings(NETSUITE_SYNC_ENABLED=True)
    @patch("apps.integrations.services.push_to_external", return_value="NS-FAC-001")
    def test_facility_receipt_syncs_to_netsuite_through_retry_safe_outbox(self, push):
        facility = self._approved_facility()
        tranche = lending_ledger.confirm_facility_tranche(
            {
                "facilityId": facility.id,
                "externalReference": "BANK-IN-NETSUITE",
                "idempotencyKey": "receipt-netsuite-001",
                "amount": "750.00",
                "receivedOn": "2026-01-02",
                "valueDate": "2026-01-02",
                "paymentReference": "BANK-IN-NETSUITE",
                "sourceAccount": "FUNDER-ACCOUNT",
                "evidenceReference": "BANK-EVIDENCE-NETSUITE",
            },
            self.accountant,
        )

        drain(time_budget_seconds=2)
        sync = IntegrationSync.objects.get(
            system="netsuite",
            context_type="facility_tranche",
            context_id=tranche.id,
        )
        self.assertEqual(sync.status, IntegrationSyncStatus.SUCCEEDED)
        self.assertEqual(sync.external_id, "NS-FAC-001")
        self.assertEqual(push.call_count, 1)
        drain(time_budget_seconds=2)
        self.assertEqual(push.call_count, 1)

    def test_financial_postings_reject_update_and_delete(self):
        _, tranche, _, disbursement = self._fund_and_disburse()

        with self.assertRaises(ValueError):
            FundingFacilityTranche.objects.filter(id=tranche.id).update(
                amount=Decimal("1.00")
            )
        with self.assertRaises(ValueError):
            disbursement.delete()

    def test_required_audit_failure_rolls_back_financial_mutation(self):
        before = self.mfi.funding_facilities.count()
        with patch(
            "apps.business_transformation.lending_ledger.audit_log",
            side_effect=RuntimeError("audit store unavailable"),
        ):
            with self.assertRaisesRegex(RuntimeError, "audit store unavailable"):
                lending_ledger.create_funding_facility(
                    {
                        "mfiId": self.mfi.id,
                        "externalReference": "FAC-AUDIT-ROLLBACK",
                        "name": "Must Roll Back",
                        "commitmentAmount": "1000.00",
                        "startsOn": "2026-01-01",
                    },
                    self.bt,
                )
        self.assertEqual(self.mfi.funding_facilities.count(), before)

    def test_posted_loan_correction_uses_separated_audited_amendment(self):
        self._fund_and_disburse()

        amendment = services.request_loan_amendment(
            self.loan.id,
            {
                "idempotencyKey": "amendment-ledger-loan-001",
                "reason": "Correct the contractual term from the signed agreement.",
                "changes": {"termMonths": 12},
            },
            self.mfi_admin,
        )
        services.approve_loan_amendment(
            amendment.id,
            {"approvalNote": "Matched to the signed facility-backed loan agreement."},
            self.cd,
        )

        self.loan.refresh_from_db()
        amendment.refresh_from_db()
        self.assertEqual(self.loan.term_months, 12)
        self.assertEqual(amendment.previous_values["term_months"], None)
        self.assertEqual(amendment.new_values["term_months"], 12)
        self.assertEqual(amendment.status, "approved")
        self.assertTrue(
            AuditLog.objects.filter(
                action="bt.loan.amendment_approved", subject_id=self.loan.id
            ).exists()
        )

    def test_csv_repayment_import_stages_applies_and_requires_admin_certification(self):
        self._fund_and_disburse()
        self._schedule()
        csv_content = (
            "loan_reference,payment_reference,payment_date,installment_number,"
            "total_amount,principal_amount,interest_amount,fee_amount,"
            "penalty_amount,evidence_reference\n"
            "LEDGER-LOAN-001,IMPORT-PAY-001,2026-02-01,1,550.00,500.00,"
            "50.00,0.00,0.00,IMPORT-BANK-EVIDENCE\n"
        ).encode()

        submission = lending_imports.stage_repayment_csv(
            mfi_id=self.mfi.id,
            reporting_month="2026-02-01",
            filename="repayments-2026-02.csv",
            content=csv_content,
            principal=self.mfi_admin,
        )
        submission = lending_imports.apply_repayment_import(
            submission.id, self.mfi_admin
        )
        submission = lending_imports.certify_portfolio_submission(
            submission.id, self.mfi_admin
        )

        self.assertEqual(submission.status, PortfolioSubmissionStatus.CERTIFIED)
        self.assertEqual(submission.rows.get().status, "applied")
        self.assertEqual(
            submission.rows.get().repayment_transaction.amount, Decimal("550.00")
        )
        self.assertEqual(
            lending_ledger.loan_position(self.loan)["outstandingPrincipal"],
            Decimal("500.00"),
        )

    def test_allocation_and_schedule_amount_invariants_are_enforced(self):
        self._fund_and_disburse()

        with self.assertRaises(BadRequest):
            lending_ledger.create_repayment_schedule(
                self.loan.id,
                [
                    {
                        "installmentNumber": 1,
                        "dueDate": "2026-02-01",
                        "principalDue": "999.99",
                        "interestDue": "0.00",
                        "feeDue": "0.00",
                    }
                ],
                self.mfi_admin,
            )

    def test_tranche_cannot_be_reversed_while_committed_to_a_loan(self):
        _, tranche, _, _ = self._fund_and_disburse()

        with self.assertRaises(ConflictError):
            lending_ledger.reverse_facility_tranche(
                tranche.id,
                {
                    "idempotencyKey": "receipt-reversal-001",
                    "reason": "Incorrect bank receipt",
                },
                self.accountant,
            )

        self.assertEqual(RepaymentTransaction.objects.count(), 0)
        self.assertEqual(FundingFacilityAllocation.objects.count(), 1)

    def test_purpose_use_impact_and_geography_keep_verified_and_missing_distinct(self):
        allocations = lending_impact.set_purpose_allocation_plan(
            self.loan.id,
            [
                {
                    "purposeId": self.purpose.id,
                    "plannedAmount": "1000.00",
                    "intendedOutput": "Working capital used for learning materials",
                }
            ],
            self.mfi_admin,
        )
        output = lending_impact.create_asset_output(
            allocations[0].id,
            {
                "assetType": "computer",
                "unit": "device",
                "plannedQuantity": 10,
                "learnerCapacity": 200,
            },
            self.mfi_admin,
        )
        teacher = lending_impact.record_teacher_beneficiary(
            self.loan.id,
            {
                "beneficiaryReference": "TEACHER-PRIVATE-HASH-1",
                "qualificationBefore": "Diploma",
                "institution": "Test University",
                "programme": "Bachelor of Education",
                "startedOn": "2026-01-01",
                "expectedCompletionOn": "2028-12-31",
                "programmeStatus": "enrolled",
                "fundingAmount": "1000.00",
                "evidenceReference": "ADMISSION-1",
            },
            self.mfi_admin,
        )
        baseline = lending_impact.capture_enrolment_snapshot(
            self.loan.id,
            {
                "kind": "baseline",
                "asOfDate": "2026-01-01",
                "learnerCount": 400,
                "cohortDefinition": "All enrolled learners at the financed school",
                "evidenceReference": "ENROLMENT-REGISTER-BASELINE",
            },
            self.mfi_admin,
        )
        self._fund_and_disburse()
        lending_impact.report_purpose_use(
            allocations[0].id, {"reportedAmount": "900.00"}, self.mfi_admin
        )
        lending_impact.verify_purpose_use(
            allocations[0].id,
            {"verifiedAmount": "850.00", "note": "Invoices sampled"},
            self.ia,
        )
        lending_impact.report_asset_output(
            output.id,
            {
                "reportedQuantity": 9,
                "reportedOperationalQuantity": 8,
                "completionState": "installed",
                "evidenceReference": "COMPUTER-INVOICES-AND-PHOTOS",
            },
            self.mfi_admin,
        )
        lending_impact.verify_asset_output(
            output.id,
            {
                "verifiedQuantity": 9,
                "verifiedOperationalQuantity": 8,
                "completionState": "verified functional",
            },
            self.ia,
        )
        lending_impact.report_teacher_progress(
            teacher.id,
            {
                "programmeStatus": "verification_pending",
                "completedOn": "2028-12-15",
                "evidenceReference": "DEGREE-CERTIFICATE-1",
            },
            self.mfi_admin,
        )
        lending_impact.verify_teacher_completion(teacher.id, {}, self.ia)
        follow_up = lending_impact.capture_enrolment_snapshot(
            self.loan.id,
            {
                "kind": "follow_up",
                "asOfDate": "2026-04-01",
                "learnerCount": 450,
                "cohortDefinition": "All enrolled learners at the financed school",
                "evidenceReference": "ENROLMENT-REGISTER-FOLLOWUP",
            },
            self.mfi_admin,
        )
        lending_impact.verify_enrolment_snapshot(baseline.id, {}, self.ia)
        lending_impact.verify_enrolment_snapshot(follow_up.id, {}, self.ia)
        requirement = LoanVerificationRequirement.objects.get(loan=self.loan)
        requirement.status = "verified"
        requirement.verified_at = timezone.now()
        requirement.save(update_fields=["status", "verified_at", "updated_at"])
        LoanUseResult.objects.create(
            requirement=requirement,
            finding=LoanUseFinding.FULLY_APPROVED,
            notes="Verified through governed evidence",
            recorded_by=self.mfi_admin.id,
            verification_status="confirmed",
            ia_verified_at=timezone.now(),
        )
        assessment = self.loan.impact_assessments.get()
        lending_impact.verify_loan_impact(
            assessment.id,
            {
                "classification": "positive",
                "narrative": "Verified outputs and learner observations improved.",
                "limitations": "Observed after financing; no causal counterfactual.",
                "evidenceReferences": ["SITE-VISIT-1", "FOLLOWUP-REGISTER"],
            },
            self.ia,
        )

        summary = lending_impact.impact_summary(self.ia)
        output_summary = lending_impact.purpose_output_summary(self.ia)
        equity = lending_impact.geographic_equity(self.rvp)

        self.assertEqual(summary["verifiedBaselineLoans"], 1)
        self.assertEqual(summary["verifiedFollowUpLoans"], 1)
        self.assertEqual(summary["verifiedLearnersObserved"], 450)
        self.assertEqual(output_summary["outputs"]["computer"]["verified"], 9)
        self.assertEqual(output_summary["outputs"]["computer"]["operational"], 8)
        self.assertEqual(output_summary["teachersVerifiedCompleted"], 1)
        assessment.refresh_from_db()
        self.assertEqual(assessment.classification, "positive")
        self.assertEqual(assessment.ia_status, "verified")
        self.assertTrue(equity["financialFieldsIncluded"])
        district_rows = {row["district"]: row for row in equity["rows"]}
        self.assertEqual(district_rows["Ledger District"]["dataState"], "observed")
        self.assertEqual(
            district_rows["Ledger District"]["confirmedDisbursedAmount"],
            "1000.00",
        )
        self.assertEqual(district_rows["Zero Lending District"]["dataState"], "zero")

    def test_new_purpose_requires_mfi_bt_ia_and_cd_separation(self):
        proposal = lending_impact.request_loan_purpose(
            {
                "code": "SOLAR_ENERGY",
                "name": "Solar Energy",
                "description": "School solar generation and storage",
                "businessReason": "Improve operating continuity",
                "expectedOutputs": "Installed solar generation capacity",
                "unit": "system",
                "requiredEvidence": ["invoice", "installation_photo"],
                "expectedImpact": "Reduced interruption from power outages",
                "exampleLoanReference": self.loan.external_loan_reference,
            },
            self.mfi_admin,
        )
        proposal = lending_impact.review_loan_purpose(
            proposal.id, {"note": "Operationally relevant."}, self.bt
        )
        proposal = lending_impact.define_loan_purpose_measurement(
            proposal.id,
            {
                "requiredEvidence": ["invoice", "installation_photo", "site_visit"],
                "impactIndicators": ["operational_systems", "uptime_hours"],
                "verificationMethod": "IA site verification",
            },
            self.ia,
        )
        purpose = lending_impact.approve_loan_purpose(
            proposal.id, {"applicableCountries": ["UG"]}, self.cd
        )

        self.assertTrue(purpose.active)
        self.assertTrue(purpose.measurement_profile_complete)
        self.assertEqual(purpose.verification_method, "IA site verification")
        self.assertEqual(purpose.applicable_countries, ["UG"])
