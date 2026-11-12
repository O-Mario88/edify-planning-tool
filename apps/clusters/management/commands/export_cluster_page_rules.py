"""Write the Clusters page's rules for the Go gateway.

Go owns District and Cluster management (owner brief, 2026-11-11). It builds
the Clusters page (/clusters, ClusterDashboardService.get_dashboard_data and
the page's templates) from the vocabularies this command writes to
platform/backend/internal/clusterpage/rules.json: who may open the page and
use each of its doors, the statuses and activity types each figure counts,
the SSA interventions in their order, and the strip's labels. A change to any
of them must be exported again; apps/clusters/test_cluster_page_rules_export.py
fails until it is, so the two can never drift.

The doors are not restated: each role's answer is computed here by the gates
the page itself asks (cluster_views.cluster_list_view).

    python manage.py export_cluster_page_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/clusterpage/rules.json")

#: The strip's figures, in the page's order (get_dashboard_data).
STRIP_KEYS = (
    "clusters_services_total_clusters",
    "clusters_services_schools_in_clusters",
    "clusters_services_without_current_ssa",
    "clusters_services_needing_group_training",
    "clusters_services_not_met_this_quarter",
    "clusters_services_average_cluster_ssa",
    "clusters_services_weakest_intervention",
    "clusters_services_pending_activities",
)


def doors() -> dict:
    """What each role may do on the Clusters page, by the page's own gates."""
    from apps.core.permissions import (
        RolePermissionService,
        can_open_url,
        has_permission,
    )
    from apps.core.rbac import EdifyRole, Permission

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        planning = RolePermissionService.can_view_page(user, "planning")
        out[role.value] = {
            # require_page_permission("clusters") and the feed's can_open_url.
            "page": RolePermissionService.can_view_page(user, "clusters")
            and bool(can_open_url(user, "/clusters")),
            # can_plan_clusters: Schedule Group Training, Schedule Cluster
            # Meeting and Partner to Facilitate.
            "plan": planning and RolePermissionService.can_schedule_activity(user),
            # can_create_clusters: CLUSTER_ASSIGN.
            "create": has_permission(user, Permission.CLUSTER_ASSIGN.value),
            # can_add_cluster_schools: the bulk-assign drawer's own check.
            "add_schools": planning,
            # A card's schools (cluster_schools_partial): the Planning page's
            # permission and the feed's can_open_url.
            "schools_list": planning
            and bool(can_open_url(user, "/partials/clusters/0/schools")),
            # Its rows: Schedule (can_open_schedule_drawer), Assign
            # (can_assign_to_partner), the bulk Schedule visit and Add to
            # Meeting / Training (can_schedule_activity), and the school
            # profile link (can_open_url("/schools/0")).
            "schedule": RolePermissionService.can_open_schedule_drawer(user),
            "assign_partner": RolePermissionService.can_assign_to_partner(user),
            "bulk_schedule": RolePermissionService.can_schedule_activity(user),
            "open_school": bool(can_open_url(user, "/schools/0")),
        }
    return out


def rules() -> dict:
    from django.conf import settings

    from apps.clusters import services
    from apps.core.activity_types import (
        COMPLETED_WORK_STATUSES,
        TRAINING_TYPES,
        VISIT_TYPES,
    )
    from apps.core.enums import SsaIntervention
    from apps.core.metrics.reconciled_registry import source_label_for_key
    from apps.planning.visit_gate import OWN_TABLE_SCHOOL_TYPES
    from apps.schools.lifecycle_models import OPERATING_STATUSES

    return {
        "doors": doors(),
        "operating_statuses": [str(s) for s in OPERATING_STATUSES],
        "own_table_school_types": list(OWN_TABLE_SCHOOL_TYPES),
        "completed_work_statuses": list(COMPLETED_WORK_STATUSES),
        "card_training_types": list(services.CARD_TRAINING_KINDS),
        "planning_done_statuses": list(services.PLANNING_DONE_STATUSES),
        "planning_open_statuses": list(services.PLANNING_OPEN_STATUSES),
        "planning_training_types": list(services.PLANNING_TRAINING_KINDS),
        "planning_school_training_types": list(services.PLANNING_SCHOOL_TRAINING_KINDS),
        "ssa_interventions": [[key.value, key.label] for key in SsaIntervention],
        "strip_labels": [source_label_for_key(key) for key in STRIP_KEYS],
        # The Partner-supported school rule (support_responsibility
        # .visibility_enabled): the switch and its pilot roles and emails.
        "support_rule": {
            "enabled": settings.PARTNER_SUPPORTED_SCHOOL_PLANNING_VISIBILITY_ENABLED,
            "pilot_roles": list(settings.PARTNER_SUPPORTED_SCHOOL_PLANNING_PILOT_ROLES),
            "pilot_users": list(settings.PARTNER_SUPPORTED_SCHOOL_PLANNING_PILOT_USERS),
        },
        # A card's schools: the visit and training types a row's Last Visit
        # and Last Training read.
        "visit_types": [str(t) for t in VISIT_TYPES],
        "training_types": [str(t) for t in TRAINING_TYPES],
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write the Clusters page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
