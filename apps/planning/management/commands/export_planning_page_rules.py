"""Write the Planning page's rules for the Go gateway.

Go owns Activity planning and scheduling (owner brief, 2026-11-11). It
builds the Planning page (/planning, planning_views.planning_dashboard_view,
PlanningDashboardService.get_dashboard_data and the page's templates) from
the vocabularies this command writes to
platform/backend/internal/planningpage/rules.json: who may open the page and
use each of its doors, the statuses and activity types each figure and row
counts, the filter menus, the strip's labels, and the rules a person's
counted visits and visit target are read by. A change to any of them must
be exported again; apps/planning/test_planning_page_rules_export.py fails
until it is, so the two can never drift.

    python manage.py export_planning_page_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/planningpage/rules.json")

#: The strip's figures, in the page's order (get_dashboard_data), the
#: "Not grouped in cluster" figure the service inserts third left aside.
STRIP_KEYS = (
    "planning_planning_service_ready_for_support",
    "planning_planning_service_ssa_required",
    "planning_planning_service_clusters_needing_action",
    "planning_planning_service_core_package_gaps",
    "planning_planning_service_partner_pending_schedule",
    "planning_planning_service_in_my_plan",
    "planning_ssa_informed_plans",
    "planning_planning_service_cost_blocked",
    "planning_planning_service_data_cleanup_required",
)


def doors() -> dict:
    """What each role may do on the page, by the page's own gates."""
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            # require_page_permission("planning") and the feed's can_open_url.
            "page": RolePermissionService.can_view_page(user, "planning")
            and bool(can_open_url(user, "/planning")),
            # A row's Schedule (_may_open_schedule_drawer) and Assign, the
            # bar's Assign to partner and Schedule visit.
            "schedule": RolePermissionService.can_open_schedule_drawer(user),
            "assign_partner": RolePermissionService.can_assign_to_partner(user),
            "bulk_schedule": RolePermissionService.can_schedule_activity(user),
            # The row's "Open … school profile" link.
            "open_school": bool(can_open_url(user, "/schools/0")),
        }
    return out


def counted_visits() -> dict:
    """staff_plan.own_workload's count: a person's counted visits of the year
    (country_oversight.rules.counted_visit_q, planned_q, staff_delivery_q)
    against the visit target of the planning role they hold."""
    from apps.core.enums import SchoolType
    from apps.planning import staff_plan
    from apps.planning.country_oversight import policy, rules
    from apps.schools.lifecycle_service import OPERATING_STATUSES

    return {
        "visit_shape_types": [str(t) for t in rules.VISIT_SHAPE_TYPES],
        "companion_purpose": rules.COMPANION_PURPOSE,
        "outreach_purposes": list(rules.OUTREACH_PURPOSES),
        "data_collection_purposes": list(rules.DATA_COLLECTION_PURPOSES),
        "data_collection_types": [str(t) for t in rules.DATA_COLLECTION_TYPES],
        "kind_purposes": sorted(str(p) for p in rules._PURPOSE_KIND),
        "planned_states": sorted(policy.PLANNED_STATES),
        "program_lead_role": rules.PROGRAM_LEAD_ROLE,
        "cceo_role": rules.CCEO_ROLE,
        "visit_targets": dict(rules.VISIT_TARGETS),
        "core_types": list(staff_plan.CORE_TYPES),
        # own_workload's share-out (rules.workload): the schools a person
        # holds, operating (active_schools), Core and the Client rule types.
        "operating_statuses": sorted(str(s) for s in OPERATING_STATUSES),
        "core_type": SchoolType.CORE.value,
        "client_rule_types": list(rules.CLIENT_RULE_TYPES),
        "core_staff_visits": rules.REQUIREMENTS[SchoolType.CORE.value].staff_visits,
        "core_partner_visits": rules.REQUIREMENTS[SchoolType.CORE.value].partner_visits,
    }


def rules() -> dict:
    from django.conf import settings

    from apps.budget.models import RateCardKind, RateCardStatus
    from apps.core.activity_types import (
        COMPLETED_WORK_STATUSES,
        NOT_IN_PLAN_ACTIVITY_STATUSES,
    )
    from apps.core.enums import PlanningReadiness, SsaStatus
    from apps.core.metrics.reconciled_registry import source_label_for_key
    from apps.planning import planning_service as service
    from apps.planning.planning_support import PLANNING_SUPPORT_FILTERS
    from apps.planning.visit_gate import OWN_TABLE_SCHOOL_TYPES
    from apps.ssa.plan_alignment import INFORMED

    return {
        "doors": doors(),
        "client_tab_types": list(service.CLIENT_TAB_TYPES),
        "partner_pending_statuses": list(service.PARTNER_PENDING_STATUSES),
        "partner_live_statuses": list(service.PARTNER_LIVE_STATUSES),
        "not_active_work_statuses": list(service.NOT_ACTIVE_WORK_STATUSES),
        "row_visit_count_types": list(service.ROW_VISIT_COUNT_TYPES),
        "row_training_count_types": list(service.ROW_TRAINING_COUNT_TYPES),
        "row_attendance_types": list(service.ROW_ATTENDANCE_TYPES),
        "live_plan_statuses": list(service.LIVE_PLAN_STATUSES),
        "not_scheduled_statuses": list(service.NOT_SCHEDULED_STATUSES),
        "not_in_the_plan": [str(s) for s in service._NOT_IN_THE_PLAN],
        "not_in_plan_activity_statuses": list(NOT_IN_PLAN_ACTIVITY_STATUSES),
        "completed_work_statuses": list(COMPLETED_WORK_STATUSES),
        "informed_alignments": [str(a) for a in INFORMED],
        "own_table_school_types": list(OWN_TABLE_SCHOOL_TYPES),
        "readiness_choices": [
            [str(v), str(label)] for v, label in PlanningReadiness.choices
        ],
        "ssa_status_choices": [[str(v), str(label)] for v, label in SsaStatus.choices],
        "support_filters": [list(pair) for pair in PLANNING_SUPPORT_FILTERS],
        "strip_labels": [source_label_for_key(key) for key in STRIP_KEYS],
        "counted_visits": counted_visits(),
        # active_catalogue: the country's live published operational card.
        "catalogue": {
            "country": getattr(settings, "COUNTRY", "Uganda"),
            "kind": str(RateCardKind.OPERATIONAL),
            "status": str(RateCardStatus.PUBLISHED),
        },
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write the Planning page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
