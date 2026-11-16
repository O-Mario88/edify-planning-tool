"""Write the Special Projects page's rules for the Go gateway.

Go builds the Projects page (/projects: extended_views.projects_list_view,
_projects_context, apps.projects.dashboard_service.get_dashboard and
pages/projects/index.html) from what this command writes to
platform/backend/internal/projectspage/rules.json: what each role is given
(the page, its New Project button, the card's Export to Excel, the strip
above the filters, whether a school name opens its profile and which of the
follow-up steps it can open); the project types, the status filter and the
derived status bands; the activity statuses and types the figures count; the
payment states that count as disbursed; the intervention labels; and the
figures' labels. A change to any of them must be exported again;
apps/projects/test_projects_page_rules_export.py fails until it is.

    python manage.py export_projects_page_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/projectspage/rules.json")

PAGE_PATH = "/projects"

#: The follow-up steps a school's row can link to, each asked with
#: can_open_url as the template's `can_open` filter asks it.
FOLLOW_UP_PATHS = ("/projects/planning", "/projects/my-plan", "/clusters")

#: The figures the page shows, in the order get_dashboard builds them.
METRIC_KEYS = (
    "projects_dashboard_service_total_projects",
    "projects_dashboard_service_active_projects",
    "projects_dashboard_service_project_schools",
    "projects_dashboard_service_teachers_trained",
    "projects_dashboard_service_leaders_trained",
    "projects_dashboard_service_learners_reached",
    "projects_dashboard_service_assigned_partners",
    "projects_dashboard_service_budget_generated",
    "projects_dashboard_service_activities_in_my_plan",
    "projects_dashboard_service_evidence_pending",
    "projects_dashboard_service_ia_pending",
    "projects_dashboard_service_closed_activities",
)

#: The payment states the Budget & Execution utilisation counts as disbursed
#: (get_dashboard's `disbursed`).
DISBURSED_PAYMENT_STATUSES = (
    "accountant_cleared",
    "paid",
    "closed",
    "netsuite_accountability",
)


def strip(user):
    """The workspace strip the page shows ``user``, as the feed reads it (a
    linkTabs block), or None when there is none."""
    from django.template.loader import render_to_string

    from apps.core.navigation import build_workspace
    from apps.mobile_feed import page_blocks

    html = render_to_string(
        "partials/_section_nav.html", {"workspace": build_workspace(user, PAGE_PATH)}
    )
    blocks = page_blocks.read(html)["blocks"]
    return blocks[0]["linkTabs"] if blocks else None


def doors() -> dict:
    """What each role is given on the page, by the page's own gates."""
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.frontend.views.extended_views import _can_configure_project_priorities

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            # require_page_permission("projects") and the feed's can_open_url.
            "page": RolePermissionService.can_view_page(user, "projects")
            and bool(can_open_url(user, PAGE_PATH)),
            # The header's New Project (else Add Eligible Schools).
            "create": bool(_can_configure_project_priorities(user)),
            # The card's Export to Excel.
            "export": RolePermissionService.can_export(user, PAGE_PATH),
            "strip": strip(user),
            # {% school_link %}: a name is a link for a reader of profiles.
            "profiles": bool(can_open_url(user, "/schools/0")),
            "opens": {path: bool(can_open_url(user, path)) for path in FOLLOW_UP_PATHS},
        }
    return out


def rules() -> dict:
    from apps.core.activity_types import TRAINING_TYPES, VISIT_TYPES
    from apps.core.enums import SsaIntervention
    from apps.core.metrics.reconciled_registry import source_label_for_key
    from apps.projects import dashboard_service as dashboard
    from apps.projects.models import ProjectCategory

    return {
        "doors": doors(),
        "categories": [[str(v), str(label)] for v, label in ProjectCategory.choices],
        "status_filters": [list(pair) for pair in dashboard.STATUS_FILTER_OPTIONS],
        "status_filter_labels": {
            key: sorted(labels)
            for key, labels in dashboard.STATUS_FILTER_LABELS.items()
        },
        "delivered_statuses": list(dashboard.DELIVERED_STATUSES),
        "not_in_plan_statuses": list(dashboard.NOT_IN_PLAN_STATUSES),
        "ssa_types": list(dashboard.SSA_TYPES),
        "training_types": sorted(TRAINING_TYPES),
        "visit_types": sorted(VISIT_TYPES),
        "disbursed_payment_statuses": list(DISBURSED_PAYMENT_STATUSES),
        "interventions": [[str(v), str(label)] for v, label in SsaIntervention.choices],
        "metric_labels": [source_label_for_key(key) for key in METRIC_KEYS],
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Special Projects page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
