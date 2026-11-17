"""Write Programme Rollout's rules for the Go gateway.

Go draws the Programme Lead's Programme Rollout (/programme-rollout,
apps.frontend.views.programme_rollout_views over
apps.analytics.programme_rollout_service) from what this command writes to
platform/backend/internal/programmerollout/rules.json: who opens the page,
who chooses a lead, the views, the statuses each figure reads, the training
types, the interventions' order, words and abbreviations, the activity
labels, the page sizes and the observation kind. A change to any of them
must be exported again; apps/frontend/test_programme_rollout_rules_export.py
fails until it is.

    python manage.py export_programme_rollout_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

EXPORT_PATH = Path("platform/backend/internal/programmerollout/rules.json")

#: The officers' table shows this many rows (partials/programme_rollout/
#: trainings.html `rollout.officers|slice:":60"`).
OFFICER_ROWS = 60


def _values(items) -> list[str]:
    return [str(getattr(i, "value", i)) for i in items]


def rules() -> dict:
    from apps.analytics import programme_rollout_service as rollout
    from apps.cce_leadership.models import EngagementKind
    from apps.core.interventions import INTERVENTION_LABELS, intervention_abbr
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.schools.lifecycle_models import OPERATING_STATUSES
    from apps.schools.management.commands.export_school_directory_rules import (
        _role_user,
    )

    return {
        "page_roles": sorted(
            role.value
            for role in EdifyRole
            if RolePermissionService.can_view_page(
                _role_user(role.value), "programme_rollout"
            )
            and can_open_url(_role_user(role.value), rollout.PAGE_URL)
        ),
        "program_lead": rollout.PROGRAM_LEAD,
        "lead_choosers": list(rollout.LEAD_CHOOSERS),
        "views": list(rollout.VIEWS),
        "default_view": rollout.DEFAULT_VIEW,
        "upcoming_days": rollout.UPCOMING_DAYS,
        "upcoming_rows": rollout.UPCOMING_ROWS,
        "training_types": _values(rollout.TRAINING_TYPES),
        "school_training_types": _values(rollout.SCHOOL_TRAINING_TYPES),
        "cluster_training_types": _values(rollout.CLUSTER_TRAINING_TYPES),
        "not_planned_statuses": list(rollout.NOT_PLANNED_STATUSES),
        "live_statuses": list(rollout.LIVE_STATUSES),
        "in_review_statuses": list(rollout.IN_REVIEW_STATUSES),
        "completed_statuses": _values(rollout.COMPLETED_WORK_STATUSES),
        "cluster_credit_statuses": _values(rollout.CLUSTER_CREDIT_STATUSES),
        "intervention_order": list(rollout.INTERVENTION_ORDER),
        "intervention_labels": {str(k): str(v) for k, v in INTERVENTION_LABELS.items()},
        "intervention_abbreviations": {
            code: intervention_abbr(code) for code in rollout.INTERVENTION_ORDER
        },
        "status_labels": {str(k): str(v) for k, v in rollout.STATUS_LABELS.items()},
        "type_labels": {str(k): str(v) for k, v in rollout.TYPE_LABELS.items()},
        "operating_statuses": _values(OPERATING_STATUSES),
        "observation_kind": str(EngagementKind.TRAINING_OBSERVATION),
        "page_size": TABLE_PAGE_SIZE,
        "officer_rows": OFFICER_ROWS,
        "ssa": _ssa(),
    }


def _ssa() -> dict:
    """The Self-Assessments view: the record and assignment statuses each
    state reads, the collection types, and the heatmap's columns."""
    from apps.analytics import programme_rollout_service as rollout
    from apps.analytics.pl_analytics_service import SSA_INTERVENTIONS
    from apps.partners.models import PartnerAssignment

    return {
        "confirmed_status": rollout.SSA_CONFIRMED,
        "awaiting_record_statuses": list(rollout.SSA_AWAITING_RECORD_STATUSES),
        "collection_types": list(rollout._ssa_collection_types()),
        "unscheduled_assignment_statuses": list(PartnerAssignment.UNSCHEDULED_STATUSES),
        "matrix_interventions": [
            [value, label, code] for value, label, code in SSA_INTERVENTIONS
        ],
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write Programme Rollout's rules for the Go gateway."

    def handle(self, *args, **options):
        path = Path(settings.BASE_DIR) / EXPORT_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"wrote {EXPORT_PATH}")
