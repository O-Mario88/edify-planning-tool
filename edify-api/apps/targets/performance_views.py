"""Performance endpoints — /api/performance/*.

Backend-driven staff performance for CCEO (My Targets), PL (Team Targets),
CD (Country Targets), and HR (staff oversight). All counts come from the
central PerformanceService — no mock numbers, no frontend computation.

Drilldowns return the exact records behind each metric so a card count always
equals its drilldown count.
"""
from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import BadRequest
from apps.core.fy import get_fy_date_range, get_operational_fy
from apps.core.permissions import RequirePermissions
from apps.core.rbac import EdifyRole
from apps.core.scoping import resolve_user_scope

from . import performance as perf


VIEW = ["planning.view"]  # CCEO/PL/CD/HR/IA all have planning.view


def _q(request: Request) -> dict:
    return {k: request.query_params.get(k) for k in request.query_params}


def _period_range(query: dict, fy: str):
    """Resolve (start, end) from the period query params."""
    period = (query.get("period") or "fy").lower()
    quarter = query.get("quarter")
    month = query.get("month")
    return perf.period_bounds(fy, period, quarter, month)


# ── CCEO: My Targets ────────────────────────────────────────────────────────

class MyTargetsView(APIView):
    """GET /api/performance/my-targets — the caller's own metrics + targets."""
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        fy = request.query_params.get("fy") or get_operational_fy()
        staff_id = request.user.staff_profile_id
        if not staff_id:
            return Response({"error": "No staff profile."}, status=400)
        start, end = _period_range(_q(request), fy)
        data = perf.staff_metrics_with_targets(staff_id, fy, start, end)
        return Response(data)


# ── PL: Team Targets ────────────────────────────────────────────────────────

class TeamTargetsView(APIView):
    """GET /api/performance/team-targets — supervised CCEOs' metrics + team aggregate."""
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        scope = resolve_user_scope(request.user)
        fy = request.query_params.get("fy") or get_operational_fy()
        start, end = _period_range(_q(request), fy)
        supervised = scope.supervised_staff_ids or []

        members = []
        team_totals = {}
        for staff_id in (scope.staff_ids + supervised):
            m = perf.staff_metrics_with_targets(staff_id, fy, start, end)
            from apps.accounts.models import StaffProfile
            sp = StaffProfile.objects.filter(id=staff_id).select_related("user").first()
            name = sp.user.name if sp else "Unknown"
            members.append({"staffId": staff_id, "name": name, **m})
            for k, v in m.get("metrics", {}).items():
                team_totals[k] = team_totals.get(k, 0) + v

        return Response({
            "fy": fy,
            "teamTotals": team_totals,
            "members": members,
            "supervisedCount": len(supervised),
        })


# ── CD: Country Targets ─────────────────────────────────────────────────────

class CountryTargetsView(APIView):
    """GET /api/performance/country-targets — country-wide metrics by staff/PL team."""
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

        fy = request.query_params.get("fy") or get_operational_fy()
        start, end = _period_range(_q(request), fy)
        # All active field staff (CCEO/PL).
        staff = list(StaffProfile.objects.filter(
            deleted_at__isnull=True, user__is_active=True,
            user__active_role__in=[EdifyRole.CCEO.value, EdifyRole.COUNTRY_PROGRAM_LEAD.value],
        ).select_related("user"))

        all_metrics = {}
        by_role = {"CCEO": {}, "PL": {}}
        for sp in staff:
            m = perf.staff_metrics(sp.id, fy, start, end)
            for k, v in m.items():
                all_metrics[k] = all_metrics.get(k, 0) + v
                role_key = "PL" if sp.user.active_role == EdifyRole.COUNTRY_PROGRAM_LEAD.value else "CCEO"
                by_role[role_key][k] = by_role[role_key].get(k, 0) + v

        return Response({
            "fy": fy,
            "countryTotals": all_metrics,
            "byRole": by_role,
            "staffCount": len(staff),
        })


# ── HR: Staff performance ───────────────────────────────────────────────────

class HrStaffView(APIView):
    """GET /api/performance/hr/staff — every staff member's metrics + workload."""
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ["staff.performance.view"]

    def get(self, request: Request) -> Response:
        from apps.accounts.models import StaffProfile

        fy = request.query_params.get("fy") or get_operational_fy()
        start, end = _period_range(_q(request), fy)
        staff = list(StaffProfile.objects.filter(
            deleted_at__isnull=True, user__is_active=True,
        ).select_related("user"))

        rows = []
        for sp in staff:
            m = perf.staff_metrics(sp.id, fy, start, end)
            wl = perf.workload_context(sp.id) if hasattr(perf, "workload_context") else {}
            rows.append({
                "staffId": sp.id,
                "name": sp.user.name,
                "role": sp.user.active_role,
                "email": sp.user.email,
                **m,
                **wl,
            })
        return Response({"fy": fy, "staff": rows, "count": len(rows)})


class HrRisksView(APIView):
    """GET /api/performance/hr/risks — staff at risk / underperforming / over-workload."""
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = ["staff.performance.view"]

    def get(self, request: Request) -> Response:
        from apps.accounts.models import StaffProfile

        fy = request.query_params.get("fy") or get_operational_fy()
        start, end = _period_range(_q(request), fy)
        staff = list(StaffProfile.objects.filter(
            deleted_at__isnull=True, user__is_active=True,
            user__active_role__in=[EdifyRole.CCEO.value, EdifyRole.COUNTRY_PROGRAM_LEAD.value],
        ).select_related("user"))

        at_risk = []
        over_workload = []
        for sp in staff:
            m = perf.staff_metrics(sp.id, fy, start, end)
            planned = m.get("total_planned", 0)
            completed = m.get("total_completed", 0)
            wl = perf.workload_context(sp.id) if hasattr(perf, "workload_context") else {}
            school_count = wl.get("assignedSchoolCount", 0)
            # At risk: completion rate < 50% with planned work.
            if planned > 0 and completed / planned < 0.5:
                at_risk.append({"staffId": sp.id, "name": sp.user.name, "planned": planned, "completed": completed})
            # Over workload: > 30 assigned schools.
            if school_count > 30:
                over_workload.append({"staffId": sp.id, "name": sp.user.name, "schoolCount": school_count})

        return Response({"fy": fy, "atRisk": at_risk, "overWorkload": over_workload})


# ── Drilldown ───────────────────────────────────────────────────────────────

class DrilldownView(APIView):
    """GET /api/performance/drilldown?staff_id=&metric=&fy=&period= — the exact
    records counted by a metric. Card count == drilldown count."""
    permission_classes = [IsAuthenticated, RequirePermissions]
    required_permissions = VIEW

    def get(self, request: Request) -> Response:
        staff_id = request.query_params.get("staffId")
        metric = request.query_params.get("metric")
        fy = request.query_params.get("fy") or get_operational_fy()
        if not staff_id or not metric:
            raise BadRequest("staffId and metric are required.")
        start, end = _period_range(_q(request), fy)
        rows = perf.drilldown(staff_id, metric, fy, start, end)
        return Response({"metric": metric, "fy": fy, "count": len(rows), "items": rows})
