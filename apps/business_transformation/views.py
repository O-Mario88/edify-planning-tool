"""Business Transformation JSON API."""

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services
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
