"""Partners endpoints — /api/partners/*."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.scoping import resolve_user_scope

from . import services

VIEW = [Permission.PARTNER_VIEW.value]
MANAGE = [Permission.PARTNER_MANAGE.value]


def _q(request: Request) -> dict:
    return {k: request.query_params.get(k) for k in request.query_params}


class PartnerListOnboardView(APIView):
    @property
    def required_permissions(self):
        return MANAGE if self.request.method == "POST" else VIEW

    def get_permissions(self):
        return [IsAuthenticated(), RequirePermissions()]

    def get(self, request: Request) -> Response:
        return Response(services.list_partners(request.user, _q(request)))

    def post(self, request: Request) -> Response:
        return Response(services.onboard(request.data, request.user), status=201)


class PartnerEligibleView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        return Response(services.eligible(_q(request)))


class PartnerMeView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.PLANNING_VIEW.value]

    def get(self, request: Request) -> Response:
        return Response(services.my_partner(request.user))


class PartnerMeActivitiesView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.PLANNING_VIEW.value]

    def get(self, request: Request) -> Response:
        return Response(services.my_activities(request.user))


class PartnerMeScheduleView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.PLANNING_VIEW.value]

    def post(self, request: Request, activity_id: str) -> Response:
        return Response(
            services.schedule_activity(activity_id, request.data, request.user)
        )


class PartnerAssignmentEligibleActivitiesView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.PLANNING_VIEW.value]

    def get(self, request: Request, assignment_id: str) -> Response:
        from apps.activity_catalogue.services import (
            effective_items,
            serialize_item,
            validate_context,
        )
        from apps.partners.models import PartnerAssignment

        assignment = (
            PartnerAssignment.objects.select_related(
                "school", "cluster", "project", "catalogue_item"
            )
            .prefetch_related("allowed_catalogue_items")
            .filter(id=assignment_id)
            .first()
        )
        if assignment is None:
            raise NotFoundError("Partner assignment not found.")
        scope = resolve_user_scope(request.user)
        staff_id = getattr(request.user, "staff_profile_id", None)
        if (
            not scope.country_scope
            and assignment.partner_id not in scope.partner_ids
            and assignment.assigning_staff_id
            not in {
                staff_id,
                getattr(request.user, "user_id", None),
            }
        ):
            raise NotFoundError("Partner assignment not found.")
        ids = (
            [assignment.catalogue_item_id]
            if assignment.catalogue_item_id
            else list(assignment.allowed_catalogue_items.values_list("id", flat=True))
        )
        if not ids:
            # No pinned choice recorded — resolve the assigner's decision from
            # the recorded purpose, exactly as the schedule drawer self-heals.
            from apps.activity_catalogue.services import resolve_assignment_item

            resolved = resolve_assignment_item(
                purpose_of_visit=assignment.purpose_of_visit or None,
                expected_activity_type=assignment.expected_activity_type or None,
            )
            ids = [resolved.id] if resolved else []
        allowed = []
        for item in (
            effective_items()
            .filter(id__in=ids)
            .prefetch_related("intervention_mappings")
        ):
            try:
                validate_context(
                    item,
                    school=assignment.school,
                    cluster=assignment.cluster,
                    project=assignment.project,
                    executor_type="partner",
                )
            except (BadRequest, Forbidden):
                continue
            allowed.append(serialize_item(item))
        return Response(allowed)


class PartnerUpdateView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = MANAGE

    def patch(self, request: Request, partner_id: str) -> Response:
        return Response(services.update(partner_id, request.data, request.user))

    def delete(self, request: Request, partner_id: str) -> Response:
        return Response(services.delete_partner(partner_id, request.user))
