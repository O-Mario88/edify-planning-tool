"""Write the Programme Output Reports page's rules for the Go gateway.

Go builds Programme Output Reports (/reports, apps.frontend.views
.extended_views.reports_view and partials/analytics/panels/reports.html in
the Analytics section shell) from what this command writes to
platform/backend/internal/reports/rules.json: who may open the page and the
workspace strip each is shown; each
reporting area's label, activity types and target type; the statuses that
count as achieved; and the four quarters. A change to any of them must be
exported again; apps/schools/test_reports_rules_export.py fails until it is.

    python manage.py export_reports_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/reports/rules.json")

PAGE_PATH = "/reports"
PAGE_PERMISSION = "reports"


def rules() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.frontend.views import extended_views as v

    def opens(role) -> bool:
        user = _role_user(role.value)
        return RolePermissionService.can_view_page(user, PAGE_PERMISSION) and bool(
            can_open_url(user, PAGE_PATH)
        )

    return {
        "page_roles": sorted(r.value for r in EdifyRole if opens(r)),
        # The Analytics tab rail each role is shown above the report.
        "strips": {
            r.value: strip(
                _role_user(r.value), PAGE_PATH, "partials/analytics/tab_rail.html"
            )
            for r in EdifyRole
            if opens(r)
        },
        "areas": [
            {
                "label": a["label"],
                "types": list(a["types"]),
                "target_type": str(a["target_type"]) if a.get("target_type") else "",
            }
            for a in v._REPORTS_AREA_DEFS
        ],
        "achieved_statuses": list(v._REPORTS_ACHIEVED_STATUSES),
        "quarters": [
            {"key": key, "code": code, "label": label, "order": order}
            for key, code, label, order in v._REPORTS_QUARTER_PERIODS
        ],
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Programme Output Reports page's rules for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
