"""
Auth endpoints — /api/auth/* (login, me, refresh, logout, forgot/reset, invite).

The ONLY controller without a class-level auth guard: login/refresh/reset are
public; `me` requires JWT. Login + forgot-password are rate-limited.
"""
from __future__ import annotations

from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsAuthenticated
from apps.core.rbac import permissions_for_role
from apps.core.scoping import resolve_user_scope
from apps.core.throttling import ForgotPasswordRateThrottle, LoginRateThrottle

from . import auth_services
from .jwt import AuthPrincipal
from .serializers import (
    ForgotPasswordSerializer,
    LoginSerializer,
    LogoutSerializer,
    RefreshSerializer,
    ResetPasswordSerializer,
    SetPasswordSerializer,
)


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [LoginRateThrottle]
    rate_name = "auth.login"

    def post(self, request: Request) -> Response:
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        result = auth_services.login(
            email=data["email"],
            password=data["password"],
            requested_active_role=data.get("activeRole"),
        )
        return Response(result)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        user: AuthPrincipal = request.user
        scope = resolve_user_scope(user)
        return Response(
            {
                "id": user.user_id,
                "userId": user.user_id,
                "email": user.email,
                "name": user.name,
                "roles": user.roles,
                "activeRole": user.active_role,
                "permissions": permissions_for_role(user.active_role),
                "staffProfileId": user.staff_profile_id,
                "scope": {
                    "countryScope": scope.country_scope,
                    "canViewSummaryOnly": scope.can_view_summary_only,
                    "canViewSchoolLevelDetail": scope.can_view_school_level_detail,
                    "canViewPartnerData": scope.can_view_partner_data,
                    "canViewFinancialData": scope.can_view_financial_data,
                    "canApprove": scope.can_approve,
                    "canAssign": scope.can_assign,
                    "canExport": scope.can_export,
                    "schoolsInScope": None if scope.country_scope else len(scope.school_ids),
                },
            }
        )


class RefreshView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        s = RefreshSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(auth_services.refresh(s.validated_data["refreshToken"]))


class LogoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        s = LogoutSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(auth_services.logout(s.validated_data.get("refreshToken")))


class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ForgotPasswordRateThrottle]
    rate_name = "auth.forgot-password"

    def post(self, request: Request) -> Response:
        s = ForgotPasswordSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(auth_services.forgot_password(s.validated_data["email"]))


class ResetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        s = ResetPasswordSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        return Response(auth_services.reset_password(d["token"], d["password"], d["confirm"]))


class InviteValidateView(APIView):
    permission_classes = [AllowAny]

    def get(self, request: Request) -> Response:
        token = request.query_params.get("token", "")
        return Response(auth_services.validate_invite(token))


class SetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        s = SetPasswordSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        return Response(auth_services.set_password(d["token"], d["password"], d["confirm"]))
