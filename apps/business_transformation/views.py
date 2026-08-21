"""Business Transformation JSON API."""

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import lending_impact, lending_imports, lending_ledger, services
from .models import LoanPurpose

VIEW = [Permission.BUSINESS_TRANSFORMATION_VIEW.value]
PORTFOLIO = [Permission.BUSINESS_TRANSFORMATION_PORTFOLIO_VIEW.value]


def _query(request: Request) -> dict:
    return {key: request.query_params.get(key) for key in request.query_params}


class CaseListView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        cases = services.scoped_cases(request.user)
        status = request.query_params.get("status")
        if status:
            cases = cases.filter(status=status)
        return Response([services.serialize_case(case) for case in cases[:200]])


class CaseTriageView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_CASE_MANAGE.value]

    def post(self, request: Request, case_id: str) -> Response:
        return Response(services.triage_case(case_id, request.data, request.user))


class MfiListCreateView(APIView):
    @property
    def required_permissions(self):
        if self.request.method == "POST":
            return [Permission.BUSINESS_TRANSFORMATION_MFI_MANAGE.value]
        return PORTFOLIO

    def get_permissions(self):
        return [IsAuthenticated(), RequirePermissions()]

    def get(self, request: Request) -> Response:
        return Response(
            [services.serialize_mfi(mfi) for mfi in services.scoped_mfis(request.user)]
        )

    def post(self, request: Request) -> Response:
        return Response(services.onboard_mfi(request.data, request.user), status=201)


class MfiMemberCreateView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_MFI_MEMBER_MANAGE.value]

    def post(self, request: Request) -> Response:
        return Response(
            services.onboard_mfi_member(request.data, request.user), status=201
        )


class ReferralCreateView(APIView):
    @property
    def required_permissions(self):
        if self.request.method == "POST":
            return [Permission.BUSINESS_TRANSFORMATION_REFERRAL_MANAGE.value]
        return PORTFOLIO

    def get_permissions(self):
        return [IsAuthenticated(), RequirePermissions()]

    def get(self, request: Request) -> Response:
        referrals = services.scoped_referrals(request.user)
        status = request.query_params.get("status")
        if status:
            referrals = referrals.filter(status=status)
        return Response(
            [services.serialize_referral(referral) for referral in referrals[:200]]
        )

    def post(self, request: Request) -> Response:
        return Response(
            services.create_referral(request.data, request.user), status=201
        )


class LoanPurposeListView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        return Response(
            [
                {
                    "id": purpose.id,
                    "code": purpose.code,
                    "label": purpose.label,
                    "isEdtech": purpose.is_edtech,
                }
                for purpose in LoanPurpose.objects.filter(active=True).order_by("label")
            ]
        )


class ReferralDecisionView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE.value]

    def post(self, request: Request, referral_id: str) -> Response:
        return Response(
            services.record_referral_decision(referral_id, request.data, request.user)
        )


class LoanListCreateView(APIView):
    @property
    def required_permissions(self):
        if self.request.method == "POST":
            return [Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE.value]
        return PORTFOLIO

    def get_permissions(self):
        return [IsAuthenticated(), RequirePermissions()]

    def get(self, request: Request) -> Response:
        loans = services.filter_loans(
            services.scoped_loans(request.user), _query(request)
        )
        return Response([services.serialize_loan(loan) for loan in loans[:200]])

    def post(self, request: Request) -> Response:
        return Response(
            services.register_or_update_loan(request.data, request.user), status=201
        )


class RepaymentSnapshotCreateView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_REPAYMENT_WRITE.value]

    def post(self, request: Request, loan_id: str) -> Response:
        return Response(
            services.add_repayment_snapshot(loan_id, request.data, request.user),
            status=201,
        )


class LoanSalesforceConfirmationView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_SALESFORCE_CONFIRM.value]

    def post(self, request: Request, loan_id: str) -> Response:
        return Response(
            services.confirm_salesforce_loan(loan_id, request.data, request.user)
        )


class LoanSalesforceReturnView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_CASE_MANAGE.value]

    def post(self, request: Request, loan_id: str) -> Response:
        return Response(
            services.return_salesforce_loan(loan_id, request.data, request.user)
        )


class LoanIAValidationView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_IA_VALIDATE.value]

    def post(self, request: Request, loan_id: str) -> Response:
        return Response(
            services.validate_loan_by_ia(loan_id, request.data, request.user)
        )


class VerificationActivityLinkView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [
        Permission.BUSINESS_TRANSFORMATION_SCHOOL_SUPPORT_MANAGE.value
    ]

    def post(self, request: Request, requirement_id: str) -> Response:
        return Response(
            services.link_verification_activity(
                requirement_id, request.data.get("activityId"), request.user
            )
        )


class LoanUseResultView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    # The service additionally checks that the caller is the activity's
    # assigned field officer. BT does not receive this execution permission.
    required_permissions = [Permission.ACTIVITY_COMPLETE.value]

    def post(self, request: Request, requirement_id: str) -> Response:
        return Response(
            services.record_loan_use_result(requirement_id, request.data, request.user)
        )


class LoanUseConcernReviewView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_CASE_MANAGE.value]

    def post(self, request: Request, result_id: str) -> Response:
        return Response(
            services.review_loan_use_concern(result_id, request.data, request.user)
        )


class PortfolioMetricsView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = PORTFOLIO

    def get(self, request: Request) -> Response:
        return Response(
            services.portfolio_metrics(
                request.user,
                fy=request.query_params.get("fy"),
                filters=_query(request),
            )
        )


class FundingFacilityListCreateView(APIView):
    @property
    def required_permissions(self):
        if self.request.method == "POST":
            return [Permission.BUSINESS_TRANSFORMATION_FACILITY_MANAGE.value]
        return [Permission.BUSINESS_TRANSFORMATION_FACILITY_VIEW.value]

    def get_permissions(self):
        return [IsAuthenticated(), RequirePermissions()]

    def get(self, request: Request) -> Response:
        return Response(
            [
                lending_ledger.serialize_facility(facility)
                for facility in lending_ledger.scoped_facilities(request.user)
            ]
        )

    def post(self, request: Request) -> Response:
        facility = lending_ledger.create_funding_facility(request.data, request.user)
        return Response(lending_ledger.serialize_facility(facility), status=201)


class FundingFacilityApproveView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_FACILITY_APPROVE.value]

    def post(self, request: Request, facility_id: str) -> Response:
        facility = lending_ledger.approve_funding_facility(facility_id, request.user)
        return Response(lending_ledger.serialize_facility(facility))


class FundingFacilityTrancheCreateView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_FACILITY_TRANSFER.value]

    def post(self, request: Request) -> Response:
        posting = lending_ledger.confirm_facility_tranche(request.data, request.user)
        return Response(
            {"id": posting.id, "facilityId": posting.facility_id}, status=201
        )


class FundingFacilityTrancheReverseView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_FACILITY_TRANSFER.value]

    def post(self, request: Request, tranche_id: str) -> Response:
        posting = lending_ledger.reverse_facility_tranche(
            tranche_id, request.data, request.user
        )
        return Response({"id": posting.id, "trancheId": posting.tranche_id}, status=201)


class FundingFacilityMovementCreateView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_FACILITY_TRANSFER.value]

    def post(self, request: Request) -> Response:
        posting = lending_ledger.post_facility_movement(request.data, request.user)
        return Response(
            {
                "id": posting.id,
                "facilityId": posting.facility_id,
                "kind": posting.kind,
                "capitalSource": posting.capital_source,
                "amount": str(posting.amount),
            },
            status=201,
        )


class FundingFacilityMovementReverseView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_FACILITY_TRANSFER.value]

    def post(self, request: Request, movement_id: str) -> Response:
        posting = lending_ledger.reverse_facility_movement(
            movement_id, request.data, request.user
        )
        return Response(
            {"id": posting.id, "movementId": posting.movement_id}, status=201
        )


class FundingFacilityAllocationCreateView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_ALLOCATION_MANAGE.value]

    def post(self, request: Request) -> Response:
        allocation = lending_ledger.reserve_facility_for_loan(
            request.data, request.user
        )
        return Response(
            {
                "id": allocation.id,
                "facilityId": allocation.facility_id,
                "loanId": allocation.loan_id,
                "amount": str(allocation.amount),
                "status": allocation.status,
            },
            status=201,
        )


class FundingFacilityAllocationReleaseView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_ALLOCATION_MANAGE.value]

    def post(self, request: Request, allocation_id: str) -> Response:
        allocation = lending_ledger.release_facility_allocation(
            allocation_id, request.data, request.user
        )
        return Response({"id": allocation.id, "status": allocation.status})


class LoanDisbursementCreateView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_DISBURSEMENT_WRITE.value]

    def post(self, request: Request) -> Response:
        posting = lending_ledger.post_loan_disbursement(request.data, request.user)
        return Response(
            {
                "id": posting.id,
                "loanId": posting.loan_id,
                "amount": str(posting.amount),
            },
            status=201,
        )


class LoanDisbursementReverseView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_DISBURSEMENT_WRITE.value]

    def post(self, request: Request, disbursement_id: str) -> Response:
        posting = lending_ledger.reverse_loan_disbursement(
            disbursement_id, request.data, request.user
        )
        return Response(
            {"id": posting.id, "disbursementId": posting.disbursement_id}, status=201
        )


class LoanRepaymentScheduleCreateView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE.value]

    def post(self, request: Request, loan_id: str) -> Response:
        rows = lending_ledger.create_repayment_schedule(
            loan_id,
            request.data.get("installments") or [],
            request.user,
            version=int(request.data.get("version") or 1),
        )
        return Response(
            [
                {"id": row.id, "installmentNumber": row.installment_number}
                for row in rows
            ],
            status=201,
        )


class RepaymentTransactionCreateView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_REPAYMENT_WRITE.value]

    def post(self, request: Request) -> Response:
        posting = lending_ledger.post_repayment_transaction(request.data, request.user)
        return Response(
            {
                "id": posting.id,
                "loanId": posting.loan_id,
                "amount": str(posting.amount),
            },
            status=201,
        )


class RepaymentTransactionReverseView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_REPAYMENT_REVERSE.value]

    def post(self, request: Request, transaction_id: str) -> Response:
        posting = lending_ledger.reverse_repayment_transaction(
            transaction_id, request.data, request.user
        )
        return Response(
            {"id": posting.id, "reversalOf": posting.reversal_of_id}, status=201
        )


class LoanPurposeAllocationPlanView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE.value]

    def post(self, request: Request, loan_id: str) -> Response:
        rows = lending_impact.set_purpose_allocation_plan(
            loan_id, request.data.get("allocations") or [], request.user
        )
        return Response(
            [
                {
                    "id": row.id,
                    "purposeId": row.purpose_id,
                    "plannedAmount": str(row.planned_amount),
                }
                for row in rows
            ],
            status=201,
        )


class LoanPurposeUseReportView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE.value]

    def post(self, request: Request, allocation_id: str) -> Response:
        row = lending_impact.report_purpose_use(
            allocation_id, request.data, request.user
        )
        return Response({"id": row.id, "status": row.status})


class LoanPurposeUseVerifyView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_IA_VALIDATE.value]

    def post(self, request: Request, allocation_id: str) -> Response:
        row = lending_impact.verify_purpose_use(
            allocation_id, request.data, request.user
        )
        return Response({"id": row.id, "status": row.status})


class LoanEnrolmentSnapshotCreateView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE.value]

    def post(self, request: Request, loan_id: str) -> Response:
        row = lending_impact.capture_enrolment_snapshot(
            loan_id, request.data, request.user
        )
        return Response({"id": row.id, "status": row.status}, status=201)


class LoanEnrolmentSnapshotVerifyView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_IA_VALIDATE.value]

    def post(self, request: Request, snapshot_id: str) -> Response:
        row = lending_impact.verify_enrolment_snapshot(
            snapshot_id, request.data, request.user
        )
        return Response({"id": row.id, "status": row.status})


class LoanReturnedResubmitView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE.value]

    def post(self, request: Request, loan_id: str) -> Response:
        return Response(
            services.resubmit_returned_loan(loan_id, request.data, request.user)
        )


class LoanAmendmentRequestView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE.value]

    def post(self, request: Request, loan_id: str) -> Response:
        row = services.request_loan_amendment(loan_id, request.data, request.user)
        return Response({"id": row.id, "status": row.status}, status=201)


class LoanAmendmentApproveView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_AMENDMENT_APPROVE.value]

    def post(self, request: Request, amendment_id: str) -> Response:
        row = services.approve_loan_amendment(amendment_id, request.data, request.user)
        return Response({"id": row.id, "status": row.status})


class PortfolioImportStageView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_REPAYMENT_WRITE.value]

    def post(self, request: Request) -> Response:
        upload = request.FILES.get("file")
        if upload is None:
            from apps.core.exceptions import BadRequest

            raise BadRequest("A CSV file is required.")
        row = lending_imports.stage_repayment_csv(
            mfi_id=request.data.get("mfiId"),
            reporting_month=request.data.get("reportingMonth"),
            filename=upload.name,
            content=upload.read(),
            principal=request.user,
        )
        return Response(
            {
                "id": row.id,
                "status": row.status,
                "totalRows": row.total_rows,
                "validRows": row.valid_rows,
                "exceptionRows": row.exception_rows,
            },
            status=201,
        )


class PortfolioImportApplyView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_REPAYMENT_WRITE.value]

    def post(self, request: Request, submission_id: str) -> Response:
        row = lending_imports.apply_repayment_import(submission_id, request.user)
        return Response(
            {
                "id": row.id,
                "status": row.status,
                "validRows": row.valid_rows,
                "exceptionRows": row.exception_rows,
            }
        )


class PortfolioImportCertifyView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_PORTFOLIO_CERTIFY.value]

    def post(self, request: Request, submission_id: str) -> Response:
        row = lending_imports.certify_portfolio_submission(submission_id, request.user)
        return Response({"id": row.id, "status": row.status})


class PurposeAssetOutputCreateView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE.value]

    def post(self, request: Request, allocation_id: str) -> Response:
        row = lending_impact.create_asset_output(
            allocation_id, request.data, request.user
        )
        return Response({"id": row.id, "status": row.status}, status=201)


class PurposeAssetOutputReportView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE.value]

    def post(self, request: Request, output_id: str) -> Response:
        row = lending_impact.report_asset_output(output_id, request.data, request.user)
        return Response({"id": row.id, "status": row.status})


class PurposeAssetOutputVerifyView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_IA_VALIDATE.value]

    def post(self, request: Request, output_id: str) -> Response:
        row = lending_impact.verify_asset_output(output_id, request.data, request.user)
        return Response({"id": row.id, "status": row.status})


class TeacherBeneficiaryCreateView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE.value]

    def post(self, request: Request, loan_id: str) -> Response:
        row = lending_impact.record_teacher_beneficiary(
            loan_id, request.data, request.user
        )
        return Response(
            {"id": row.id, "programmeStatus": row.programme_status}, status=201
        )


class TeacherBeneficiaryProgressView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_LOAN_WRITE.value]

    def post(self, request: Request, beneficiary_id: str) -> Response:
        row = lending_impact.report_teacher_progress(
            beneficiary_id, request.data, request.user
        )
        return Response({"id": row.id, "programmeStatus": row.programme_status})


class TeacherBeneficiaryVerifyView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_IA_VALIDATE.value]

    def post(self, request: Request, beneficiary_id: str) -> Response:
        row = lending_impact.verify_teacher_completion(
            beneficiary_id, request.data, request.user
        )
        return Response({"id": row.id, "programmeStatus": row.programme_status})


class LoanPurposeRequestView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_PURPOSE_REQUEST.value]

    def post(self, request: Request) -> Response:
        row = lending_impact.request_loan_purpose(request.data, request.user)
        return Response({"id": row.id, "status": row.status}, status=201)


class LoanPurposeReviewView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_PURPOSE_REVIEW.value]

    def post(self, request: Request, proposal_id: str) -> Response:
        row = lending_impact.review_loan_purpose(
            proposal_id, request.data, request.user
        )
        return Response({"id": row.id, "status": row.status})


class LoanPurposeDefineView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_PURPOSE_DEFINE.value]

    def post(self, request: Request, proposal_id: str) -> Response:
        row = lending_impact.define_loan_purpose_measurement(
            proposal_id, request.data, request.user
        )
        return Response({"id": row.id, "status": row.status})


class LoanPurposeApproveView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_PURPOSE_APPROVE.value]

    def post(self, request: Request, proposal_id: str) -> Response:
        row = lending_impact.approve_loan_purpose(
            proposal_id, request.data, request.user
        )
        return Response({"id": row.id, "code": row.code}, status=201)


class LendingImpactSummaryView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [
        Permission.BUSINESS_TRANSFORMATION_PORTFOLIO_VIEW.value,
        Permission.BUSINESS_TRANSFORMATION_SCHOOL_SUPPORT_MANAGE.value,
    ]

    def get(self, request: Request) -> Response:
        return Response(
            {
                **lending_impact.impact_summary(request.user),
                **lending_impact.purpose_output_summary(request.user),
            }
        )


class LoanImpactVerifyView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.BUSINESS_TRANSFORMATION_IA_VALIDATE.value]

    def post(self, request: Request, assessment_id: str) -> Response:
        row = lending_impact.verify_loan_impact(
            assessment_id, request.data, request.user
        )
        return Response(
            {
                "id": row.id,
                "classification": row.classification,
                "status": row.ia_status,
            }
        )


class LendingGeographicEquityView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [
        Permission.BUSINESS_TRANSFORMATION_PORTFOLIO_VIEW.value,
        Permission.BUSINESS_TRANSFORMATION_SCHOOL_SUPPORT_MANAGE.value,
    ]

    def get(self, request: Request) -> Response:
        return Response(lending_impact.geographic_equity(request.user))
