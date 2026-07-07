"""Staff-setup candidate endpoints — /api/staff-candidates/*.

Admin/CD/HR resolve uploaded staff names into real users (or merge with existing),
linking the affected schools to the resolved staff so they enter planning scope.
"""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services

# USER_MANAGE gates user provisioning (Admin/CD/HR). Staff-candidate resolution
# creates/links users, so the same permission applies.
MANAGE = [Permission.USER_MANAGE.value]


def _q(request: Request) -> dict:
    return {k: request.query_params.get(k) for k in request.query_params}


class StaffCandidateListView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = MANAGE

    def get(self, request: Request) -> Response:
        return Response(services.list_candidates(_q(request)))


class StaffCandidateDetailView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = MANAGE

    def get(self, request: Request, candidate_id: str) -> Response:
        return Response(services.get_one(candidate_id))


class StaffCandidateCreateUserView(APIView):
    """Admin adds email (+phone, role) → User + StaffProfile created; all matching
    schools linked to the new staff. Candidate → active."""

    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = MANAGE

    def post(self, request: Request, candidate_id: str) -> Response:
        return Response(services.create_user(candidate_id, request.data, request.user))


class StaffCandidateMatchExistingView(APIView):
    """Admin picks an existing user id → schools linked to that user's staff.
    Candidate → merged."""

    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = MANAGE

    def post(self, request: Request, candidate_id: str) -> Response:
        return Response(
            services.match_existing(candidate_id, request.data, request.user)
        )


class StaffCandidateIgnoreView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = MANAGE

    def post(self, request: Request, candidate_id: str) -> Response:
        return Response(services.ignore(candidate_id, request.user))
