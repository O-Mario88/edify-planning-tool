"""Write the Programme Schools page's rules for the Go gateway.

Go builds the page (/programme-schools, apps.frontend.views.school_views.
programme_schools_view, apps.schools.programme_schools and
pages/schools/programme_schools.html) from the vocabularies this command
writes to platform/backend/internal/programmeschools/rules.json: who may open
the page and who is offered Schedule on a row; the three programme school
types with their labels, in the page's order; the statuses that count as
operating; the list's row limit and the shared table page size; and the query
keys the app's feed never passes to a page. A change to any of them must be
exported again; apps/schools/test_programme_schools_rules_export.py fails
until it is, so the two can never drift.

The doors are not restated: each role's answer is computed here by the gates
the page itself asks. The visit rule a row reads is the school profile's
export (export_school_profile_rules, "gate").

    python manage.py export_programme_schools_rules
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/programmeschools/rules.json")

PAGE_PATH = "/programme-schools"


def doors() -> dict:
    """What each role is given on the page, by the page's own gates."""
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            # require_page_permission("programme_schools") and the feed's
            # can_open_url.
            "page": RolePermissionService.can_view_page(user, "programme_schools")
            and bool(can_open_url(user, PAGE_PATH)),
            # can_schedule: a planner's row offers Schedule, anyone else's View.
            "schedule": bool(RolePermissionService.can_schedule_activity(user)),
        }
    return out


def rules() -> dict:
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.mobile_feed.views import NOT_PASSED
    from apps.schools import programme_schools as programme
    from apps.schools.lifecycle_models import OPERATING_STATUSES

    limit = inspect.signature(programme.programme_schools).parameters["limit"].default
    return {
        "doors": doors(),
        "school_types": [
            [value, str(label)] for value, label in programme.type_options()
        ],
        "operating_statuses": [str(s) for s in OPERATING_STATUSES],
        "max_rows": limit,
        "page_size": TABLE_PAGE_SIZE,
        "query_keys_not_passed": sorted(NOT_PASSED),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write the Programme Schools page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
