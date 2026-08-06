"""Special-projects endpoints — /api/special-projects/*."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission
from apps.activity_catalogue.services import list_catalogue, serialize_item

from . import services

VIEW = [Permission.ANALYTICS_VIEW.value]
ASSIGN = [Permission.ACTIVITY_ASSIGN.value]


class ProjectListView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        return Response(services.list_projects(request.user))

    def get_permissions(self):
        self.required_permissions = (
            [Permission.PROJECT_CONFIGURE_PRIORITIES.value]
            if self.request.method == "POST"
            else VIEW
        )
        return [IsAuthenticated(), RequirePermissions()]

    def post(self, request: Request) -> Response:
        return Response(
            services.create_project(request.data, request.user),
            status=201,
        )


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
        return Response(services.get_one(project_id, request.user))

    def patch(self, request: Request, project_id: str) -> Response:
        # CD/ProjectCoordinator/Admin sets the project manager (single staff id).
        if "managerStaffId" in request.data:
            return Response(
                services.set_manager(project_id, request.data, request.user)
            )
        return Response(services.get_one(project_id, request.user))


class ProjectImpactView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request, project_id: str) -> Response:
        return Response(services.impact(project_id, request.user))


class ProjectEligibleActivitiesView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.PLANNING_VIEW.value]

    def get(self, request: Request, project_id: str) -> Response:
        from .scoping import get_scoped_project

        project = get_scoped_project(project_id, request.user)
        return Response(
            [serialize_item(item) for item in list_catalogue(project_id=project.id)]
        )


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
        return Response(
            services.assign_school(project_id, request.data, request.user),
            status=201,
        )


class ProjectStaffAssignmentsView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.PROJECT_CONFIGURE_PRIORITIES.value]

    def get(self, request: Request, project_id: str) -> Response:
        return Response(services.staff_assignments(project_id, request.user))

    def post(self, request: Request, project_id: str) -> Response:
        return Response(
            services.assign_staff(project_id, request.data, request.user),
            status=201,
        )


class ProjectStaffAssignmentDetailView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.PROJECT_CONFIGURE_PRIORITIES.value]

    def delete(self, request: Request, project_id: str, staff_id: str) -> Response:
        return Response(services.revoke_staff(project_id, staff_id, request.user))


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
