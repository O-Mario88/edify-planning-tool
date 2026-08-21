from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.command_center.todo_service import _business_transformation_todos
from apps.core.enums import ActivityStatus, SsaIntervention
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.navigation import PAGE_PERMISSIONS, build_sidebar_for_user
from apps.core.rbac import EdifyRole, Permission, permissions_for_role
from apps.outbox.models import OutboxEvent
from apps.outbox.services import drain
from apps.integrations.models import IntegrationSync, IntegrationSyncStatus
from apps.notifications.models import Notification
from apps.partners.models import Partner, PartnerAssignment
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

from . import lending_impact, lending_ledger, services
from .models import (
    CaseRecommendation,
    FinanceReferral,
    FundingFacility,
    FundingFacilityStatus,
    FundingFacilityTranche,
    IAValidationStatus,
    LoanPurpose,
    LoanStatus,
    LoanStatusHistory,
    LoanUseFinding,
    LoanVerificationRequirement,
    MfiLoan,
    MfiMembership,
    MfiMembershipRole,
    MfiOrganization,
    ReferralStatus,
    RepaymentSnapshot,
    SalesforceStatus,
    SalesforceConfirmation,
    TransformationCase,
    VerificationRequirementStatus,
)


class UgandaBusinessTransformationTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(
            school_id="UG-BT-001", name="Kampala Hope School"
        )
        cls.bt_user = User.objects.create_user(
            email="bt@example.org",
            name="Uganda BT Officer",
            roles=[EdifyRole.BUSINESS_TRANSFORMATION_OFFICER.value],
            active_role=EdifyRole.BUSINESS_TRANSFORMATION_OFFICER.value,
        )


class GovernedUgandaLoanPurposeTests(TestCase):
    def test_active_purposes_are_the_specific_uganda_categories(self):
        expected = {
            "LAND_EXPANSION": ("Land for Expansion", False),
            "CLASSROOM_CONSTRUCTION": ("Classroom Construction", False),
            "DORMITORY_CONSTRUCTION": ("Dormitory Construction", False),
            "SCHOOL_VAN": ("School Van", False),
            "SCHOOL_BUS": ("School Bus", False),
            "EDTECH_COMPUTER_LAB": ("EdTech - Computer Lab", True),
        }
        actual = {
            purpose.code: (purpose.label, purpose.is_edtech)
            for purpose in LoanPurpose.objects.filter(code__in=expected)
        }

        self.assertEqual(actual, expected)
        self.assertFalse(
            LoanPurpose.objects.filter(
                code__in={
                    "EDTECH",
                    "INFRASTRUCTURE",
                    "WORKING_CAPITAL",
                    "SCHOOL_EQUIPMENT",
                    "COMPLIANCE",
                    "OTHER",
                },
                active=True,
            ).exists()
        )


class VerifiedSsaTriggerTests(UgandaBusinessTransformationTestCase):
    def _ssa(self, financial=5.0, government=4.0):
        record = SsaRecord.objects.create(
            school=self.school,
            date_of_ssa=timezone.now(),
            fy="2026",
            quarter="Q4",
            verification_status="confirmed",
            verified_by_user_id=self.bt_user.id,
            verified_at=timezone.now(),
            uploaded_by=self.bt_user.id,
        )
        SsaScore.objects.bulk_create(
            [
                SsaScore(
                    ssa_record=record,
                    intervention=SsaIntervention.FINANCIAL_HEALTH,
                    score=financial,
                ),
                SsaScore(
                    ssa_record=record,
                    intervention=SsaIntervention.GOVERNMENT_REQUIREMENT,
                    score=government,
                ),
            ]
        )
        return record

    def test_confirmed_weak_ssa_converges_to_one_case_and_recommendation_set(self):
        record = self._ssa()

        first = services.ensure_case_from_verified_ssa(record.id)
        second = services.ensure_case_from_verified_ssa(record.id)

        self.assertEqual(first.id, second.id)
        self.assertEqual(TransformationCase.objects.count(), 1)
        self.assertEqual(CaseRecommendation.objects.count(), 3)
        self.assertSetEqual(
            set(CaseRecommendation.objects.values_list("kind", flat=True)),
            {
                "financial_health_training",
                "loan_readiness",
                "compliance_support",
            },
        )

    def test_scores_above_policy_threshold_do_not_create_a_case(self):
        record = self._ssa(financial=7.0, government=8.0)

        self.assertIsNone(services.ensure_case_from_verified_ssa(record.id))
        self.assertFalse(TransformationCase.objects.exists())

    def test_ssa_signal_reaches_case_service_through_durable_outbox(self):
        record = self._ssa()

        self.assertTrue(
            OutboxEvent.objects.filter(
                event_type="bt.ssa.confirmed",
                payload__ssaRecordId=record.id,
            ).exists()
        )
        result = drain(batch_size=10, time_budget_seconds=5, worker_id="bt-test")

        self.assertGreaterEqual(result["succeeded"], 1)
        self.assertTrue(TransformationCase.objects.filter(school=self.school).exists())


class UgandaBusinessTransformationFrontendTests(UgandaBusinessTransformationTestCase):
    def test_bt_officer_can_open_uganda_workspace_and_school_360_section(self):
        self.client.force_login(self.bt_user)

        workspace = self.client.get("/business-transformation")
        portfolio = self.client.get("/business-transformation/portfolio")
        school_profile = self.client.get(f"/schools/{self.school.school_id}")

        self.assertEqual(workspace.status_code, 200)
        self.assertContains(workspace, "Uganda portfolio")
        self.assertEqual(workspace.content.count(b"<main"), 1)
        self.assertContains(workspace, 'class="edify-filter-bar"')
        # One search per page: the shell's top-bar input joins the filter
        # form via form= instead of a body search living in the bar itself.
        self.assertContains(workspace, 'form="bt-workspace-filters"')
        # The platform headline policy deliberately removes the former
        # eleven-card inventory and keeps one professional four-metric tray.
        self.assertContains(workspace, 'data-component="kpi-card"', count=4)
        self.assertNotContains(workspace, "text-[11px]")
        self.assertEqual(portfolio.status_code, 200)
        self.assertContains(portfolio, "MFI referral pipeline")
        self.assertEqual(school_profile.status_code, 200)
        self.assertContains(school_profile, "Business Transformation")

    def test_operational_loan_register_uses_only_two_position_kpis(self):
        self.client.force_login(self.bt_user)

        response = self.client.get("/loans")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-component="kpi-card"', count=2)


class TransformationSchoolPortfolioTests(UgandaBusinessTransformationTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.other_school = School.objects.create(
            school_id="UG-BT-002", name="Luwero Future School"
        )
        cls.partner = Partner.objects.create(name="Uganda School Business Partner")
        PartnerAssignment.objects.create(
            school=cls.school,
            partner=cls.partner,
            focus_intervention=SsaIntervention.FINANCIAL_HEALTH,
            status=PartnerAssignment.STATUS_ASSIGNED,
        )
        PartnerAssignment.objects.create(
            school=cls.other_school,
            partner=cls.partner,
            focus_intervention=SsaIntervention.FINANCIAL_HEALTH,
            status=PartnerAssignment.STATUS_ASSIGNED,
        )
        PartnerAssignment.objects.create(
            school=cls.school,
            partner=cls.partner,
            focus_intervention=SsaIntervention.GOVERNMENT_REQUIREMENT,
            status=PartnerAssignment.STATUS_ASSIGNED,
        )
        cls.cceo = User.objects.create_user(
            email="bt-portfolio-cceo@example.org",
            name="Portfolio CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
        )
        cls.cceo_staff = StaffProfile.objects.create(
            user=cls.cceo, onboarding_state="active"
        )
        StaffSchoolAssignment.objects.create(
            staff=cls.cceo_staff, school_id=cls.school.id
        )

    def test_partner_assigned_school_appears_without_a_bt_case(self):
        self.assertFalse(TransformationCase.objects.filter(school=self.school).exists())

        context = services.financial_health_context(self.bt_user, {})

        self.assertSetEqual(
            {row["school_id"] for row in context["rows"]},
            {self.school.school_id, self.other_school.school_id},
        )
        self.assertEqual(context["metrics"]["partnerAssigned"], 2)

    def test_cceo_manages_only_the_relevant_schools_in_operational_scope(self):
        context = services.financial_health_context(self.cceo, {})

        self.assertEqual(
            [row["school_id"] for row in context["rows"]], [self.school.school_id]
        )
        self.assertTrue(context["rows"][0]["can_manage"])
        self.assertTrue(context["rows"][0]["can_plan"])
        self.assertTrue(
            Permission.BUSINESS_TRANSFORMATION_SCHOOL_SUPPORT_MANAGE.value
            in permissions_for_role(EdifyRole.CCEO)
        )
        self.assertNotIn(
            Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE.value,
            permissions_for_role(EdifyRole.CCEO),
        )

    def test_bt_government_requirements_uses_the_school_list_contract(self):
        self.client.force_login(self.bt_user)

        response = self.client.get("/business-transformation/government-requirements")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Government Requirements portfolio")
        self.assertContains(response, "school-record-list")
        self.assertContains(response, self.school.name)

    def test_bt_is_read_only_except_for_salesforce_confirmation(self):
        context = services.government_requirements_context(self.bt_user, {})
        bt_permissions = set(
            permissions_for_role(EdifyRole.BUSINESS_TRANSFORMATION_OFFICER)
        )

        self.assertFalse(context["rows"][0]["can_manage"])
        self.assertFalse(context["rows"][0]["can_plan"])
        self.assertIn(
            Permission.BUSINESS_TRANSFORMATION_SALESFORCE_CONFIRM.value,
            bt_permissions,
        )
        for write_permission in (
            Permission.PLANNING_CREATE,
            Permission.MANUAL_ACTIVITY_CREATE,
            Permission.ACTIVITY_ASSIGN,
            Permission.ACTIVITY_COMPLETE,
            Permission.EVIDENCE_REVIEW,
            Permission.BUSINESS_TRANSFORMATION_CASE_MANAGE,
            Permission.BUSINESS_TRANSFORMATION_SCHOOL_SUPPORT_MANAGE,
            Permission.BUSINESS_TRANSFORMATION_REFERRAL_MANAGE,
            Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE,
            Permission.BUSINESS_TRANSFORMATION_REPAYMENT_WRITE,
            Permission.BUSINESS_TRANSFORMATION_PORTFOLIO_CERTIFY,
            Permission.BUSINESS_TRANSFORMATION_IA_VALIDATE,
        ):
            self.assertNotIn(write_permission.value, bt_permissions)
        for role in (
            EdifyRole.CCEO,
            EdifyRole.COUNTRY_PROGRAM_LEAD,
        ):
            self.assertIn(
                Permission.BUSINESS_TRANSFORMATION_SCHOOL_SUPPORT_MANAGE.value,
                permissions_for_role(role),
            )

        self.client.force_login(self.bt_user)
        response = self.client.get("/business-transformation/government-requirements")
        self.assertContains(response, "View support for")
        self.assertNotContains(response, "Monitor support for")
        self.assertNotContains(response, "Plan support for")

    def test_performance_uses_confirmed_baseline_and_latest_ssa(self):
        for index, score in enumerate((3.0, 6.0), start=1):
            record = SsaRecord.objects.create(
                school=self.school,
                date_of_ssa=timezone.now() + timedelta(days=index),
                fy="2026",
                quarter=f"Q{index}",
                verification_status="confirmed",
                verified_by_user_id=self.bt_user.id,
                verified_at=timezone.now(),
                uploaded_by=self.bt_user.id,
            )
            SsaScore.objects.create(
                ssa_record=record,
                intervention=SsaIntervention.FINANCIAL_HEALTH,
                score=score,
            )

        context = services.financial_health_context(self.bt_user, {"q": "Kampala"})

        self.assertEqual(context["rows"][0]["performance"]["label"], "Improving")
        self.assertEqual(context["rows"][0]["performance"]["movement"], 3.0)


class LoanRoleAccessContractTests(UgandaBusinessTransformationTestCase):
    record_level_roles = {
        EdifyRole.BUSINESS_TRANSFORMATION_OFFICER,
        EdifyRole.COUNTRY_DIRECTOR,
        EdifyRole.IMPACT_ASSESSMENT,
        EdifyRole.REGIONAL_VICE_PRESIDENT,
        EdifyRole.MFI_PARTNER_ADMIN,
        EdifyRole.MFI_LOAN_OFFICER,
    }
    full_access_roles = {
        EdifyRole.MFI_PARTNER_ADMIN,
        EdifyRole.MFI_LOAN_OFFICER,
    }
    export_roles = {
        EdifyRole.COUNTRY_DIRECTOR,
        EdifyRole.IMPACT_ASSESSMENT,
        EdifyRole.BUSINESS_TRANSFORMATION_OFFICER,
        EdifyRole.REGIONAL_VICE_PRESIDENT,
    }

    def test_loan_dashboard_exposes_only_the_primary_filters(self):
        self.client.force_login(self.bt_user)

        response = self.client.get(
            "/loans",
            {
                "fy": "2026",
                "purpose": "retired-purpose-filter",
                "period_type": "month",
                "custom_from": "2026-01-01",
            },
        )

        for control_id in (
            "loan-fy",
            "loan-mfi-filter",
            "loan-district-filter",
            "loan-status-filter",
            "loan-repayment-filter",
            "loan-salesforce-filter",
        ):
            with self.subTest(primary_filter=control_id):
                self.assertContains(response, f'id="{control_id}"')

        for control_id in (
            "loan-period-type",
            "loan-quarter",
            "loan-month",
            "loan-region",
            "loan-school-filter",
            "loan-purpose-filter",
            "loan-edtech-filter",
            "loan-ia-filter",
            "loan-impact-filter",
            "loan-custom-from",
            "loan-custom-to",
        ):
            with self.subTest(retired_filter=control_id):
                self.assertNotContains(response, f'id="{control_id}"')

        self.assertNotIn("purpose", response.context["filters"])
        self.assertNotIn("period_type", response.context["filters"])
        self.assertNotIn("custom_from", response.context["filters"])
        self.assertEqual(response.context["filter_query"], "fy=2026")

    def test_only_record_level_lending_roles_have_the_loans_page(self):
        for index, role in enumerate(EdifyRole):
            user = User.objects.create_user(
                email=f"loan-nav-{index}@example.org",
                name=f"{role.name} Loan Reader",
                roles=[role.value],
                active_role=role.value,
            )
            self.client.force_login(user)

            response = self.client.get("/loans")
            sidebar_urls = {
                item["url"]
                for section in build_sidebar_for_user(user, "/loans")
                for item in section["items"]
            }

            with self.subTest(role=role.value):
                if role not in self.record_level_roles:
                    self.assertEqual(response.status_code, 302)
                    self.assertNotIn("/loans", sidebar_urls)
                    continue
                self.assertEqual(response.status_code, 200)
                expected_url = (
                    "/mfi-portal/loans"
                    if role
                    in {
                        EdifyRole.MFI_PARTNER_ADMIN,
                        EdifyRole.MFI_LOAN_OFFICER,
                    }
                    else "/loans"
                )
                self.assertIn(expected_url, sidebar_urls)

    def test_restricted_roles_cannot_read_the_record_level_loan_api(self):
        restricted = set(EdifyRole) - self.record_level_roles
        for index, role in enumerate(sorted(restricted, key=lambda item: item.value)):
            user = User.objects.create_user(
                email=f"loan-api-denied-{index}@example.org",
                name=f"{role.name} Loan API Denied",
                roles=[role.value],
                active_role=role.value,
            )
            self.client.force_login(user)

            response = self.client.get("/api/business-transformation/loans")

            with self.subTest(role=role.value):
                self.assertEqual(response.status_code, 403)

    def test_rvp_record_level_loan_api_is_empty(self):
        user = User.objects.create_user(
            email="loan-api-rvp@example.org",
            name="RVP Aggregate Loan API",
            roles=[EdifyRole.REGIONAL_VICE_PRESIDENT.value],
            active_role=EdifyRole.REGIONAL_VICE_PRESIDENT.value,
        )
        self.client.force_login(user)

        response = self.client.get("/api/business-transformation/loans")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_only_bt_role_sees_the_extended_workspace_tabs_on_the_loan_page(self):
        protected_links = (
            "/business-transformation/overview",
            "/business-transformation/business-accounting-finance",
            "/business-transformation/government-requirements",
            "/business-transformation/impact-reports",
        )
        for index, role in enumerate(EdifyRole):
            if role in self.full_access_roles:
                continue
            user = User.objects.create_user(
                email=f"loan-tabs-{index}@example.org",
                name=f"{role.name} Loan Tabs",
                roles=[role.value],
                active_role=role.value,
            )
            self.client.force_login(user)
            response = self.client.get("/loans")
            if role not in self.record_level_roles:
                with self.subTest(role=role.value):
                    self.assertEqual(response.status_code, 302)
                    self.assertNotIn(
                        "/loans",
                        {
                            item["url"]
                            for section in build_sidebar_for_user(user, "/loans")
                            for item in section["items"]
                        },
                    )
                continue
            html = response.content.decode()
            nav_start = html.index(
                '<nav aria-label="Business Transformation workspace"'
            )
            workspace_nav = html[nav_start : html.index("</nav>", nav_start)]

            with self.subTest(role=role.value):
                self.assertIn('href="/loans"', workspace_nav)
                for link in protected_links:
                    if role == EdifyRole.BUSINESS_TRANSFORMATION_OFFICER:
                        self.assertIn(f'href="{link}"', workspace_nav)
                    else:
                        self.assertNotIn(f'href="{link}"', workspace_nav)

                sidebar_bt_urls = {
                    item["url"]
                    for section in build_sidebar_for_user(user, "/loans")
                    if section["label"] == "BUSINESS TRANSFORMATION"
                    for item in section["items"]
                }
                if role == EdifyRole.BUSINESS_TRANSFORMATION_OFFICER:
                    self.assertTrue(set(protected_links).issubset(sidebar_bt_urls))
                elif role in {
                    EdifyRole.PARTNER_ADMIN,
                    EdifyRole.PARTNER_FIELD_OFFICER,
                }:
                    # Delivery partners carry no BUSINESS TRANSFORMATION
                    # group at all (owner, 2026-08-19).
                    self.assertEqual(sidebar_bt_urls, set())
                else:
                    self.assertEqual(sidebar_bt_urls, {"/loans"})

    def test_business_accounting_and_government_pages_are_bt_role_only(self):
        protected_pages = (
            "business_transformation_finance",
            "business_transformation_government",
        )
        self.assertEqual(
            PAGE_PERMISSIONS["business_transformation_finance"],
            {"BUSINESS_TRANSFORMATION"},
        )
        self.assertEqual(
            PAGE_PERMISSIONS["business_transformation_government"],
            {"BUSINESS_TRANSFORMATION"},
        )

        from apps.core.permissions import RolePermissionService

        for index, role in enumerate(EdifyRole):
            user = User.objects.create_user(
                email=f"bt-page-access-{index}@example.org",
                name=f"{role.name} BT Page Access",
                roles=[role.value],
                active_role=role.value,
            )
            with self.subTest(role=role.value):
                expected = role == EdifyRole.BUSINESS_TRANSFORMATION_OFFICER
                for page in protected_pages:
                    self.assertEqual(
                        RolePermissionService.can_view_page(user, page), expected
                    )

    def test_bt_and_mfi_dashboard_entry_routes_to_the_loan_dashboard(self):
        for index, role in enumerate(
            (
                EdifyRole.BUSINESS_TRANSFORMATION_OFFICER,
                EdifyRole.MFI_PARTNER_ADMIN,
                EdifyRole.MFI_LOAN_OFFICER,
            )
        ):
            user = User.objects.create_user(
                email=f"loan-home-{index}@example.org",
                name=f"{role.name} Loan Home",
                roles=[role.value],
                active_role=role.value,
            )
            self.client.force_login(user)

            response = self.client.get("/dashboard")

            with self.subTest(role=role.value):
                expected = (
                    "/business-transformation/overview"
                    if role == EdifyRole.BUSINESS_TRANSFORMATION_OFFICER
                    else "/mfi-portal/dashboard"
                )
                self.assertRedirects(response, expected, fetch_redirect_response=False)

    def test_only_mfi_roles_receive_write_and_execute_controls(self):
        write_permissions = {
            Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE.value,
            Permission.BUSINESS_TRANSFORMATION_REPAYMENT_WRITE.value,
        }
        certify_permission = Permission.BUSINESS_TRANSFORMATION_PORTFOLIO_CERTIFY.value
        for index, role in enumerate(EdifyRole):
            user = User.objects.create_user(
                email=f"loan-access-{index}@example.org",
                name=f"{role.name} Loan Access",
                roles=[role.value],
                active_role=role.value,
            )
            self.client.force_login(user)
            response = self.client.get("/loans")
            permissions = set(permissions_for_role(role))

            with self.subTest(role=role.value):
                if role not in self.record_level_roles:
                    self.assertEqual(response.status_code, 302)
                    self.assertTrue(write_permissions.isdisjoint(permissions))
                    self.assertNotIn(certify_permission, permissions)
                    continue
                if role in self.full_access_roles:
                    self.assertTrue(write_permissions.issubset(permissions))
                    if role == EdifyRole.MFI_PARTNER_ADMIN:
                        self.assertIn(certify_permission, permissions)
                    else:
                        self.assertNotIn(certify_permission, permissions)
                    self.assertContains(response, "Save loan record")
                    self.assertContains(response, "Record repayment snapshot")
                else:
                    self.assertTrue(write_permissions.isdisjoint(permissions))
                    self.assertNotIn(certify_permission, permissions)
                    if role == EdifyRole.BUSINESS_TRANSFORMATION_OFFICER:
                        self.assertContains(response, "Salesforce confirmation")
                    else:
                        self.assertContains(response, "Read only")
                    self.assertNotContains(response, "Save loan record")
                    self.assertNotContains(response, "Record repayment snapshot")

    def test_loan_export_and_salesforce_confirmation_have_distinct_authorities(self):
        for index, role in enumerate(EdifyRole):
            user = User.objects.create_user(
                email=f"loan-governance-{index}@example.org",
                name=f"{role.name} Loan Governance",
                roles=[role.value],
                active_role=role.value,
            )
            self.client.force_login(user)
            response = self.client.get("/loans")
            permissions = set(permissions_for_role(role))

            with self.subTest(role=role.value):
                if role not in self.record_level_roles:
                    self.assertEqual(response.status_code, 302)
                    self.assertNotIn(
                        Permission.BUSINESS_TRANSFORMATION_EXPORT.value, permissions
                    )
                    self.assertNotIn(
                        Permission.BUSINESS_TRANSFORMATION_SALESFORCE_CONFIRM.value,
                        permissions,
                    )
                    continue
                if role in self.export_roles:
                    self.assertIn(
                        Permission.BUSINESS_TRANSFORMATION_EXPORT.value, permissions
                    )
                    self.assertContains(response, "Export loan records")
                else:
                    self.assertNotIn(
                        Permission.BUSINESS_TRANSFORMATION_EXPORT.value, permissions
                    )
                    self.assertNotContains(response, "Export loan records")

                if role == EdifyRole.BUSINESS_TRANSFORMATION_OFFICER:
                    self.assertIn(
                        Permission.BUSINESS_TRANSFORMATION_SALESFORCE_CONFIRM.value,
                        permissions,
                    )
                    self.assertContains(response, "Salesforce confirmation")
                else:
                    self.assertNotIn(
                        Permission.BUSINESS_TRANSFORMATION_SALESFORCE_CONFIRM.value,
                        permissions,
                    )
                    if role != EdifyRole.BUSINESS_TRANSFORMATION_OFFICER:
                        self.assertNotContains(
                            response, "Salesforce confirmation queue"
                        )


class MfiAuthorityAndMonitoringTests(UgandaBusinessTransformationTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.mfi = MfiOrganization.objects.create(code="TEST-MFI", name="Test MFI")
        cls.purpose = LoanPurpose.objects.create(
            code="EDTECH-TEST", label="Education technology", is_edtech=True
        )
        cls.case = TransformationCase.objects.create(
            school=cls.school, status="active", opened_fy="2026"
        )
        cls.referral = FinanceReferral.objects.create(
            case=cls.case,
            mfi=cls.mfi,
            purpose=cls.purpose,
            intended_use="Install a school computer lab",
            consent_recorded_at=timezone.now(),
            status="sent",
            referred_by=cls.bt_user.id,
            referred_at=timezone.now(),
        )
        cls.officer = User.objects.create_user(
            email="officer@example.org",
            name="MFI Loan Officer",
            roles=[EdifyRole.MFI_LOAN_OFFICER.value],
            active_role=EdifyRole.MFI_LOAN_OFFICER.value,
        )
        MfiMembership.objects.create(
            mfi=cls.mfi,
            user=cls.officer,
            role=MfiMembershipRole.LOAN_OFFICER,
        )
        cls.ia_user = User.objects.create_user(
            email="loan-ia@example.org",
            name="Loan IA Verifier",
            roles=[EdifyRole.IMPACT_ASSESSMENT.value],
            active_role=EdifyRole.IMPACT_ASSESSMENT.value,
        )
        cls.facility = FundingFacility.objects.create(
            mfi=cls.mfi,
            external_reference="TEST-FACILITY",
            name="Test school lending facility",
            country_code="UG",
            currency="UGX",
            commitment_amount=Decimal("1000000000.00"),
            starts_on=timezone.localdate() - timedelta(days=30),
            status=FundingFacilityStatus.ACTIVE,
            created_by=cls.bt_user.id,
            approved_by="test-country-director",
            approved_at=timezone.now(),
        )
        FundingFacilityTranche.objects.create(
            facility=cls.facility,
            external_reference="TEST-FACILITY-RECEIPT",
            idempotency_key="test-facility-receipt",
            amount=Decimal("1000000000.00"),
            received_on=timezone.localdate() - timedelta(days=29),
            value_date=timezone.localdate() - timedelta(days=29),
            evidence_reference="TEST-BANK-EVIDENCE",
            confirmed_by="test-accountant",
            confirmed_at=timezone.now(),
        )

    def _loan_payload(self, reference="LN-001"):
        return {
            "mfiId": self.mfi.id,
            "caseId": self.case.id,
            "referralId": self.referral.id,
            "purposeId": self.purpose.id,
            "externalLoanReference": reference,
            "status": LoanStatus.PROCESSING,
            "approvedAmount": "12000000",
            "approvedAt": timezone.now().isoformat(),
            "termMonths": 18,
        }

    def _register_and_disburse(self, reference="LN-001", actor=None):
        actor = actor or self.officer
        result = services.register_or_update_loan(self._loan_payload(reference), actor)
        loan = MfiLoan.objects.get(id=result["id"])
        lending_impact.set_purpose_allocation_plan(
            loan.id,
            [
                {
                    "purposeId": self.purpose.id,
                    "plannedAmount": "12000000.00",
                    "intendedOutput": "Governed lending test output",
                }
            ],
            actor,
        )
        learner_count = self.school.enrollment or 100
        baseline = lending_impact.capture_enrolment_snapshot(
            loan.id,
            {
                "kind": "baseline",
                "asOfDate": timezone.localdate().isoformat(),
                "learnerCount": learner_count,
                "cohortDefinition": "All learners enrolled at first disbursement",
                "evidenceReference": f"ENROLMENT-{reference}",
            },
            actor,
        )
        lending_impact.verify_enrolment_snapshot(baseline.id, {}, self.ia_user)
        lending_ledger.reserve_facility_for_loan(
            {
                "facilityId": self.facility.id,
                "loanId": loan.id,
                "amount": "12000000.00",
                "idempotencyKey": f"allocation-{reference}",
            },
            self.bt_user,
        )
        lending_ledger.post_loan_disbursement(
            {
                "loanId": loan.id,
                "sequence": 1,
                "externalReference": f"DISBURSEMENT-{reference}",
                "idempotencyKey": f"disbursement-{reference}",
                "amount": "12000000.00",
                "disbursedOn": timezone.localdate().isoformat(),
                "valueDate": timezone.localdate().isoformat(),
                "bankReference": f"BANK-{reference}",
            },
            actor,
        )
        return result

    def test_mfi_disbursement_creates_monitoring_requirement(self):
        result = self._register_and_disburse()

        loan = MfiLoan.objects.get(id=result["id"])
        requirement = LoanVerificationRequirement.objects.get(loan=loan)
        self.case.refresh_from_db()
        self.assertEqual(loan.currency, "UGX")
        self.assertEqual(loan.registered_by, self.officer.id)
        self.assertEqual(
            requirement.due_date, timezone.localdate() + timedelta(days=60)
        )
        self.assertEqual(self.case.status, "monitoring")

    def test_loan_officer_cannot_read_another_officers_portfolio(self):
        loan_data = self._register_and_disburse("LN-OFFICER-SCOPE")
        other_officer = User.objects.create_user(
            email="other-officer@example.org",
            name="Other MFI Loan Officer",
            roles=[EdifyRole.MFI_LOAN_OFFICER.value],
            active_role=EdifyRole.MFI_LOAN_OFFICER.value,
        )
        MfiMembership.objects.create(
            mfi=self.mfi,
            user=other_officer,
            role=MfiMembershipRole.LOAN_OFFICER,
            officer_reference="OTHER-OFFICER",
        )

        self.assertFalse(
            services.scoped_loans(other_officer).filter(id=loan_data["id"]).exists()
        )
        self.assertTrue(
            services.scoped_loans(self.officer).filter(id=loan_data["id"]).exists()
        )

    def test_bt_confirms_the_salesforce_loan_id_without_editing_lender_facts(self):
        loan_data = self._register_and_disburse("LN-SALESFORCE")

        result = services.confirm_salesforce_loan(
            loan_data["id"],
            {"salesforceLoanId": "Loan-19650"},
            self.bt_user,
        )

        loan = MfiLoan.objects.get(id=loan_data["id"])
        self.assertEqual(result["salesforceLoanId"], "Loan-19650")
        self.assertEqual(loan.salesforce_confirmed_by, self.bt_user.id)
        self.assertIsNotNone(loan.salesforce_confirmed_at)
        self.assertEqual(loan.salesforce_entry_date, timezone.localdate())
        self.assertEqual(loan.salesforce_confirmation_note, "")
        self.assertEqual(loan.external_loan_reference, "LN-SALESFORCE")
        self.assertEqual(loan.disbursed_amount, Decimal("12000000"))
        self.assertTrue(
            SalesforceConfirmation.objects.filter(
                loan=loan,
                salesforce_loan_id="Loan-19650",
                status=SalesforceStatus.CONFIRMED,
            ).exists()
        )

    @override_settings(SALESFORCE_SYNC_ENABLED=True)
    def test_salesforce_confirmation_reconciles_through_retry_safe_outbox(self):
        loan_data = self._register_and_disburse("LN-SALESFORCE-INTEGRATION")
        payload = {
            "salesforceLoanId": "Loan-29650",
            "idempotencyKey": "sf-confirm-integration-1",
        }

        services.confirm_salesforce_loan(loan_data["id"], payload, self.bt_user)
        services.confirm_salesforce_loan(loan_data["id"], payload, self.bt_user)
        self.assertEqual(
            SalesforceConfirmation.objects.filter(loan_id=loan_data["id"]).count(), 1
        )
        with patch(
            "apps.integrations.services.validate_external_reference", return_value=None
        ):
            result = drain(time_budget_seconds=2)

        self.assertEqual(result["failed"], 0)
        self.assertTrue(
            IntegrationSync.objects.filter(
                system="salesforce",
                context_type="school_loan",
                context_id=loan_data["id"],
                status=IntegrationSyncStatus.RECONCILED_MANUAL,
            ).exists()
        )

    def test_bt_salesforce_drawer_exposes_only_the_id_confirmation(self):
        loan_data = self._register_and_disburse("LN-SALESFORCE-DRAWER")
        self.client.force_login(self.bt_user)

        response = self.client.get(f"/loans/{loan_data['id']}/drawer")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Salesforce ID")
        self.assertContains(response, "Confirm &amp; Complete", html=True)
        self.assertNotContains(response, "Return to MFI")
        self.assertNotContains(response, "returnReason")
        self.assertNotContains(response, "salesforceEntryDate")
        self.assertNotContains(response, "confirmationNote")

    def test_only_bt_can_confirm_a_valid_unique_salesforce_loan_id(self):
        first = self._register_and_disburse("LN-SALESFORCE-FIRST")
        second = self._register_and_disburse("LN-SALESFORCE-SECOND")

        with self.assertRaises(Forbidden):
            services.confirm_salesforce_loan(
                first["id"], {"salesforceLoanId": "Loan-19650"}, self.officer
            )
        with self.assertRaises(BadRequest):
            services.confirm_salesforce_loan(
                first["id"], {"salesforceLoanId": "not-a-salesforce-id"}, self.bt_user
            )
        services.confirm_salesforce_loan(
            first["id"], {"salesforceLoanId": "Loan-19650"}, self.bt_user
        )
        with self.assertRaises(BadRequest):
            services.confirm_salesforce_loan(
                second["id"], {"salesforceLoanId": "Loan-19650"}, self.bt_user
            )

    def test_salesforce_confirmation_locks_core_identity_but_not_repayment(self):
        loan_data = self._register_and_disburse("LN-LOCKED")
        services.confirm_salesforce_loan(
            loan_data["id"], {"salesforceLoanId": "Loan-19652"}, self.bt_user
        )
        changed = self._loan_payload("LN-LOCKED")
        changed["approvedAmount"] = "13000000"
        with self.assertRaises(Forbidden):
            services.register_or_update_loan(changed, self.officer)

        snapshot = services.add_repayment_snapshot(
            loan_data["id"],
            {
                "asOfDate": timezone.localdate().isoformat(),
                "amountDueDuringPeriod": "1000000",
                "amountPaidDuringPeriod": "1000000",
                "outstandingAmount": "11000000",
                "loanStatus": LoanStatus.ACTIVE,
            },
            self.officer,
        )
        self.assertEqual(snapshot["status"], "current")

    def test_dashboard_rolls_up_every_lending_partner_and_respects_mfi_scope(self):
        self._register_and_disburse("LN-PARTNER-ONE")
        other_mfi = MfiOrganization.objects.create(
            code="DASHBOARD-MFI", name="Dashboard MFI"
        )
        other_referral = FinanceReferral.objects.create(
            case=self.case,
            mfi=other_mfi,
            purpose=self.purpose,
            intended_use="Purchase a school bus",
            consent_recorded_at=timezone.now(),
            status=ReferralStatus.APPROVED,
            referred_by=self.bt_user.id,
            referred_at=timezone.now(),
        )
        MfiLoan.objects.create(
            mfi=other_mfi,
            school=self.school,
            case=self.case,
            referral=other_referral,
            purpose=self.purpose,
            external_loan_reference="LN-PARTNER-TWO",
            status=LoanStatus.PROCESSING,
            registered_by="other-mfi-officer",
        )

        country_rows = services.lending_partner_dashboard(self.bt_user, {})
        mfi_rows = services.lending_partner_dashboard(self.officer, {})

        self.assertSetEqual(
            {row["mfi__name"] for row in country_rows},
            {"Test MFI", "Dashboard MFI"},
        )
        self.assertEqual([row["mfi__name"] for row in mfi_rows], ["Test MFI"])

    def test_authorized_roles_export_the_governed_loan_register(self):
        loan_data = self._register_and_disburse("LN-EXPORT")
        services.confirm_salesforce_loan(
            loan_data["id"],
            {"salesforceLoanId": "Loan-19650"},
            self.bt_user,
        )
        users = [self.bt_user]
        for index, role in enumerate(
            (
                EdifyRole.COUNTRY_DIRECTOR,
                EdifyRole.IMPACT_ASSESSMENT,
                EdifyRole.REGIONAL_VICE_PRESIDENT,
            )
        ):
            users.append(
                User.objects.create_user(
                    email=f"loan-export-{index}@example.org",
                    name=f"{role.name} Loan Export",
                    roles=[role.value],
                    active_role=role.value,
                )
            )

        for user in users:
            self.client.force_login(user)
            response = self.client.get("/loans/export.csv")
            with self.subTest(role=user.active_role):
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
                self.assertContains(response, "LN-EXPORT")
                self.assertContains(response, "Loan-19650")

        self.client.force_login(self.officer)
        denied = self.client.get("/loans/export.csv", HTTP_HX_REQUEST="true")
        self.assertEqual(denied.status_code, 403)

    def test_mfi_admin_can_enter_a_loan_for_their_mfi(self):
        mfi_admin = User.objects.create_user(
            email="mfi-admin@example.org",
            name="MFI Partner Administrator",
            roles=[EdifyRole.MFI_PARTNER_ADMIN.value],
            active_role=EdifyRole.MFI_PARTNER_ADMIN.value,
        )
        MfiMembership.objects.create(
            mfi=self.mfi,
            user=mfi_admin,
            role=MfiMembershipRole.ADMIN,
        )

        result = services.register_or_update_loan(
            self._loan_payload("LN-MFI-ADMIN"), mfi_admin
        )

        self.assertTrue(
            MfiLoan.objects.filter(id=result["id"], registered_by=mfi_admin.id).exists()
        )

    def test_mfi_writer_cannot_enter_a_loan_for_another_mfi(self):
        other_mfi = MfiOrganization.objects.create(code="OTHER-MFI", name="Other MFI")
        other_referral = FinanceReferral.objects.create(
            case=self.case,
            mfi=other_mfi,
            purpose=self.purpose,
            intended_use="Build an additional classroom",
            consent_recorded_at=timezone.now(),
            status=ReferralStatus.APPROVED,
            referred_by=self.bt_user.id,
            referred_at=timezone.now(),
        )
        payload = self._loan_payload("LN-OTHER-MFI")
        payload.update(
            {
                "mfiId": other_mfi.id,
                "referralId": other_referral.id,
            }
        )

        with self.assertRaises(NotFoundError):
            services.register_or_update_loan(payload, self.officer)

    def test_countrywide_roles_cannot_enter_loans(self):
        roles = (
            EdifyRole.COUNTRY_DIRECTOR,
            EdifyRole.BUSINESS_TRANSFORMATION_OFFICER,
            EdifyRole.IMPACT_ASSESSMENT,
        )
        for index, role in enumerate(roles):
            user = User.objects.create_user(
                email=f"loan-countrywide-{index}@example.org",
                name=f"{role.name} Loan Owner",
                roles=[role.value],
                active_role=role.value,
            )

            with self.subTest(role=role.value):
                with self.assertRaises(Forbidden):
                    services.register_or_update_loan(
                        self._loan_payload(f"LN-COUNTRY-{index}"), user
                    )

    def test_read_only_role_cannot_mutate_a_loan(self):
        reader = User.objects.create_user(
            email="loan-reader@example.org",
            name="Loan Reader",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
        )

        with self.assertRaises(Forbidden):
            services.register_or_update_loan(self._loan_payload("LN-READ-ONLY"), reader)

    def test_loan_requires_the_governed_edify_referral(self):
        payload = self._loan_payload()
        payload.pop("referralId")

        with self.assertRaises(BadRequest):
            services.register_or_update_loan(payload, self.officer)

    def test_mfi_can_discover_its_referrals_and_governed_purposes(self):
        self.client.force_login(self.officer)

        referrals = self.client.get("/api/business-transformation/referrals")
        purposes = self.client.get("/api/business-transformation/loan-purposes")

        self.assertEqual(referrals.status_code, 200)
        self.assertEqual(referrals.json()[0]["schoolId"], self.school.school_id)
        self.assertEqual(referrals.json()[0]["mfiId"], self.mfi.id)
        self.assertEqual(purposes.status_code, 200)
        self.assertIn(self.purpose.id, {purpose["id"] for purpose in purposes.json()})

    def test_platform_admin_cannot_write_lender_facts(self):
        admin = User.objects.create_user(
            email="admin-bt@example.org",
            name="Technical Admin",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
        )

        with self.assertRaises(Forbidden):
            services.register_or_update_loan(self._loan_payload(), admin)

    def test_loan_officer_reads_their_governed_mfi_portfolio(self):
        own_loan = MfiLoan.objects.create(
            mfi=self.mfi,
            school=self.school,
            case=self.case,
            referral=self.referral,
            purpose=self.purpose,
            external_loan_reference="OWN",
            status=LoanStatus.PROCESSING,
            registered_by=self.officer.id,
        )
        MfiLoan.objects.create(
            mfi=self.mfi,
            school=self.school,
            case=self.case,
            referral=self.referral,
            purpose=self.purpose,
            external_loan_reference="OTHER",
            status=LoanStatus.PROCESSING,
            registered_by="different-officer",
        )

        self.assertSetEqual(
            set(services.scoped_loans(self.officer).values_list("id", flat=True)),
            {own_loan.id},
        )

    def test_repayment_snapshot_rejects_negative_financial_values(self):
        loan_data = self._register_and_disburse("LN-NEGATIVE")

        with self.assertRaises(BadRequest):
            services.add_repayment_snapshot(
                loan_data["id"],
                {
                    "asOfDate": timezone.localdate().isoformat(),
                    "outstandingAmount": "-1",
                },
                self.officer,
            )
        self.assertFalse(RepaymentSnapshot.objects.exists())

    def test_activity_ia_state_projects_into_loan_use_verification(self):
        loan_data = self._register_and_disburse("LN-VERIFY")
        cceo = User.objects.create_user(
            email="loan-verification-cceo@example.org",
            name="Loan Verification CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
        )
        cceo_staff = StaffProfile.objects.create(user=cceo, onboarding_state="active")
        StaffSchoolAssignment.objects.create(staff=cceo_staff, school_id=self.school.id)
        requirement = LoanVerificationRequirement.objects.get(loan_id=loan_data["id"])
        catalogue_item = ActivityCatalogueItem.objects.get(
            stable_code="BT_UG_LOAN_USE_VERIFICATION"
        )
        activity = Activity.objects.create(
            school=self.school,
            catalogue_item=catalogue_item,
            activity_type="school_visit",
            fy="2026",
            quarter="Q4",
            responsible_staff_id=cceo.id,
            status=ActivityStatus.PLANNED,
        )
        with self.assertRaises(Forbidden):
            services.link_verification_activity(
                requirement.id, activity.id, self.bt_user
            )
        services.link_verification_activity(requirement.id, activity.id, cceo)
        result = services.record_loan_use_result(
            requirement.id,
            {
                "finding": LoanUseFinding.FULLY_APPROVED,
                "notes": "Assets installed and in use.",
                "edtechAssetOperational": True,
            },
            cceo,
        )
        self.assertEqual(result["verificationStatus"], "provisional")

        activity.status = ActivityStatus.IA_VERIFIED
        activity.ia_confirmed_at = timezone.now()
        activity.save(update_fields=["status", "ia_confirmed_at", "updated_at"])
        services.project_activity_state(activity.id)
        requirement.refresh_from_db()
        requirement.result.refresh_from_db()
        self.assertEqual(requirement.status, VerificationRequirementStatus.VERIFIED)
        self.assertEqual(requirement.result.verification_status, "confirmed")

        activity.status = ActivityStatus.RETURNED_BY_IA
        activity.save(update_fields=["status", "updated_at"])
        services.project_activity_state(activity.id)
        requirement.refresh_from_db()
        requirement.result.refresh_from_db()
        self.assertEqual(
            requirement.status, VerificationRequirementStatus.AWAITING_VERIFICATION
        )
        self.assertEqual(requirement.result.verification_status, "provisional")

    def test_portfolio_metrics_preserve_uganda_currency_and_edtech_definition(self):
        self.school.enrollment = 480
        self.school.save(update_fields=["enrollment"])
        self._register_and_disburse("LN-METRIC")

        metrics = services.portfolio_metrics(self.bt_user, fy="2026")

        self.assertEqual(metrics["loansDisbursed"], 1)
        self.assertEqual(metrics["valueDisbursed"], Decimal("12000000"))
        self.assertEqual(metrics["edtechLoans"], 1)
        self.assertEqual(metrics["edtechPct"], 100.0)
        self.assertEqual(metrics["schoolsImpacted"], 1)
        self.assertEqual(metrics["studentsReached"], 480)
        self.assertEqual(metrics["schoolsWithEnrollment"], 1)
        self.assertEqual(metrics["schoolsMissingEnrollment"], 0)

    def test_student_reach_counts_each_financed_school_once(self):
        self.school.enrollment = 625
        self.school.save(update_fields=["enrollment"])
        self._register_and_disburse("LN-STUDENT-REACH-1")
        self._register_and_disburse("LN-STUDENT-REACH-2")

        metrics = services.portfolio_metrics(self.bt_user, fy="2026")

        self.assertEqual(metrics["loansDisbursed"], 2)
        self.assertEqual(metrics["schoolsImpacted"], 1)
        self.assertEqual(metrics["studentsReached"], 625)
        self.assertEqual(metrics["enrollmentCoveragePct"], 100.0)

    def test_rvp_workspace_has_complete_read_only_regional_detail(self):
        self._register_and_disburse("LN-RVP")
        rvp = User.objects.create_user(
            email="rvp-bt@example.org",
            name="Regional Vice President",
            roles=[EdifyRole.REGIONAL_VICE_PRESIDENT.value],
            active_role=EdifyRole.REGIONAL_VICE_PRESIDENT.value,
        )

        context = services.workspace_context(rvp, {"fy": "2026"})

        self.assertFalse(context["summary_only"])
        self.assertEqual(context["metrics"]["loansDisbursed"], 1)
        self.assertEqual(context["loans"].count(), 1)

    def test_field_staff_school_profile_hides_financial_amounts(self):
        self._register_and_disburse("LN-FIELD-SUMMARY")
        cceo = User.objects.create_user(
            email="cceo-bt@example.org",
            name="Assigned CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
        )
        staff = StaffProfile.objects.create(user=cceo, onboarding_state="active")
        StaffSchoolAssignment.objects.create(staff=staff, school_id=self.school.id)

        context = services.school_profile_context(cceo, self.school)

        self.assertFalse(context["sensitive"])
        self.assertEqual(len(context["loans"]), 1)
        self.assertNotIn("disbursed_amount", context["loans"][0])

    def test_governed_verification_activity_auto_links_oldest_requirement(self):
        loan_data = self._register_and_disburse("LN-AUTO-LINK")
        requirement = LoanVerificationRequirement.objects.get(loan_id=loan_data["id"])
        item = ActivityCatalogueItem.objects.get(
            stable_code="BT_UG_LOAN_USE_VERIFICATION"
        )

        activity = Activity.objects.create(
            school=self.school,
            catalogue_item=item,
            activity_type=item.workflow_kind,
            fy="2026",
            quarter="Q4",
            status=ActivityStatus.PLANNED,
        )

        requirement.refresh_from_db()
        self.assertEqual(requirement.activity_id, activity.id)
        self.assertEqual(requirement.status, VerificationRequirementStatus.SCHEDULED)
        self.assertEqual(activity.business_transformation_link.loan_id, loan_data["id"])

    def test_business_transformation_todos_are_derived_from_open_state(self):
        loan_data = self._register_and_disburse("LN-TODO")
        requirement = LoanVerificationRequirement.objects.get(loan_id=loan_data["id"])

        bt_todos = _business_transformation_todos(
            self.bt_user, self.bt_user.active_role, timezone.localdate()
        )
        mfi_todos = _business_transformation_todos(
            self.officer, self.officer.active_role, timezone.localdate()
        )

        self.assertIn(
            f"bt-verification-{requirement.id}", {todo["id"] for todo in bt_todos}
        )
        self.assertIn(
            f"bt-repayment-{loan_data['id']}", {todo["id"] for todo in mfi_todos}
        )

    def test_loan_submission_notification_resolves_when_salesforce_is_confirmed(self):
        loan_data = self._register_and_disburse("LN-NOTIFICATION-LIFECYCLE")
        notice = Notification.objects.get(
            recipient_id=self.bt_user.id,
            source_event_type="bt.loan.submitted",
            context_id=loan_data["id"],
        )
        self.assertIsNone(notice.resolved_at)

        services.confirm_salesforce_loan(
            loan_data["id"],
            {"salesforceLoanId": "Loan-31100"},
            self.bt_user,
        )

        notice.refresh_from_db()
        self.assertIsNotNone(notice.resolved_at)
        self.assertEqual(notice.status, "archived")

    def test_independent_statuses_drive_salesforce_return_and_ia_todos(self):
        loan_data = self._register_and_disburse("LN-INDEPENDENT-STATES")
        loan = MfiLoan.objects.get(id=loan_data["id"])
        self.assertEqual(loan.status, LoanStatus.DISBURSED)
        self.assertEqual(loan.salesforce_status, SalesforceStatus.PENDING)
        self.assertEqual(loan.ia_validation_status, IAValidationStatus.PENDING)
        self.assertGreaterEqual(LoanStatusHistory.objects.filter(loan=loan).count(), 2)

        bt_todos = _business_transformation_todos(
            self.bt_user, self.bt_user.active_role, timezone.localdate()
        )
        self.assertIn(f"bt-salesforce-{loan.id}", {todo["id"] for todo in bt_todos})

        country_director = User.objects.create_user(
            email="loan-return-cd@example.org",
            name="Loan Return Country Director",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
        )
        with self.assertRaises(Forbidden):
            services.return_salesforce_loan(
                loan.id,
                {
                    "returnReason": "amount_inconsistent",
                    "returnNote": "Check approval.",
                },
                self.bt_user,
            )
        services.return_salesforce_loan(
            loan.id,
            {"returnReason": "amount_inconsistent", "returnNote": "Check approval."},
            country_director,
        )
        loan.refresh_from_db()
        self.assertEqual(loan.salesforce_status, SalesforceStatus.RETURNED)
        mfi_todos = _business_transformation_todos(
            self.officer, self.officer.active_role, timezone.localdate()
        )
        self.assertIn(f"bt-returned-{loan.id}", {todo["id"] for todo in mfi_todos})

        services.resubmit_returned_loan(
            loan.id,
            {"correctionNote": "Confirmed the approved amount against the agreement."},
            self.officer,
        )
        services.confirm_salesforce_loan(
            loan.id,
            {"salesforceLoanId": "Loan-19651", "confirmationNote": "Entered."},
            self.bt_user,
        )
        ia_user = User.objects.create_user(
            email="ia-loan-validation@example.org",
            name="IA Loan Validator",
            roles=[EdifyRole.IMPACT_ASSESSMENT.value],
            active_role=EdifyRole.IMPACT_ASSESSMENT.value,
        )
        ia_todos = _business_transformation_todos(
            ia_user, ia_user.active_role, timezone.localdate()
        )
        self.assertIn(f"bt-ia-{loan.id}", {todo["id"] for todo in ia_todos})

        services.validate_loan_by_ia(
            loan.id, {"decision": IAValidationStatus.VERIFIED}, ia_user
        )
        loan.refresh_from_db()
        self.assertEqual(loan.status, LoanStatus.DISBURSED)
        self.assertEqual(loan.salesforce_status, SalesforceStatus.CONFIRMED)
        self.assertEqual(loan.ia_validation_status, IAValidationStatus.VERIFIED)
        self.assertNotIn(
            f"bt-ia-{loan.id}",
            {
                todo["id"]
                for todo in _business_transformation_todos(
                    ia_user, ia_user.active_role, timezone.localdate()
                )
            },
        )
