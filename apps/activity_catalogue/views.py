from __future__ import annotations

from django.db.models import Q
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import NotFoundError
from apps.core.permissions import RequirePermissions, has_permission
from apps.core.rbac import Permission
from apps.core.scoping import resolve_user_scope, scoped_school_queryset

from .models import ActivityCatalogueItem
from .models import ActivityProjectMapping
from .services import (
    list_catalogue,
    recommend_activities,
    serialize_item,
    transition_item,
)


VIEW = [Permission.ACTIVITY_CATALOGUE_VIEW.value]
MANAGE = [Permission.ACTIVITY_CATALOGUE_MANAGE.value]


def _bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _limit(value, default=3, maximum=5):
    try:
        return min(maximum, max(1, int(value or default)))
    except (TypeError, ValueError):
        return default


class CatalogueListView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        include_inactive = request.query_params.get(
            "includeInactive", ""
        ).lower() == "true" and has_permission(
            request.user, Permission.ACTIVITY_CATALOGUE_MANAGE.value
        )
        items = list_catalogue(
            intervention=request.query_params.get("intervention"),
            activity_type=request.query_params.get("activityType"),
            delivery_method=request.query_params.get("deliveryMethod"),
            project_id=request.query_params.get("projectId"),
            status=request.query_params.get("status"),
            include_inactive=include_inactive,
        )
        return Response([serialize_item(item) for item in items])


class CatalogueDetailView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request, item_id: str) -> Response:
        item = (
            ActivityCatalogueItem.objects.prefetch_related(
                "intervention_mappings",
                "versions",
                "project_mappings__project",
            )
            .filter(Q(id=item_id) | Q(stable_code=item_id))
            .first()
        )
        if not item:
            raise NotFoundError("Activity Catalogue item not found.")
        payload = serialize_item(item)
        payload["versions"] = [
            {
                "version": version.version,
                "reason": version.change_reason,
                "createdAt": version.created_at,
                "createdBy": version.created_by,
            }
            for version in item.versions.all()
        ]
        payload["projects"] = [
            {
                "id": mapping.project_id,
                "name": mapping.project.name,
                "requirement": mapping.required_or_optional,
            }
            for mapping in item.project_mappings.all()
            if mapping.active
        ]
        payload["usageCount"] = item.activities.count()
        return Response(payload)


class CatalogueRecommendationsView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.PLANNING_VIEW.value]

    def get(self, request: Request) -> Response:
        school_key = request.query_params.get("schoolId")
        scope = resolve_user_scope(request.user)
        if not scope.can_view_school_level_detail:
            raise NotFoundError("School not found.")
        school = (
            scoped_school_queryset(scope)
            .filter(Q(id=school_key) | Q(school_id=school_key))
            .first()
        )
        if not school:
            raise NotFoundError("School not found.")
        project = None
        if request.query_params.get("projectId"):
            from apps.projects.scoping import get_scoped_project

            project = get_scoped_project(
                request.query_params["projectId"], request.user
            )
        return Response(
            recommend_activities(
                school=school,
                principal=request.user,
                project=project,
                cluster=school.cluster
                if request.query_params.get("context") == "cluster"
                else None,
                executor_type=request.query_params.get("executorType", "staff"),
                limit=_limit(request.query_params.get("limit")),
            )
        )


class CatalogueAnalyticsView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.ANALYTICS_VIEW.value]

    def get(self, request: Request) -> Response:
        from apps.analytics.activity_catalogue import (
            activity_catalogue_metrics,
            verified_ssa_change_by_catalogue,
        )

        filters = {
            "fy": request.query_params.get("fy") or None,
            "project_id": request.query_params.get("projectId") or None,
        }
        return Response(
            {
                "usage": activity_catalogue_metrics(**filters),
                "verifiedSsaChange": verified_ssa_change_by_catalogue(**filters),
            }
        )


class CatalogueLifecycleView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = MANAGE

    def post(self, request: Request, item_id: str) -> Response:
        item = ActivityCatalogueItem.objects.filter(id=item_id).first()
        if not item:
            raise NotFoundError("Activity Catalogue item not found.")
        updated = transition_item(
            item,
            status=request.data.get("status", ""),
            actor_id=getattr(request.user, "user_id", None) or str(request.user.id),
            reason=request.data.get("reason", ""),
        )
        return Response(serialize_item(updated))


class CatalogueProjectMappingView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.ACTIVITY_CATALOGUE_MANAGE_PROJECT_RULES.value]

    def post(self, request: Request, item_id: str) -> Response:
        from apps.projects.models import Project

        item = ActivityCatalogueItem.objects.filter(id=item_id).first()
        project = Project.objects.filter(
            id=request.data.get("projectId"), deleted_at__isnull=True
        ).first()
        if not item or not project:
            raise NotFoundError("Catalogue item or Project not found.")
        mapping, _ = ActivityProjectMapping.objects.update_or_create(
            project=project,
            catalogue_item=item,
            defaults={
                "required_or_optional": request.data.get(
                    "requiredOrOptional", "optional"
                ),
                "eligible_school_levels": request.data.get("eligibleSchoolLevels", []),
                "eligible_school_types": request.data.get("eligibleSchoolTypes", []),
                "staff_delivery_allowed": _bool(
                    request.data.get("staffDeliveryAllowed")
                ),
                "partner_delivery_allowed": _bool(
                    request.data.get("partnerDeliveryAllowed")
                ),
                "active": _bool(request.data.get("active")),
            },
        )
        return Response(
            {
                "id": mapping.id,
                "projectId": mapping.project_id,
                "catalogueItemId": mapping.catalogue_item_id,
                "requiredOrOptional": mapping.required_or_optional,
                "active": mapping.active,
            }
        )

    def delete(self, request: Request, item_id: str) -> Response:
        mapping = ActivityProjectMapping.objects.filter(
            catalogue_item_id=item_id,
            project_id=request.data.get("projectId")
            or request.query_params.get("projectId"),
        ).first()
        if not mapping:
            raise NotFoundError("Project-to-Activity mapping not found.")
        mapping.active = False
        mapping.save(update_fields=["active", "updated_at"])
        return Response({"status": "inactive"})
