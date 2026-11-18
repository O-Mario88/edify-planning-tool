"""Write the Visit Requests page's rules for the Go gateway.

Go builds /planning/visit-requests (apps.frontend.views.visit_request_views.
visit_requests_page over apps.planning.visit_requests, and
pages/planning/visit_requests.html, as the existing feed reads them) from what
this command writes to platform/backend/internal/visitrequests/rules.json: for
each role, whether it may open the page, whether it files requests rather than
plans (can_request_school_visit), and whether a school's or a district's name
opens its profile; and the status a request waits in. A change to any of them
must be exported again; apps/planning/test_visit_requests_rules_export.py fails
until it is.

    python manage.py export_visit_requests_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/visitrequests/rules.json")

PAGE_PERMISSION = "visit_requests"
PATH = "/planning/visit-requests"


def roles() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            "page": RolePermissionService.can_view_page(user, PAGE_PERMISSION)
            and bool(can_open_url(user, PATH)),
            "requester": RolePermissionService.can_request_school_visit(user),
            # school_links._may_open, for the school and the district names.
            "open_school": bool(can_open_url(user, "/schools/0")),
            "open_district": bool(can_open_url(user, "/districts/0")),
        }
    return out


def rules() -> dict:
    from apps.planning import visit_requests

    return {"roles": roles(), "awaiting": visit_requests.AWAITING}


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Visit Requests page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
