"""SEC-A5 — one MFI must never read another's loan book.

`tests.py` already pins *which roles* may reach the record-level loan API, and
that is the half a role list can express. It does not build two tenants, so
nothing in the suite fails if `scoped_loans` or `_mfi_ids_for` ever stops
filtering by membership — the restricted-role tests would still pass while
every MFI read every other MFI's portfolio.

The mandate names cross-partner exposure a stop-the-line defect, so the
invariant is pinned here against real HTTP responses rather than by calling the
scoping function and agreeing with it.

Two properties, both currently correct:

* An MFI admin sees their own tenant's loans and nothing else.
* A loan officer sees the records they own, NOT the whole tenant portfolio —
  `_loan_officer_scope` says so in its own docstring ("Records owned by this
  loan officer, never the whole MFI portfolio"), and that is a narrower claim
  than tenancy alone.
"""

from __future__ import annotations

from decimal import Decimal

from django.test import Client, TestCase

from apps.accounts.models import StaffProfile, User
from apps.business_transformation.models import (
    LoanPurpose,
    MfiLoan,
    MfiMembership,
    MfiMembershipRole,
    MfiOrganization,
    TransformationCase,
)
from apps.geography.models import District, Region
from apps.schools.models import School


class MfiTenancyIsolationTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Tenancy Region")
        district = District.objects.create(name="Tenancy District", region=region)
        purpose = LoanPurpose.objects.create(code="TEN_CLASSROOM", label="Classrooms")

        cls.mfi_a = MfiOrganization.objects.create(code="TEN_A", name="Alpha MFI")
        cls.mfi_b = MfiOrganization.objects.create(code="TEN_B", name="Beta MFI")

        cls.admin_a = cls._user("tenancy-a-admin", "MfiPartnerAdmin")
        cls.admin_b = cls._user("tenancy-b-admin", "MfiPartnerAdmin")
        cls.officer_a1 = cls._user("tenancy-a-off1", "MfiLoanOfficer")
        cls.officer_a2 = cls._user("tenancy-a-off2", "MfiLoanOfficer")

        for mfi, user, role in (
            (cls.mfi_a, cls.admin_a, MfiMembershipRole.ADMIN),
            (cls.mfi_b, cls.admin_b, MfiMembershipRole.ADMIN),
            (cls.mfi_a, cls.officer_a1, MfiMembershipRole.LOAN_OFFICER),
            (cls.mfi_a, cls.officer_a2, MfiMembershipRole.LOAN_OFFICER),
        ):
            MfiMembership.objects.create(mfi=mfi, user=user, role=role)

        def loan(mfi, reference, registered_by):
            school = School.objects.create(
                school_id=f"TEN-{reference}",
                name=f"Tenancy School {reference}",
                region=region,
                district=district,
            )
            case = TransformationCase.objects.create(school=school, opened_fy="2027")
            return MfiLoan.objects.create(
                mfi=mfi,
                school=school,
                case=case,
                purpose=purpose,
                external_loan_reference=reference,
                registered_by=registered_by.id,
                approved_amount=Decimal("1000.00"),
                disbursed_amount=Decimal("1000.00"),
            )

        loan(cls.mfi_a, "A-1", cls.officer_a1)
        loan(cls.mfi_a, "A-2", cls.officer_a2)
        loan(cls.mfi_b, "B-1", cls.admin_b)

    @classmethod
    def _user(cls, slug: str, role: str) -> User:
        user = User.objects.create(
            email=f"{slug}@edify.test",
            name=slug,
            roles=[role],
            active_role=role,
            is_active=True,
        )
        StaffProfile.objects.create(user=user, title=role)
        return user

    def _references(self, user) -> set[str]:
        client = Client()
        client.force_login(user)
        response = client.get("/api/business-transformation/loans")
        self.assertEqual(response.status_code, 200, user.active_role)
        return {row["externalLoanReference"] for row in response.json()}

    def test_an_mfi_admin_reads_only_their_own_tenant(self):
        self.assertEqual(self._references(self.admin_a), {"A-1", "A-2"})

    def test_the_second_mfi_never_sees_the_first_ones_book(self):
        """The property a one-tenant fixture cannot show."""
        self.assertEqual(self._references(self.admin_b), {"B-1"})

    def test_a_loan_officer_sees_their_own_records_not_the_portfolio(self):
        self.assertEqual(self._references(self.officer_a1), {"A-1"})
        self.assertEqual(self._references(self.officer_a2), {"A-2"})
