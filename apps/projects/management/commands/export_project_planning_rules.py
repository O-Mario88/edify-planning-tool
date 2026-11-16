"""Write the Special Projects Planning's rules for the Go gateway.

Go builds the page (/projects/planning:
apps.frontend.views.extended_views.special_projects_planning_view,
apps.projects.planning_service.get_planning and
partials/projects/planning_workspace.html, as the existing feed reads them)
from what this command writes to platform/backend/internal/projectplanning/
rules.json: for each role, whether it may open the page, the workspace strip
it is shown and whether it may schedule, hand a school to a partner,
export and open a school's profile; the figures' labels; the names of the activity types and statuses,
interventions, project categories and school types; the statuses the page
reads as live, returned and done; the school statuses that keep a school on
the list; and the handover statuses not yet scheduled. A change to any of
them must be exported again; apps/projects/
test_project_planning_rules_export.py fails until it is.

    python manage.py export_project_planning_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/projectplanning/rules.json")

PAGE_PERMISSION = "projects"
PATH = "/projects/planning"

#: The strip's figures, then the readiness bands', in the order
#: get_planning builds them.
METRIC_KEYS = (
    "projects_planning_service_total_project_schools",
    "projects_planning_service_ssa_score_required",
    "projects_planning_service_scheduled_this_week",
    "projects_planning_service_planning_completion",
    "projects_planning_service_high_risk_project_schools",
    "projects_planning_service_schools_requiring_follow_up",
    "projects_planning_service_ssa_required",
    "projects_planning_service_ready_for_scheduling",
    "projects_planning_service_ready_for_partner_assignment",
)


def roles() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        page = RolePermissionService.can_view_page(user, PAGE_PERMISSION) and bool(
            can_open_url(user, PATH)
        )
        out[role.value] = {
            "page": page,
            "strip": strip(user, PATH, "partials/_section_nav.html") if page else None,
            "can_schedule": bool(RolePermissionService.can_schedule_activity(user)),
            "can_assign_partner": bool(
                RolePermissionService.can_assign_to_partner(user)
            ),
            "can_export": bool(
                RolePermissionService.can_export(user, "special_projects")
            ),
            "school_links": bool(can_open_url(user, "/schools/0")),
        }
    return out


def rules() -> dict:
    from apps.activities.models import Activity
    from apps.core.metrics.reconciled_registry import source_label_for_key
    from apps.partners.models import PartnerAssignment
    from apps.projects import planning_service as service
    from apps.schools.lifecycle_models import OPERATING_STATUSES
    from apps.schools.models import School

    def choices(model, field):
        return {str(k): str(v) for k, v in model._meta.get_field(field).choices}

    return {
        "roles": roles(),
        "metric_labels": [source_label_for_key(key) for key in METRIC_KEYS],
        "activity_types": choices(Activity, "activity_type"),
        "statuses": choices(Activity, "status"),
        "staff_verification_statuses": dict(Activity._STAFF_VERIFICATION_LABELS),
        "school_types": choices(School, "school_type"),
        "interventions": {
            str(k): str(v) for k, v in service.INTERVENTION_LABELS.items()
        },
        "project_types": {
            str(k): str(v) for k, v in service.PROJECT_TYPE_LABELS.items()
        },
        "active_statuses": sorted(str(s) for s in service.ACTIVE_ACTIVITY_STATES),
        "returned_statuses": sorted(str(s) for s in service.RETURNED_STATES),
        "live_plan_statuses": sorted(str(s) for s in service._LIVE_PLAN_STATES),
        "operating_school_statuses": sorted(str(s) for s in OPERATING_STATUSES),
        "unscheduled_handover_statuses": list(PartnerAssignment.UNSCHEDULED_STATUSES),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Special Projects Planning's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
