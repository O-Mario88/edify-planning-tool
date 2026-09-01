"""Budget endpoints — /api/budget/* (the cost spine)."""

from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import RequirePermissions
from apps.core.rbac import Permission

from . import services

VIEW = [Permission.PLANNING_VIEW.value]
COST_MANAGE = [Permission.COST_SETTINGS_MANAGE.value]
# Country-wide financial rollups (/api/budgets/*) are finance-leadership
# surfaces: BUDGET_VIEW_SUMMARY is held only by CD, RVP, Accountant, IA and
# Admin — not by every PLANNING_VIEW holder (CCEO/PL), who previously could
# read the whole country's totals.
BUDGET_SUMMARY = [Permission.BUDGET_VIEW_SUMMARY.value]


def _q(request: Request) -> dict:
    return {k: request.query_params.get(k) for k in request.query_params}


class CostSettingsView(APIView):
    """GET (list, PLANNING_VIEW) + POST (upsert, COST_SETTINGS_MANAGE)."""

    @property
    def required_permissions(self):
        return COST_MANAGE if self.request.method == "POST" else VIEW

    def get_permissions(self):
        return [IsAuthenticated(), RequirePermissions()]

    def get(self, request: Request) -> Response:
        return Response(services.list_cost_settings(request.user, _q(request)))

    def post(self, request: Request) -> Response:
        return Response(services.upsert_cost_setting(request.data, request.user))


class CostSettingsHistoryView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        key = request.query_params.get("key", "")
        return Response(services.cost_setting_history(key, request.user))


class CostingPreviewView(APIView):
    """POST /api/budget/costing/preview — the central CostingService preview.
    Returns the itemized cost (lines with lineItemType), catalogue provenance,
    missingItems/blockers, and canSchedule. No writes."""

    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def post(self, request: Request) -> Response:
        from .costing_service import preview, planning_preview_owner

        return Response(
            preview(
                request.data,
                minimum=True,
                responsible_user_id=planning_preview_owner(
                    request.user, request.data.get("responsibleStaffId")
                ),
            )
        )


class ManagementCostingPreviewView(APIView):
    """Restricted dual-card preview; never share this serializer with staff."""

    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.ACTIVITY_REFERENCE_COST_VIEW.value]

    def post(self, request: Request) -> Response:
        from .costing_service import management_preview

        return Response(management_preview(request.data))


class RateCardsView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.RATE_CARD_OPERATIONAL_VIEW.value]

    def get(self, request: Request) -> Response:
        from .governance_service import list_rate_cards

        return Response(
            list_rate_cards(request.user, fy=request.query_params.get("fy"))
        )

    def post(self, request: Request) -> Response:
        from .governance_service import create_rate_card_version

        return Response(
            create_rate_card_version(request.user, request.data), status=201
        )


class RateCardLineView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [
        Permission.RATE_CARD_OPERATIONAL_MANAGE.value,
        Permission.RATE_CARD_REFERENCE_MANAGE.value,
    ]

    def post(self, request: Request, card_id: str) -> Response:
        from .governance_service import upsert_rate_card_line

        return Response(upsert_rate_card_line(request.user, card_id, request.data))


class RateCardPublishView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [
        Permission.RATE_CARD_OPERATIONAL_MANAGE.value,
        Permission.RATE_CARD_REFERENCE_MANAGE.value,
    ]

    def post(self, request: Request, card_id: str) -> Response:
        from .governance_service import publish_rate_card

        return Response(publish_rate_card(request.user, card_id))


class ActivityCostReviewView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.COST_AMENDMENT_REQUEST.value]

    def post(self, request: Request, activity_id: str) -> Response:
        from .governance_service import request_cost_review

        return Response(
            request_cost_review(request.user, activity_id, request.data), status=201
        )


class ActivityCostReviewDecisionView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.COST_AMENDMENT_APPROVE.value]

    def post(self, request: Request, review_id: str) -> Response:
        from .governance_service import decide_cost_review

        return Response(decide_cost_review(request.user, review_id, request.data))


class StrategicReserveView(APIView):
    @property
    def required_permissions(self):
        if self.request.method == "POST":
            return [Permission.STRATEGIC_RESERVE_MANAGE.value]
        return [Permission.STRATEGIC_RESERVE_VIEW.value]

    def get_permissions(self):
        return [IsAuthenticated(), RequirePermissions()]

    def get(self, request: Request) -> Response:
        from .governance_service import reserve_summary

        return Response(
            reserve_summary(request.user, fy=request.query_params.get("fy"))
        )

    def post(self, request: Request) -> Response:
        from .governance_service import create_or_update_reserve

        return Response(
            create_or_update_reserve(request.user, request.data), status=201
        )


class StrategicReserveApprovalView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.STRATEGIC_RESERVE_APPROVE.value]

    def post(self, request: Request, reserve_id: str) -> Response:
        from .governance_service import approve_reserve

        return Response(approve_reserve(request.user, reserve_id))


class StrategicReserveActivationView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.STRATEGIC_RESERVE_MANAGE.value]

    def post(self, request: Request, reserve_id: str) -> Response:
        from .governance_service import request_reserve_activation

        return Response(
            request_reserve_activation(request.user, reserve_id, request.data),
            status=201,
        )


class StrategicReserveActivationApprovalView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = [Permission.STRATEGIC_RESERVE_APPROVE.value]

    def post(self, request: Request, activation_id: str) -> Response:
        from .governance_service import approve_reserve_activation

        return Response(approve_reserve_activation(request.user, activation_id))


class BudgetFromScheduleView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        return Response(services.from_schedule(request.user, _q(request)))


class BudgetWeeklyView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        return Response(services.weekly(request.user, _q(request)))


class BudgetBoardView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        return Response(services.board(request.user, _q(request)))


# ── /api/budgets/* — program + admin aggregation by period ──────────────────
class MonthlyBudgetView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = BUDGET_SUMMARY

    def get(self, request: Request) -> Response:
        return Response(services.monthly_budget(_q(request)))


class QuarterlyBudgetView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = BUDGET_SUMMARY

    def get(self, request: Request) -> Response:
        return Response(services.quarterly_budget(_q(request)))


class FyBudgetView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = BUDGET_SUMMARY

    def get(self, request: Request) -> Response:
        return Response(services.fy_budget(_q(request)))


class BudgetLinesListView(APIView):
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        from apps.activities.models import ActivityScheduleCostLine
        from django.db.models import Q

        qs = ActivityScheduleCostLine.objects.all().order_by("-planned_date")

        user = request.user
        from apps.core.scoping import resolve_user_scope

        scope = resolve_user_scope(user)
        if not scope.country_scope and scope.staff_ids:
            q = Q(responsible_user=user.user_id)
            if scope.supervised_staff_ids:
                from apps.accounts.models import StaffProfile

                supervised_user_ids = StaffProfile.objects.filter(
                    id__in=scope.supervised_staff_ids,
                ).values_list("user_id", flat=True)
                q |= Q(responsible_user__in=supervised_user_ids)
            qs = qs.filter(q)

        if request.query_params.get("weekStartDate"):
            qs = qs.filter(week_start_date=request.query_params["weekStartDate"])
        if request.query_params.get("responsibleUser"):
            qs = qs.filter(responsible_user=request.query_params["responsibleUser"])

        data = []
        for line in qs.select_related("activity"):
            data.append(
                {
                    "id": line.id,
                    "activityId": line.activity_id,
                    "activityType": line.activity.activity_type,
                    "label": line.label,
                    "unitCost": line.unit_cost,
                    "quantity": line.quantity,
                    "amount": line.amount,
                    "plannedDate": line.planned_date.isoformat()
                    if line.planned_date
                    else None,
                    "weekStartDate": line.week_start_date.isoformat()
                    if line.week_start_date
                    else None,
                    "weekEndDate": line.week_end_date.isoformat()
                    if line.week_end_date
                    else None,
                    "month": line.month,
                    "quarter": line.quarter,
                    "fiscalYear": line.fiscal_year,
                    "responsibleUser": line.responsible_user,
                    "lineItemType": line.line_item_type,
                }
            )
        return Response(data)
