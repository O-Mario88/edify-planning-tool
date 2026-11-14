"""Write My Team's rules for Go.

Go builds the Programme Lead's My Team page (/my-team:
apps.frontend.views.staff_views.my_team_view, apps.hr.team_roster and
pages/my_team/index.html) from what this command writes to
platform/backend/internal/myteam/rules.json: who may open the page; the
statuses that make delivery verified, that leave the plan and that wait on the
lead; the review stages that wait on the manager or close the review, and
every stage's words; the risk words for each pace band and the bands counted
at risk; the development, escalation, policy and leave states it reads; the
coaching kinds' words; the school statuses that are operating; the tiles'
labels; and the page size. A change to any of them must be exported again;
apps/hr/test_my_team_rules_export.py fails until it is.

    python manage.py export_my_team_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/myteam/rules.json")

#: The six tiles, in the page's order (staff_views._team_metrics).
TILES = [
    "Officers on My Team",
    "Officers On Pace for FY Targets",
    "Officers at Target Risk This Month",
    "Team Handoffs Waiting on You",
    "Team Exceptions Needing Your Action",
    "Team Portfolio SSA Coverage This FY",
]


def rules() -> dict:
    from apps.analytics.pl_analytics_service import VERIFIED_STATUSES
    from apps.cce_leadership.coaching import KIND_LABELS
    from apps.core.activity_types import NOT_IN_PLAN_ACTIVITY_STATUSES
    from apps.core.metrics.reconciled_registry import (
        key_for_source_label,
        source_label_for_key,
    )
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.documents.models import READABLE_STATUSES, AcknowledgementState
    from apps.flags.models import EscalationStatus
    from apps.frontend.views.staff_views import TEAM_METRIC_SOURCE
    from apps.hr import hr_exceptions, team_roster
    from apps.hr.models import ReviewStage
    from apps.professional_development.models import PDStatus
    from apps.schools.lifecycle_models import OPERATING_STATUSES

    return {
        "page_roles": sorted(
            role.value
            for role in EdifyRole
            if RolePermissionService.can_view_page(_role_user(role.value), "my_team")
            and can_open_url(_role_user(role.value), "/my-team")
        ),
        "verified_statuses": list(VERIFIED_STATUSES),
        "not_in_plan_statuses": sorted(NOT_IN_PLAN_ACTIVITY_STATUSES),
        "awaiting_pl_status": team_roster.AWAITING_PL_STATUS,
        "manager_stages": list(team_roster.MANAGER_STAGES),
        "closed_stages": ["closed", "signed_and_archived"],
        "closed_review_statuses": ["Completed", "Closed"],
        "review_stages": {k: str(v) for k, v in ReviewStage.choices},
        "high_risk_bands": list(team_roster.HIGH_RISK_BANDS),
        "risk_words": {k: list(v) for k, v in team_roster._RISK_WORDS.items()},
        "pd_supervisor_status": PDStatus.SUBMITTED_TO_SUPERVISOR.value,
        "escalation_resolved": EscalationStatus.RESOLVED.value,
        "readable_document_statuses": sorted(str(s) for s in READABLE_STATUSES),
        "pending_acknowledgement": AcknowledgementState.PENDING.value,
        "leave_decision_days": hr_exceptions.LEAVE_DECISION_DAYS,
        "review_overdue_days": hr_exceptions.REVIEW_OVERDUE_DAYS,
        "coaching_kinds": {str(k): str(v) for k, v in KIND_LABELS.items()},
        "operating_statuses": [str(s) for s in OPERATING_STATUSES],
        "tile_labels": {
            label: source_label_for_key(key_for_source_label(TEAM_METRIC_SOURCE, label))
            for label in TILES
        },
        "page_size": TABLE_PAGE_SIZE,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write My Team's rules for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
