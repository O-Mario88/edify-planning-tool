"""Write the staff logs' rules for the Go gateway.

Go builds the visits log (/visits: apps.frontend.views.staff_views.
visits_log_view, pages/visits/index.html) and the trainings log (/trainings:
trainings_log_view, pages/trainings/index.html), as the existing feed reads them,
from what this command writes to platform/backend/internal/stafflogs/rules.json:
for each role, whether it may open each log and whether a school's name opens
its profile; the activity types a visit and a training are; the roles the
trainings log sends elsewhere; the statuses the header counts as
completed and as not yet finished in the field; the row limit; and the words
status_label keeps as initialisms. A change to any of them must be exported
again; apps/frontend/test_staff_logs_rules_export.py fails until it is.

    python manage.py export_staff_logs_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/stafflogs/rules.json")

PAGE_PERMISSION = "my_plan"
VISITS_PATH = "/visits"
TRAININGS_PATH = "/trainings"
#: trainings_log_view sends these roles elsewhere (the Programme Lead to
#: Programme Rollout, the CCEO to My Plan).
TRAININGS_REDIRECTED = ["Program Lead", "CCEO"]
#: visits_log_view's visits_qs[:100].
ROW_LIMIT = 100


def roles() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            "visits": RolePermissionService.can_view_page(user, PAGE_PERMISSION)
            and bool(can_open_url(user, VISITS_PATH)),
            "trainings": RolePermissionService.can_view_page(user, PAGE_PERMISSION)
            and bool(can_open_url(user, TRAININGS_PATH)),
            # school_links._may_open.
            "open_school": bool(can_open_url(user, "/schools/0")),
        }
    return out


def rules() -> dict:
    from apps.core.activity_types import (
        COMPLETED_WORK_STATUSES,
        TRAINING_TYPES,
        VISIT_TYPES,
    )
    from apps.frontend.templatetags.frontend_filters import _STATUS_INITIALISMS
    from apps.frontend.views.staff_views import _NOT_FINISHED_IN_FIELD

    return {
        "roles": roles(),
        "visit_types": [str(t) for t in VISIT_TYPES],
        "training_types": [str(t) for t in TRAINING_TYPES],
        "trainings_redirected": TRAININGS_REDIRECTED,
        "completed_statuses": list(COMPLETED_WORK_STATUSES),
        "not_finished_statuses": list(_NOT_FINISHED_IN_FIELD),
        "row_limit": ROW_LIMIT,
        "status_initialisms": _STATUS_INITIALISMS,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the staff logs' rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
