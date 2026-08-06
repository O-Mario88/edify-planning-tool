"""Admin-users endpoints — /api/admin/users/*."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services

MANAGE = [Permission.USER_MANAGE.value]


class AdminUserListCreateView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = MANAGE

    def get(self, request: Request) -> Response:
        return Response(services.list_users())

    def post(self, request: Request) -> Response:
        return Response(services.create(request.data, request.user), status=201)


def _action_view(fn):
    class _V(APIView):
        permission_classes = [IsAuthenticated, RequirePermissions]
        required_permissions = MANAGE

        def post(self, request: Request, user_id: str) -> Response:
            return Response(fn(user_id, request.user))

    return _V


ResendInviteView = _action_view(services.resend_invite)
RevokeInviteView = _action_view(services.revoke_invite)
SuspendView = _action_view(services.suspend)
DisableView = _action_view(services.disable)
ReactivateView = _action_view(services.reactivate)
ForcePasswordResetView = _action_view(services.force_password_reset)


class AdminUserDetailAPIView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = MANAGE

    def put(self, request: Request, user_id: str) -> Response:
        return Response(services.update_user(user_id, request.data, request.user))

    def delete(self, request: Request, user_id: str) -> Response:
        return Response(services.delete_user(user_id, request.user))
