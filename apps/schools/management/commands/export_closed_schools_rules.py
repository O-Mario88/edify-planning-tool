"""Write the Closed Schools page's rules for the Go gateway.

Go builds the archive (/schools/closed, apps.frontend.views.school_views.
closed_schools_view and pages/schools/closed.html) from the vocabularies this
command writes to platform/backend/internal/closedschools/rules.json: who may
open the page, who reads the year's closure impact and who is given a link to
a school's profile; a closure's type and reason words; the statuses that
count as operating; the archive's row cap and the shared table page size; and
the query keys the app's feed never passes to a page. A change to any of them
must be exported again; apps/schools/test_closed_schools_rules_export.py fails
until it is, so the two can never drift.

The doors are not restated: each role's answer is computed here by the gates
the page itself asks.

    python manage.py export_closed_schools_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/closedschools/rules.json")

PAGE_PATH = "/schools/closed"


def doors() -> dict:
    """What each role is given on the archive, by the page's own gates."""
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            # require_page_permission("closed_schools") and the feed's
            # can_open_url.
            "page": RolePermissionService.can_view_page(user, "closed_schools")
            and bool(can_open_url(user, PAGE_PATH)),
            # _closure_impact: the year's four closure figures.
            "impact": RolePermissionService.can_view_page(user, "closure_impact"),
            # {% school_link %}: a name is a link for a reader of profiles.
            "profiles": bool(can_open_url(user, "/schools/0")),
        }
    return out


def rules() -> dict:
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.frontend.views.school_views import CLOSED_ARCHIVE_MAX_ROWS
    from apps.mobile_feed.views import NOT_PASSED
    from apps.schools.lifecycle_models import (
        OPERATING_STATUSES,
        ClosureReason,
        ClosureType,
    )

    return {
        "doors": doors(),
        "closure_types": [[str(v), str(label)] for v, label in ClosureType.choices],
        "closure_reasons": [[str(v), str(label)] for v, label in ClosureReason.choices],
        "operating_statuses": [str(s) for s in OPERATING_STATUSES],
        "max_rows": CLOSED_ARCHIVE_MAX_ROWS,
        "page_size": TABLE_PAGE_SIZE,
        "query_keys_not_passed": sorted(NOT_PASSED),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write the Closed Schools page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
