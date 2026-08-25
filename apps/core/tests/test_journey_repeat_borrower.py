"""Journey 18 — Repeat borrower and student reach, walked end to end.

Journey 18 of the mandate's twenty-two: Second loan, Loan count increases,
Unique school does not duplicate, Student reach does not duplicate, Loan
history remains correct.

Four of its five steps are counting rules, and two of them are stated as
things that must NOT happen. That is the same shape as TGT-03, which this
audit already found and fixed: annual "unique schools" figures summed
per-month distinct counts, so a school reached twice was counted twice. The
defect class is established in this platform; Journey 18 asks whether it also
lives in the lending domain, where the same school genuinely can take a second
loan and where double-counting learners would overstate the programme's
headline impact figure.

The aggregation looks right by inspection — `Count("loan__school_id",
distinct=True)` for schools, and learners summed per school rather than per
loan. Inspection is not evidence. This finances one school twice through the
real ledger — facility, tranche, allocation, disbursement, verified enrolment
baseline — and then reads the portfolio metrics a leadership page would show.
"""

from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import User
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School

from apps.business_transformation import lending_impact, lending_ledger, services
from apps.business_transformation.models import (
    LoanPurpose,
    LoanStatus,
    MfiLoan,
    MfiMembership,
    MfiMembershipRole,
    MfiOrganization,
    TransformationCase,
)

LEARNERS = 400


class RepeatBorrowerJourneyTest(TestCase):
    """One school, two loans — count the loans twice and the school once."""

    @classmethod
    def setUpTestData(cls):
        def _user(email, name, role):
            return User.objects.create_user(
                email=email, name=name, roles=[role], active_role=role
            )

        cls.bt = _user(
            "rb-bt@example.org",
            "RB BT",
            EdifyRole.BUSINESS_TRANSFORMATION_OFFICER.value,
        )
        cls.cd = _user("rb-cd@example.org", "RB CD", EdifyRole.COUNTRY_DIRECTOR.value)
        cls.accountant = _user(
            "rb-acct@example.org", "RB Accountant", EdifyRole.PROGRAM_ACCOUNTANT.value
        )
        cls.ia = _user("rb-ia@example.org", "RB IA", EdifyRole.IMPACT_ASSESSMENT.value)
        cls.mfi_admin = _user(
            "rb-mfi@example.org", "RB MFI Admin", EdifyRole.MFI_PARTNER_ADMIN.value
        )

        cls.mfi = MfiOrganization.objects.create(
            code="RB-MFI", name="RB MFI", country_code="UG"
        )
        MfiMembership.objects.create(
            mfi=cls.mfi, user=cls.mfi_admin, role=MfiMembershipRole.ADMIN
        )
        cls.region = Region.objects.create(name="RB Region")
        cls.district = District.objects.create(name="RB District", region=cls.region)
        cls.school = School.objects.create(
            school_id="UG-RB-001",
            name="RB School",
            region=cls.region,
            district=cls.district,
        )
        cls.case = TransformationCase.objects.create(
            school=cls.school, status="active", opened_fy="2026"
        )
        cls.purpose = LoanPurpose.objects.create(
            code="RB-WC", label="RB working capital"
        )

    def setUp(self):
        self.facility = lending_ledger.approve_funding_facility(
            lending_ledger.create_funding_facility(
                {
                    "mfiId": self.mfi.id,
                    "externalReference": "RB-FAC-001",
                    "name": "RB Growth Facility",
                    "commitmentAmount": "5000.00",
                    "currency": "UGX",
                    "countryCode": "UG",
                    "revolving": True,
                    "startsOn": "2026-01-01",
                    "endsOn": "2027-12-31",
                    "agreementReference": "RB-AGREEMENT-001",
                },
                self.bt,
            ).id,
            self.cd,
        )
        lending_ledger.confirm_facility_tranche(
            {
                "facilityId": self.facility.id,
                "externalReference": "RB-BANK-IN-001",
                "idempotencyKey": "rb-receipt-001",
                "amount": "5000.00",
                "receivedOn": "2026-01-02",
                "valueDate": "2026-01-02",
                "evidenceReference": "RB-NETSUITE-001",
            },
            self.accountant,
        )

    def _finance(
        self, *, reference: str, amount: str, seq: int, on: str, learners=None
    ):
        """One complete loan to THE SAME school, through the real ledger."""
        loan = MfiLoan.objects.create(
            mfi=self.mfi,
            school=self.school,
            case=self.case,
            purpose=self.purpose,
            external_loan_reference=reference,
            approved_amount=Decimal(amount),
            currency="UGX",
            status=LoanStatus.PROCESSING,
            registered_by=self.mfi_admin.id,
        )
        lending_impact.set_purpose_allocation_plan(
            loan.id,
            [
                {
                    "purposeId": self.purpose.id,
                    "plannedAmount": amount,
                    "intendedOutput": f"Output for {reference}",
                }
            ],
            self.mfi_admin,
        )
        if learners is not None:
            baseline = lending_impact.capture_enrolment_snapshot(
                loan.id,
                {
                    "kind": "baseline",
                    "asOfDate": on,
                    "learnerCount": learners,
                    "cohortDefinition": f"All learners at {reference}",
                    "evidenceReference": f"ENROL-{reference}",
                },
                self.mfi_admin,
            )
            lending_impact.verify_enrolment_snapshot(baseline.id, {}, self.ia)
        lending_ledger.reserve_facility_for_loan(
            {
                "facilityId": self.facility.id,
                "loanId": loan.id,
                "amount": amount,
                "idempotencyKey": f"rb-allocation-{seq}",
            },
            self.bt,
        )
        lending_ledger.post_loan_disbursement(
            {
                "loanId": loan.id,
                "sequence": 1,
                "externalReference": f"RB-BANK-OUT-{seq}",
                "idempotencyKey": f"rb-disbursement-{seq}",
                "amount": amount,
                "disbursedOn": on,
                "valueDate": on,
                "bankReference": f"RB-BANK-OUT-{seq}",
            },
            self.mfi_admin,
        )
        return loan

    def _metrics(self):
        return services.portfolio_metrics(self.cd, fy="2026")

    def test_a_second_loan_to_one_school_counts_twice_but_the_school_once(self):
        # ── First loan, with a verified enrolment baseline ────────────────
        first = self._finance(
            reference="RB-LOAN-001",
            amount="1000.00",
            seq=1,
            on="2026-01-03",
            learners=LEARNERS,
        )
        before = self._metrics()
        self.assertEqual(before["loansDisbursed"], 1)
        self.assertEqual(before["schoolsImpacted"], 1)
        self.assertEqual(
            before["studentsReached"],
            LEARNERS,
            "the fixture's verified baseline never reached the reach figure, "
            "so the no-duplication assertions below would hold over nothing",
        )

        # ── 1. Second loan, same school ───────────────────────────────────
        # Every disbursed loan must carry its own verified enrolment
        # baseline — post_loan_disbursement refuses without one — so the
        # repeat loan brings a second baseline for the SAME school. That is
        # precisely the condition under which a per-loan sum would double the
        # reach, which is why it is the real scenario rather than a contrived
        # one.
        second = self._finance(
            reference="RB-LOAN-002",
            amount="400.00",
            seq=2,
            on="2026-02-03",
            learners=LEARNERS,
        )
        after = self._metrics()

        # ── 2. Loan count increases ───────────────────────────────────────
        self.assertEqual(
            after["loansDisbursed"],
            2,
            "the second loan to an existing borrower was not counted — a "
            "repeat borrower is still a loan",
        )

        # ── 3. Unique school does not duplicate ───────────────────────────
        # The TGT-03 shape, in the lending domain.
        self.assertEqual(
            after["schoolsImpacted"],
            1,
            "financing the same school twice counted it as two schools — the "
            "programme's reach is overstated by every repeat borrower",
        )
        self.assertEqual(after["schoolsFinanced"], 1)

        # ── 4. Student reach does not duplicate ───────────────────────────
        self.assertEqual(
            after["studentsReached"],
            LEARNERS,
            "the school's learners were counted once per loan rather than "
            "once per school — the headline impact figure grows every time an "
            "existing borrower takes more money",
        )
        self.assertEqual(after["verifiedLearnersObserved"], LEARNERS)
        self.assertEqual(
            after["schoolsWithEnrollment"],
            1,
            "one school with a verified baseline was reported as more than one",
        )

        # ── 5. Loan history remains correct ───────────────────────────────
        self.assertEqual(
            MfiLoan.objects.filter(school=self.school).count(),
            2,
            "the second loan replaced the first rather than joining it",
        )
        for loan in (first, second):
            loan.refresh_from_db()
            self.assertEqual(loan.school_id, self.school.id)
        self.assertEqual(
            after["valueDisbursed"],
            Decimal("1400.00"),
            "the disbursed value does not equal both loans together",
        )

    def test_a_later_baseline_replaces_the_earlier_one_rather_than_adding(self):
        """Which figure is reported when a school has two verified baselines.

        `portfolio_metrics` takes the baseline closest to the financing event,
        ordering by `-as_of_date`. Giving the two baselines DIFFERENT learner
        counts is what makes this test able to fail: with equal counts, "sums
        them" and "takes one" are indistinguishable, and the assertion would
        pass against either behaviour.
        """
        self._finance(
            reference="RB-LOAN-101",
            amount="1000.00",
            seq=11,
            on="2026-01-03",
            learners=300,
        )
        self._finance(
            reference="RB-LOAN-102",
            amount="400.00",
            seq=12,
            on="2026-02-03",
            learners=520,
        )
        after = self._metrics()
        self.assertEqual(after["loansDisbursed"], 2)
        self.assertEqual(after["schoolsImpacted"], 1)
        self.assertNotEqual(
            after["studentsReached"],
            820,
            "the two verified baselines for one school were added together — "
            "every repeat borrower inflates the headline reach figure",
        )
        self.assertEqual(
            after["studentsReached"],
            520,
            "the reported reach is neither baseline's count: it should be the "
            "one closest to the financing event",
        )
        self.assertEqual(after["schoolsWithEnrollment"], 1)
