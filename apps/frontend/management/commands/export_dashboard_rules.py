"""Write a field officer's Home rules for the Go gateway.

Go builds a CCEO's Home (/dashboard, apps.frontend.views.dashboard_views
.dashboard_view, pages/dashboards/cceo.html) from the vocabularies this
command writes to platform/backend/internal/dashboard/rules.json: the
statuses and types the week at a glance and Do next read, the figures'
labels, the views' tabs, and which of the links the page draws an officer
may open (the week's own lists are My Plan's rows, exported with My Plan). A
change to any of them must be exported again;
apps/frontend/test_dashboard_rules_export.py fails until it is, so the two
can never drift.

    python manage.py export_dashboard_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/dashboard/rules.json")

#: The links the page draws for an officer, by shape: each answer is the gate
#: the page itself asks (can_open), for an id that stands for any.
OFFICER_LINKS = {
    "complete": "/activities/0/complete",
    "start": "/activities/0/start",
    "details": "/my-plan/0",
    "planning": "/planning",
    "cluster": "/clusters/0",
}


def officer() -> dict:
    from apps.core.activity_types import (
        COMPLETED_WORK_STATUSES,
        NOT_STARTED_ACTIVITY_STATUSES,
        UNDER_WAY_ACTIVITY_STATUSES,
        VISIT_TYPES,
    )
    from apps.core.metrics import render_precomputed_metric_item
    from apps.core.permissions import can_open_url
    from apps.core.rbac import EdifyRole
    from apps.frontend.views import dashboard_views as views
    from apps.my_plan.past_due_service import RETURNED_STATUSES

    user = _role_user(EdifyRole.CCEO.value)
    return {
        "role": EdifyRole.CCEO.value,
        "completed_statuses": list(COMPLETED_WORK_STATUSES),
        "under_way_statuses": list(UNDER_WAY_ACTIVITY_STATUSES),
        "not_started_statuses": list(NOT_STARTED_ACTIVITY_STATUSES),
        "done_statuses": list(views.CCEO_DONE_STATUSES),
        "returned_statuses": list(RETURNED_STATUSES),
        "visit_types": list(VISIT_TYPES),
        "cluster_types": list(views.CCEO_CLUSTER_TYPES),
        "metrics": [
            {
                "label": render_precomputed_metric_item(key, "0")["label"],
                "helper": helper,
                "href": views.CCEO_KPI_LINKS.get(key, ""),
            }
            for key, helper, _icon, _variant in views.CCEO_KPI_METRICS
        ],
        "views": [[key, label] for key, label, _ in views.CCEO_VIEW_TABS],
        "opens": {
            name: bool(can_open_url(user, path)) for name, path in OFFICER_LINKS.items()
        },
    }


def lead() -> dict:
    """What a Programme Lead's Home reads by
    (apps.analytics.pl_dashboard_service): its views, the statuses and types
    the team pulse counts, how many of each list it reads, and the pages its
    figures and cards open."""
    from apps.analytics import pl_analytics_service as analytics
    from apps.analytics import pl_dashboard_service as pl
    from apps.core.permissions import can_open_url
    from apps.core.rbac import EdifyRole
    from apps.hr.leave_services import _APPROVER_SENIORITY
    from apps.schools.lifecycle_models import OPERATING_STATUSES

    return {
        "role": EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        "default_view": pl.DEFAULT_VIEW,
        "views": list(pl.VIEWS),
        "view_aliases": dict(pl.VIEW_ALIASES),
        "view_tabs": [[key, label] for key, label, _ in pl.VIEW_TABS],
        "released_statuses": list(pl.RELEASED_STATUSES),
        "partner_settled_statuses": list(pl.PARTNER_SETTLED_STATUSES),
        "completed_statuses": list(pl.COMPLETED_STATUSES),
        "training_types": list(pl.TRAINING_TYPES),
        "ssa_collection_types": list(pl.SSA_COLLECTION_TYPES),
        "operating_statuses": [str(s) for s in OPERATING_STATUSES],
        "approver_seniority": dict(_APPROVER_SENIORITY),
        "list_rows": pl.LIST_ROWS,
        "delegated_back_days": pl.DELEGATED_BACK_DAYS,
        "attention_limit": pl.ATTENTION_LIMIT,
        "team_oversight_url": pl.TEAM_OVERSIGHT_URL,
        # The attention cards (leadership_attention) and what they read.
        "cceo_backlog_statuses": list(analytics.CCEO_BACKLOG_STATUSES),
        "not_in_plan_statuses": list(analytics.NOT_IN_PLAN_ACTIVITY_STATUSES),
        "visit_types": list(analytics.VISIT_TYPES),
        "cluster_meeting_types": list(analytics.CLUSTER_MEETING_TYPES),
        "cceo_school_capacity": pl.CCEO_SCHOOL_CAPACITY,
        "cceo_weekly_activity_capacity": pl.CCEO_WEEKLY_ACTIVITY_CAPACITY,
        "leave_lookahead_days": pl.LEAVE_LOOKAHEAD_DAYS,
        "card_urls": {
            "escalations": pl.ESCALATIONS_URL,
            "quality_flags": pl.QUALITY_FLAGS_URL,
            "training_feedback": pl.TRAINING_FEEDBACK_URL,
            "regional_coaching": pl.REGIONAL_COACHING_URL,
            "team_targets": pl.TEAM_TARGETS_URL,
            "team_availability": pl.TEAM_AVAILABILITY_URL,
            "partner_oversight": pl.PARTNER_OVERSIGHT_URL,
        },
        # Which of the pages the header may offer a lead opens for them.
        "opens": {
            path: bool(
                can_open_url(_role_user(EdifyRole.COUNTRY_PROGRAM_LEAD.value), path)
            )
            for path in (
                pl.ESCALATIONS_URL,
                pl.QUALITY_FLAGS_URL,
                pl.TRAINING_FEEDBACK_URL,
                pl.REGIONAL_COACHING_URL,
                pl.TEAM_TARGETS_URL,
                pl.TEAM_AVAILABILITY_URL,
                pl.PARTNER_OVERSIGHT_URL,
                pl.TEAM_OVERSIGHT_URL,
            )
        },
    }


def rules() -> dict:
    return {"officer": officer(), "lead": lead()}


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write a field officer's Home rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
