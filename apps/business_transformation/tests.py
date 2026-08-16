from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.command_center.todo_service import _business_transformation_todos
from apps.core.enums import ActivityStatus, SsaIntervention
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.navigation import build_sidebar_for_user
from apps.core.rbac import EdifyRole, Permission, permissions_for_role
from apps.outbox.models import OutboxEvent
from apps.outbox.services import drain
from apps.partners.models import Partner, PartnerAssignment
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

from . import services
from .models import (
    CaseRecommendation,
    FinanceReferral,
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
        self.assertContains(workspace, 'data-component="kpi-card"', count=11)
        self.assertNotContains(workspace, "text-[11px]")
        self.assertEqual(portfolio.status_code, 200)
        self.assertContains(portfolio, "MFI referral pipeline")
        self.assertEqual(school_profile.status_code, 200)
        self.assertContains(school_profile, "Business Transformation")


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

    def test_government_requirements_uses_the_same_school_list_contract(self):
        self.client.force_login(self.cceo)

        response = self.client.get("/business-transformation/government-requirements")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Government Requirements portfolio")
        self.assertContains(response, "school-record-list")
        self.assertContains(response, self.school.name)
        self.assertContains(response, "Plan")

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
    full_access_roles = {
        EdifyRole.MFI_PARTNER_ADMIN,
        EdifyRole.MFI_LOAN_OFFICER,
    }
    export_roles = {
        EdifyRole.COUNTRY_DIRECTOR,
        EdifyRole.IMPACT_ASSESSMENT,
        EdifyRole.REGIONAL_VICE_PRESIDENT,
        EdifyRole.BUSINESS_TRANSFORMATION_OFFICER,
    }

    def test_every_role_has_the_loans_page_in_navigation(self):
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
        governed_permissions = {
            Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE.value,
            Permission.BUSINESS_TRANSFORMATION_REPAYMENT_WRITE.value,
            Permission.BUSINESS_TRANSFORMATION_PORTFOLIO_CERTIFY.value,
        }
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
                if role in self.full_access_roles:
                    self.assertTrue(governed_permissions.issubset(permissions))
                    self.assertContains(response, "Save loan record")
                    self.assertContains(response, "Record repayment snapshot")
                else:
                    self.assertTrue(governed_permissions.isdisjoint(permissions))
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

    def _loan_payload(self, reference="LN-001"):
        return {
            "mfiId": self.mfi.id,
            "caseId": self.case.id,
            "referralId": self.referral.id,
            "purposeId": self.purpose.id,
            "externalLoanReference": reference,
            "status": LoanStatus.DISBURSED,
            "approvedAmount": "12000000",
            "disbursedAmount": "12000000",
            "approvedAt": timezone.now().isoformat(),
            "disbursementDate": timezone.localdate().isoformat(),
            "termMonths": 18,
        }

    def test_mfi_disbursement_creates_monitoring_requirement(self):
        result = services.register_or_update_loan(self._loan_payload(), self.officer)

        loan = MfiLoan.objects.get(id=result["id"])
        requirement = LoanVerificationRequirement.objects.get(loan=loan)
        self.case.refresh_from_db()
        self.assertEqual(loan.currency, "UGX")
        self.assertEqual(loan.registered_by, self.officer.id)
        self.assertEqual(
            requirement.due_date, timezone.localdate() + timedelta(days=60)
        )
        self.assertEqual(self.case.status, "monitoring")

    def test_bt_confirms_the_salesforce_loan_id_without_editing_lender_facts(self):
        loan_data = services.register_or_update_loan(
            self._loan_payload("LN-SALESFORCE"), self.officer
        )

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

    def test_bt_salesforce_drawer_exposes_only_the_id_confirmation(self):
        loan_data = services.register_or_update_loan(
            self._loan_payload("LN-SALESFORCE-DRAWER"), self.officer
        )
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
        first = services.register_or_update_loan(
            self._loan_payload("LN-SALESFORCE-FIRST"), self.officer
        )
        second = services.register_or_update_loan(
            self._loan_payload("LN-SALESFORCE-SECOND"), self.officer
        )

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
        loan_data = services.register_or_update_loan(
            self._loan_payload("LN-LOCKED"), self.officer
        )
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
        services.register_or_update_loan(
            self._loan_payload("LN-PARTNER-ONE"), self.officer
        )
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
        loan_data = services.register_or_update_loan(
            self._loan_payload("LN-EXPORT"), self.officer
        )
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
        MfiLoan.objects.create(
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
            set(MfiLoan.objects.filter(mfi=self.mfi).values_list("id", flat=True)),
        )

    def test_repayment_snapshot_rejects_negative_financial_values(self):
        loan_data = services.register_or_update_loan(
            self._loan_payload("LN-NEGATIVE"), self.officer
        )

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
        loan_data = services.register_or_update_loan(
            self._loan_payload("LN-VERIFY"), self.officer
        )
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
        services.register_or_update_loan(self._loan_payload("LN-METRIC"), self.officer)

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
        services.register_or_update_loan(
            self._loan_payload("LN-STUDENT-REACH-1"), self.officer
        )
        services.register_or_update_loan(
            self._loan_payload("LN-STUDENT-REACH-2"), self.officer
        )

        metrics = services.portfolio_metrics(self.bt_user, fy="2026")

        self.assertEqual(metrics["loansDisbursed"], 2)
        self.assertEqual(metrics["schoolsImpacted"], 1)
        self.assertEqual(metrics["studentsReached"], 625)
        self.assertEqual(metrics["enrollmentCoveragePct"], 100.0)

    def test_rvp_workspace_is_aggregate_only(self):
        services.register_or_update_loan(self._loan_payload("LN-RVP"), self.officer)
        rvp = User.objects.create_user(
            email="rvp-bt@example.org",
            name="Regional Vice President",
            roles=[EdifyRole.REGIONAL_VICE_PRESIDENT.value],
            active_role=EdifyRole.REGIONAL_VICE_PRESIDENT.value,
        )

        context = services.workspace_context(rvp, {"fy": "2026"})

        self.assertTrue(context["summary_only"])
        self.assertEqual(context["metrics"]["loansDisbursed"], 1)
        self.assertFalse(context["loans"].exists())

    def test_field_staff_school_profile_hides_financial_amounts(self):
        services.register_or_update_loan(
            self._loan_payload("LN-FIELD-SUMMARY"), self.officer
        )
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
        loan_data = services.register_or_update_loan(
            self._loan_payload("LN-AUTO-LINK"), self.officer
        )
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
        loan_data = services.register_or_update_loan(
            self._loan_payload("LN-TODO"), self.officer
        )
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

    def test_independent_statuses_drive_salesforce_return_and_ia_todos(self):
        loan_data = services.register_or_update_loan(
            self._loan_payload("LN-INDEPENDENT-STATES"), self.officer
        )
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

        services.register_or_update_loan(
            self._loan_payload("LN-INDEPENDENT-STATES"), self.officer
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
