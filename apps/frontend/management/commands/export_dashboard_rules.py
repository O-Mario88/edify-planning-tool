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
            }
            for key, helper, _icon, _variant in views.CCEO_KPI_METRICS
        ],
        "views": [[key, label] for key, label, _ in views.CCEO_VIEW_TABS],
        "opens": {
            name: bool(can_open_url(user, path)) for name, path in OFFICER_LINKS.items()
        },
    }


def rules() -> dict:
    return {"officer": officer()}


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write a field officer's Home rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
