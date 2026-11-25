"""Write Team Targets' page rules for Go.

Go builds /team-targets and Team Oversight's targets lens
(apps.frontend.views.staff_views.team_targets_view over
apps.targets.team_targets.PLTeamTargetsService.get_page) from the target engine
(platform/backend/internal/targets) and what this command writes to
platform/backend/internal/teamtargets/rules.json: the activity types an
Activity SF ID is owed for, the statuses that count as done, each blocker's
recommendation, the statuses a day's drawer leaves out, the ranked order's name, the risk notices' events and the
labels of the figures the page binds to the metric registry. A change to any
of them must be exported again; apps/targets/test_team_targets_rules_export.py
fails until it is.

    python manage.py export_team_targets_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

EXPORT_PATH = Path("platform/backend/internal/teamtargets/rules.json")

#: The registered figures the page draws (render_precomputed_metric_item).
METRIC_KEYS = (
    "targets_team_targets_high_risk_staff",
    "targets_team_targets_activity_sf_id_compliance",
    "targets_team_targets_awaiting_ia",
    "targets_team_targets_missing_sf_ids",
    "targets_team_targets_returned_by_ia",
    "targets_team_targets_team_achievement",
    "targets_team_targets_monthly_on_track",
    "targets_team_targets_at_risk_staff",
    "targets_team_targets_current_quarter",
    "targets_team_targets_fy_achievement",
    "targets_team_targets_recovery_plans",
)


def rules() -> dict:
    from apps.analytics.pl_analytics_service import COMPLETED_STATUSES, VISIT_TYPES
    from apps.core.permissions import RolePermissionService
    from apps.core.rbac import EdifyRole
    from apps.schools.management.commands.export_school_directory_rules import (
        _role_user,
    )
    from apps.core.metrics.payload import render_precomputed_metric_item
    from apps.projects.models import LIVE_PROJECT_STATUSES
    from apps.core.enums import ActivityType
    from apps.frontend.views.staff_views import VALIDATION_BACKLOGS
    from apps.targets import team_targets as tt
    from apps.targets.models import CatchUpStatus
    from apps.targets.team_targets import (
        NOT_IN_PLAN_ACTIVITY_STATUSES,
        NOT_STARTED_ACTIVITY_STATUSES,
    )

    return {
        # require_page_permission("team_targets"): who may open the page.
        "page_roles": sorted(
            r.value
            for r in EdifyRole
            if RolePermissionService.can_view_page(_role_user(r.value), "team_targets")
        ),
        "sf_required_types": sorted(tt.SF_REQUIRED_TYPES),
        "completed_statuses": sorted(str(s) for s in COMPLETED_STATUSES),
        "visit_types": sorted(str(t) for t in VISIT_TYPES),
        # team_project_priorities: the Projects a team member's work is in.
        "live_project_statuses": sorted(s.value for s in LIVE_PROJECT_STATUSES),
        "recommendations": {
            key: list(value) for key, value in sorted(tt.RECOMMENDATIONS.items())
        },
        "order_ranked": tt.ORDER_RANKED,
        "catchup_status_labels": {str(k): str(v) for k, v in CatchUpStatus.choices},
        # The backlog drawers (staff_views): each activity's type as it reads,
        # and each validation tile's words.
        "activity_type_labels": {str(k): str(v) for k, v in ActivityType.choices},
        "validation_backlogs": {
            key: {name: str(value) for name, value in copy.items()}
            for key, copy in VALIDATION_BACKLOGS.items()
        },
        # sync_completion: the work a catch-up plan's activities are in.
        "not_in_plan_statuses": sorted(str(s) for s in NOT_IN_PLAN_ACTIVITY_STATUSES),
        "not_started_statuses": sorted(str(s) for s in NOT_STARTED_ACTIVITY_STATUSES),
        # day_detail: the work a day's drawer leaves out.
        "returned_statuses": sorted(str(s) for s in tt.RETURNED_STATUSES),
        "risk_events": [tt.TEAM_TARGET_STAFF_AT_RISK, tt.TEAM_TARGET_OWN_AT_RISK],
        "metric_labels": {
            key: render_precomputed_metric_item(key, "0")["label"]
            for key in METRIC_KEYS
        },
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write Team Targets' page rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"wrote {EXPORT_PATH}")
