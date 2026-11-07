"""Loan Partners, and Loan among what a partner does (owner, 2026-11-06).

  "Add loan to the list of intervention to assign to the partner. Add loan
  partner as another partner role."
  "The loan feature is different from the school visits and training. It will
  follow the loan workflow."

Owner's answers the same day: Loan is a tick on the partner register's
Interventions list; Loan Partner is a kind of partner organisation beside the
Delivery Partners that take visits and trainings; loan work is a referral in
the loan workflow, never a visit.

So a Loan Partner is a lender in the loan workflow (``MfiOrganization``), and
is never offered a school visit or training hand-over.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.business_transformation.models import MfiOrganization
from apps.business_transformation.services import scoped_mfis
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.partners import capabilities
from apps.partners import services as partner_services
from apps.partners.models import Partner, PartnerRole
from apps.schools.models import School

User = get_user_model()


def _user(email: str, role: str) -> User:
    return User.objects.create_user(
        email=email,
        name=email.split("@")[0].title(),
        roles=[role],
        active_role=role,
        password="StrongPassphrase!23",
    )


class LoanInterventionTickTest(TestCase):
    def test_loan_is_offered_on_the_interventions_list(self):
        groups = capabilities.intervention_activity_options()
        loan = next(group for group in groups if group["key"] == capabilities.LOAN_KEY)
        self.assertEqual(loan["label"], "Loan")

    def test_a_ticked_loan_is_stored_but_never_becomes_the_ssa_column(self):
        chosen = capabilities.selected_capabilities([capabilities.LOAN_KEY], [])
        self.assertEqual(chosen["ssa_interventions"], [capabilities.LOAN_KEY])
        self.assertIsNone(chosen["ssa_intervention"])

    def test_the_profile_names_it_loan(self):
        partner = Partner(name="Lender", ssa_interventions=[capabilities.LOAN_KEY])
        self.assertEqual(
            capabilities.describe(partner)["interventions"],
            [{"key": capabilities.LOAN_KEY, "label": "Loan"}],
        )


class LoanPartnerRoleTest(TestCase):
    def setUp(self):
        self.admin = _user("loan-admin@edify.test", EdifyRole.ADMIN.value)

    def test_a_partner_is_a_delivery_partner_unless_told_otherwise(self):
        created = partner_services.onboard({"name": "Reading Trust"}, self.admin)
        partner = Partner.objects.get(id=created["id"])
        self.assertEqual(partner.partner_role, PartnerRole.DELIVERY)
        self.assertIsNone(partner.loan_lender_id)
        self.assertEqual(created["partnerRoleLabel"], "Delivery Partner")

    def test_a_loan_partner_becomes_a_lender_in_the_loan_workflow(self):
        created = partner_services.onboard(
            {"name": "Faith Finance", "partnerRole": "loan", "phone": "0700"},
            self.admin,
        )
        partner = Partner.objects.get(id=created["id"])
        self.assertEqual(partner.partner_role, PartnerRole.LOAN)
        lender = partner.loan_lender
        self.assertEqual(lender.name, "Faith Finance")
        self.assertTrue(lender.active)
        self.assertEqual(lender.contact_phone, "0700")
        # The loan workflow offers it as a lender for referrals.
        self.assertIn(lender, list(scoped_mfis(self.admin)))
        self.assertEqual(created["partnerRoleLabel"], "Loan Partner")

    def test_a_lender_already_in_the_loan_workflow_is_linked_not_copied(self):
        existing = MfiOrganization.objects.create(code="CFL", name="Christian Fund")
        created = partner_services.onboard(
            {"name": "christian fund", "partnerRole": "loan"}, self.admin
        )
        partner = Partner.objects.get(id=created["id"])
        self.assertEqual(partner.loan_lender_id, existing.id)
        self.assertEqual(MfiOrganization.objects.count(), 1)

    def test_two_loan_partners_with_similar_names_get_their_own_codes(self):
        partner_services.onboard(
            {"name": "Hope Loans", "partnerRole": "loan"}, self.admin
        )
        partner_services.onboard(
            {"name": "Hope Loans Ltd", "partnerRole": "loan"}, self.admin
        )
        codes = list(MfiOrganization.objects.values_list("code", flat=True))
        self.assertEqual(len(set(codes)), 2)

    def test_an_unknown_role_is_refused(self):
        with self.assertRaises(BadRequest):
            partner_services.onboard({"name": "Odd", "partnerRole": "bank"}, self.admin)
        self.assertFalse(Partner.objects.filter(name="Odd").exists())

    def test_the_directory_side_turns_a_partner_into_a_loan_partner(self):
        partner = Partner.objects.create(name="Grace Microfinance", active_status=True)
        partner_services.update(partner.id, {"partnerRole": "loan"}, self.admin)
        partner.refresh_from_db()
        self.assertEqual(partner.partner_role, PartnerRole.LOAN)
        self.assertEqual(partner.loan_lender.name, "Grace Microfinance")

    def test_a_partners_own_login_cannot_change_its_role(self):
        login = _user("own-partner@edify.test", EdifyRole.PARTNER_ADMIN.value)
        partner = Partner.objects.create(name="Own Partner", user=login)
        with self.assertRaises(Forbidden):
            partner_services.update(partner.id, {"partnerRole": "loan"}, login)
        partner.refresh_from_db()
        self.assertEqual(partner.partner_role, PartnerRole.DELIVERY)


class LoanPartnersTakeNoSchoolWorkTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="Loan Region")
        district = District.objects.create(name="Loan District", region=region)
        cls.school = School.objects.create(
            school_id="LOAN-1",
            name="Loan Primary",
            region=region,
            district=district,
            school_type="client",
        )
        cls.delivery = Partner.objects.create(name="Delivery Org", active_status=True)
        cls.lender = Partner.objects.create(
            name="Lender Org", active_status=True, partner_role=PartnerRole.LOAN
        )

    def test_hand_over_pickers_offer_delivery_partners_only(self):
        offered = list(partner_services.assignable_partners())
        self.assertIn(self.delivery, offered)
        self.assertNotIn(self.lender, offered)

    def test_a_visit_hand_over_to_a_loan_partner_is_refused(self):
        with self.assertRaisesMessage(BadRequest, "loan workflow"):
            partner_services.create_assignment(
                school=self.school,
                partner=self.lender,
                assigning_staff_id="loan-staff",
                expected_activity_type="school_visit_ssa_collection",
                purpose_of_visit="ssa_support",
            )


@override_settings(ALLOWED_HOSTS=["testserver", "localhost"])
class PartnerRegisterDrawersTest(TestCase):
    def setUp(self):
        self.admin = _user("drawer-admin@edify.test", EdifyRole.ADMIN.value)
        self.client.force_login(self.admin)

    def test_the_add_drawer_offers_the_role_and_saves_a_loan_partner(self):
        page = self.client.get(reverse("frontend:create_partner"))
        self.assertContains(page, 'name="partner_role"')
        self.assertContains(page, "Loan Partner")
        self.client.post(
            reverse("frontend:create_partner"),
            {"name": "Drawer Lender", "partner_role": "loan"},
        )
        partner = Partner.objects.get(name="Drawer Lender")
        self.assertEqual(partner.partner_role, PartnerRole.LOAN)
        self.assertIsNotNone(partner.loan_lender_id)

    def test_the_edit_drawer_changes_the_role(self):
        partner = Partner.objects.create(name="Edit Me", active_status=True)
        url = reverse("frontend:partner_edit_drawer", args=[partner.id])
        self.assertContains(self.client.get(url), 'name="partner_role"')
        self.client.post(url, {"name": "Edit Me", "partner_role": "loan"})
        partner.refresh_from_db()
        self.assertEqual(partner.partner_role, PartnerRole.LOAN)
        self.assertIsNotNone(partner.loan_lender_id)
