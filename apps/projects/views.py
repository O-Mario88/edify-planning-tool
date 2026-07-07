"""Special-projects endpoints — /api/special-projects/*."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services

VIEW = [Permission.ANALYTICS_VIEW.value]
ASSIGN = [Permission.ACTIVITY_ASSIGN.value]


class ProjectListView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        return Response(services.list_projects())


class ProjectDetailView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get_permissions(self):
        # PATCH (set manager) requires PROJECT_MANAGE; GET only needs VIEW.
        if self.request.method == "PATCH":
            self.required_permissions = [Permission.PROJECT_MANAGE.value]
        else:
            self.required_permissions = VIEW
        return [IsAuthenticated(), RequirePermissions()]

    def get(self, request: Request, project_id: str) -> Response:
        return Response(services.get_one(project_id))

    def patch(self, request: Request, project_id: str) -> Response:
        # CD/ProjectCoordinator/Admin sets the project manager (single staff id).
        if "managerStaffId" in request.data:
            return Response(services.set_manager(project_id, request.data))
        return Response(services.get_one(project_id))


class ProjectImpactView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request, project_id: str) -> Response:
        return Response(services.impact(project_id))


class ProjectPartnersView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request, project_id: str) -> Response:
        return Response(services.partners(project_id))

    def post(self, request: Request, project_id: str) -> Response:
        return Response(services.assign_partner(project_id, request.data), status=201)


class ProjectSchoolsAssignView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ASSIGN

    def post(self, request: Request, project_id: str) -> Response:
        return Response(services.assign_school(project_id, request.data), status=201)


class ProjectSchoolsRemoveView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ASSIGN

    def delete(self, request: Request, project_id: str, school_id: str) -> Response:
        return Response(services.remove_school(project_id, school_id))


class ProjectPartnerRemoveView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ASSIGN

    def delete(self, request: Request, project_id: str, partner_id: str) -> Response:
        return Response(services.remove_partner(project_id, partner_id))
