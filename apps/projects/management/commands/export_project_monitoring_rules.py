"""Write the Project Monitoring page's rules for the Go gateway.

Go builds Project Monitoring (/projects/monitoring, apps.frontend.views.
extended_views.project_monitoring_view, apps.projects.monitoring and
pages/projects/monitoring.html) from the vocabularies this command writes to
platform/backend/internal/projectmonitoring/rules.json: who may open the page
and what each role is given on it (a school's profile link and the
workspace strip; the header's export and consolidated-tables links are
plain links the feed does not read), whose lens reads a project
whole, the live and open project statuses, the table's words and tones, the
filters, the SSA interventions and their abbreviations, the impact engine's
thresholds and the shared table page size. A change to
any of them must be exported again; apps/projects/test_project_monitoring_
rules_export.py fails until it is, so the two can never drift.

The doors are not restated: each role's answer is computed here by the gates
the page itself asks, and the strip is the workspace strip the page renders,
read by the feed's own reader.

    python manage.py export_project_monitoring_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/projectmonitoring/rules.json")

PAGE_PATH = "/projects/monitoring"


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

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            # require_page_permission("project_monitoring") and the feed's
            # can_open_url.
            "page": RolePermissionService.can_view_page(user, "project_monitoring")
            and bool(can_open_url(user, PAGE_PATH)),
            # {% school_link %}: a name is a link for a reader of profiles.
            "profiles": bool(can_open_url(user, "/schools/0")),
            "strip": strip(user),
        }
    return out


def rules() -> dict:
    from apps.core.enums import SsaIntervention
    from apps.core.interventions import INTERVENTION_ABBREVIATIONS
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.core.rbac import EdifyRole
    from apps.partners.handover_policy import past_school_rules
    from apps.projects import monitoring, ssa_impact
    from apps.projects.models import (
        GENERAL_INTERVENTION,
        LIVE_PROJECT_STATUSES,
        OPEN_PROJECT_STATUSES,
        ProjectStatus,
    )
    from apps.schools.lifecycle_models import OPERATING_STATUSES

    return {
        "doors": doors(),
        "whole_project_roles": sorted(monitoring.WHOLE_PROJECT_ROLES),
        "coordinator_role": EdifyRole.PROJECT_COORDINATOR.value,
        "withdraw_any_school_roles": list(monitoring.WITHDRAW_ANY_SCHOOL_ROLES),
        "live_statuses": sorted(str(s.value) for s in LIVE_PROJECT_STATUSES),
        "open_statuses": sorted(str(s.value) for s in OPEN_PROJECT_STATUSES),
        "status_labels": {str(v): str(label) for v, label in ProjectStatus.choices},
        "plan_labels": monitoring.PLAN_LABELS,
        "exec_labels": monitoring.EXEC_LABELS,
        "status_labels_row": monitoring.STATUS_LABELS,
        "impact_labels": {k: v[0] for k, v in monitoring.IMPACT_LABELS.items()},
        "stage_filters": [list(pair) for pair in monitoring.STAGE_FILTERS],
        "row_filters": [list(entry[:3]) for entry in monitoring.ROW_FILTERS],
        "general": monitoring.GENERAL,
        "general_intervention": GENERAL_INTERVENTION,
        "interventions": [[str(v), str(label)] for v, label in SsaIntervention.choices],
        "abbreviations": dict(INTERVENTION_ABBREVIATIONS),
        "confirmed": ssa_impact.CONFIRMED,
        "score_min": ssa_impact.SCORE_MIN,
        "score_max": ssa_impact.SCORE_MAX,
        "measured": list(ssa_impact.MEASURED),
        "operating_statuses": [str(s) for s in OPERATING_STATUSES],
        # Go ticks every school of an open project for a hand-over while
        # project hand-overs go past the Champion rule, and refuses to load
        # when they stop.
        "project_handovers_past_school_rules": past_school_rules(project_id="any"),
        "page_size": TABLE_PAGE_SIZE,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write the Project Monitoring page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
