"""Write the Special Projects My Plan's rules for the Go gateway.

Go builds the page (/projects/my-plan:
apps.frontend.views.extended_views.special_projects_my_plan_view,
apps.projects.my_plan_service.get_my_plan and
partials/projects/my_plan_workspace.html, as the existing feed reads them)
from what this command writes to platform/backend/internal/projectmyplan/
rules.json: for each role, whether it may open the page and the workspace
strip it is shown; the figures' labels; the names of the activity types,
focus interventions and evidence states; the statuses each list and figure
counts or leaves out; the status filter's choices; the type groups; and the
words a finished piece of work is shown with. A change to any of them must be
exported again; apps/projects/test_project_my_plan_rules_export.py fails until
it is.

    python manage.py export_project_my_plan_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/projectmyplan/rules.json")

PAGE_PERMISSION = "projects"
PATH = "/projects/my-plan"

#: The strip's figures, then the Budget & Workflow Status card's, in the
#: order get_my_plan builds them.
METRIC_KEYS = (
    "projects_my_plan_service_planned_this_week",
    "projects_my_plan_service_planned_this_month",
    "projects_my_plan_service_planned_this_quarter",
    "projects_my_plan_service_planned_this_fy",
    "projects_my_plan_service_school_visits_scheduled",
    "projects_my_plan_service_partner_activities",
    "projects_my_plan_service_project_trainings",
    "projects_my_plan_service_completion_readiness",
    "projects_my_plan_service_budget_created",
    "projects_my_plan_service_fund_request_synced",
    "projects_my_plan_service_evidence_pending",
    "projects_my_plan_service_ia_review_pending",
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
        }
    return out


def rules() -> dict:
    from apps.activities.completion_columns import OFFICER_COMPLETED_STATUSES
    from apps.activities.models import Activity
    from apps.core.activity_types import (
        CLUSTER_MEETING_TYPES,
        TRAINING_TYPES,
        VISIT_TYPES,
    )
    from apps.core.metrics.reconciled_registry import source_label_for_key
    from apps.my_plan.services import COMPLETE_LABEL
    from apps.projects import my_plan_service as service
    from apps.projects.dashboard_service import DELIVERED_STATUSES

    def choices(field):
        return {str(k): str(v) for k, v in Activity._meta.get_field(field).choices}

    return {
        "roles": roles(),
        "metric_labels": [source_label_for_key(key) for key in METRIC_KEYS],
        "activity_types": choices("activity_type"),
        "evidence_statuses": choices("evidence_status"),
        "interventions": {
            str(k): str(v) for k, v in service.INTERVENTION_LABELS.items()
        },
        "active_exclusions": sorted(service.ACTIVE_EXCLUSIONS),
        "returned_states": sorted(service.RETURNED_STATES),
        "review_states": sorted(service.REVIEW_STATES),
        "delivered_statuses": list(DELIVERED_STATUSES),
        "officer_completed_statuses": sorted(OFFICER_COMPLETED_STATUSES),
        "visit_types": [str(t) for t in VISIT_TYPES],
        "training_types": [str(t) for t in TRAINING_TYPES],
        "meeting_types": [str(t) for t in CLUSTER_MEETING_TYPES],
        "complete_label": COMPLETE_LABEL,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Special Projects My Plan's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
