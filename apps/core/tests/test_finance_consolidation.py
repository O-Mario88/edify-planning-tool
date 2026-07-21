"""Finance: one payout path, one filter, one workspace.

The Disbursement Dashboard's partner payout re-implemented the payment inline
and enforced only the blocked-reason check. It had no cross-channel guard, no
idempotency check, wrote no PartnerPayment ledger row and no finance audit
entry — so its payouts were invisible to the very guard protecting the other
channel. Four surfaces also each carried their own "payable" filter, so the
same queue showed different rows and totals depending on the page.
"""

from __future__ import annotations

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.rbac import EdifyRole
from apps.fund_requests.finance_services import (
    PARTNER_PAID_STATUSES,
    PARTNER_PAYABLE_STATUSES,
    PartnerPaymentService,
)
from apps.fund_requests.models import PartnerPayment
from apps.geography.models import District, Region
from apps.partners.models import Partner
from apps.schools.models import School


def _user(email, name, role):
    return User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="pw12345678",
        is_active=True,
    )


class PartnerPaymentGuardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Fin Region")
        district = District.objects.create(name="Fin District", region=region)
        cls.school = School.objects.create(
            name="Fin Primary",
            school_id="FN-1",
            region_id=region.id,
            district_id=district.id,
        )
        cls.partner = Partner.objects.create(name="Fin Partner")

    def setUp(self):
        self.acct = _user("acct-fin@t.org", "Ada", EdifyRole.PROGRAM_ACCOUNTANT.value)
        StaffProfile.objects.create(
            user=self.acct, title="Accountant", country="Uganda"
        )
        self.act = Activity.objects.create(
            school_id=self.school.id,
            activity_type="school_visit",
            status="ia_verified",
            delivery_type="partner",
            assigned_partner_id=self.partner.id,
            payment_status="ia_confirmed",
            evidence_status="accepted",
            salesforce_activity_id="SVE-FIN-1",
            ia_verification_status="confirmed",
            fy="2026",
            quarter="Q4",
            planned_date=timezone.now(),
        )
        # The gate reads real records, not the denormalised status fields: a
        # non-quarantined EvidenceRecord and at least one cost line.
        from apps.evidence.models import EvidenceRecord

        EvidenceRecord.objects.create(
            activity_id=self.act.id,
            kind="photo",
            uri="visit.jpg",
            original_name="visit.jpg",
            uploaded_by=self.acct.user_id,
            quarantined=False,
        )
        self.cost_line = ActivityScheduleCostLine.objects.create(
            activity=self.act,
            cost_setting_key="partner_visit_lump_sum",
            label="Partner Visit",
            unit_cost=35_000,
            amount=35_000,
        )

    def _pay(self):
        return PartnerPaymentService.pay_partner(
            activity=self.act,
            partner_name=self.partner.name,
            amount=35_000,
            method="bank_transfer",
            reference="REF-1",
            user_id=self.acct.user_id,
            netsuite_id="NS-FIN-1",
        )

    def test_payment_writes_a_ledger_row(self):
        self._pay()
        self.assertTrue(PartnerPayment.objects.filter(activity=self.act).exists())

    def test_a_second_payout_is_refused(self):
        self._pay()
        with self.assertRaises(ValueError) as ctx:
            self._pay()
        self.assertIn("already recorded", str(ctx.exception).lower())

    def test_advance_funded_work_cannot_also_be_partner_paid(self):
        """The cross-channel guard the inline implementation lacked entirely."""
        from apps.fund_requests.models import AdvanceRequest

        AdvanceRequest.objects.create(
            activity=self.act,
            budget_line=self.cost_line,
            fy="2026",
            quarter="Q4",
            planned_date=timezone.now(),
            amount=35_000,
            status="disbursed",
            disbursed_amount=35_000,
        )
        with self.assertRaises(ValueError) as ctx:
            self._pay()
        self.assertIn("advance channel", str(ctx.exception).lower())

    def test_the_dashboard_route_uses_the_canonical_service(self):
        """Not a re-implementation — the guards must be shared."""
        import inspect

        from apps.frontend.views import finance_views

        source = inspect.getsource(finance_views.clear_partner_payment_action)
        self.assertIn("PartnerPaymentService.pay_partner", source)
        self.assertNotIn(
            "NetSuiteExpenseRecord.objects.update_or_create",
            source,
            "the payout must not write finance records inline",
        )


class PartnerFilterUnificationTests(TestCase):
    """Four surfaces, four different definitions of the same queue."""

    def test_one_shared_payable_definition(self):
        self.assertEqual(PARTNER_PAYABLE_STATUSES, ("none", "ia_confirmed"))
        self.assertEqual(PARTNER_PAID_STATUSES, ("disbursed", "paid"))

    def test_surfaces_import_the_constant_rather_than_inlining(self):
        import inspect

        from apps.frontend.views import finance_operating_views
        from apps.fund_requests import disbursement_dashboard_service

        for module in (finance_operating_views, disbursement_dashboard_service):
            source = inspect.getsource(module)
            self.assertIn("PARTNER_PAYABLE_STATUSES", source)
            self.assertNotIn(
                'payment_status__in=["none", "ia_confirmed"]',
                source,
                f"{module.__name__} still inlines the payable filter",
            )


class AccountantWorkspaceReachableTests(TestCase):
    """The Accountant's primary page had no sidebar entry at all."""

    def test_disbursement_dashboard_is_in_the_sidebar(self):
        from apps.core.navigation import build_sidebar_for_user

        acct = _user("acct-nav@t.org", "Ada", EdifyRole.PROGRAM_ACCOUNTANT.value)
        urls = [
            item["url"]
            for section in build_sidebar_for_user(acct, "/dashboard")
            for item in section["items"]
        ]
        self.assertIn("/disbursements", urls)

    def test_field_roles_do_not_see_it(self):
        from apps.core.navigation import build_sidebar_for_user

        cceo = _user("cceo-nav@t.org", "Cara", EdifyRole.CCEO.value)
        urls = [
            item["url"]
            for section in build_sidebar_for_user(cceo, "/dashboard")
            for item in section["items"]
        ]
        self.assertNotIn("/disbursements", urls)
