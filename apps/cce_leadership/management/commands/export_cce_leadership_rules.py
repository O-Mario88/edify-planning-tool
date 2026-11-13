"""Write the CCE leadership registers' rules for the Go gateway.

Go builds the CCE leadership registers (apps.frontend.views.
cce_leadership_views, drawn by pages/cce_leadership/workspace.html) from what
this command writes to platform/backend/internal/ccelead/rules.json: for each
register Go answers, who may open it, the workspace strip each role is shown
and which of its drawer buttons each role may open; the label each figure is
drawn with; a monthly report's status labels and tones; the month reporting
started; how long the line under a figure may stay; the register's page
size; and the query keys the feed never passes. A change to any of them must
be exported again; apps/cce_leadership/test_cce_leadership_rules_export.py
fails until it is.

    python manage.py export_cce_leadership_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/ccelead/rules.json")

METRIC_SOURCE = "apps.frontend.views.cce_leadership_views:_metric"

PAGES = {
    "/cce-leadership/reports": {
        "permission": "cce_reports",
        "drawers": ["/cce-leadership/reports/new"],
        "metrics": [
            "Report Drafts",
            "Reports Awaiting Review",
            "Reports Returned",
            "Reports Acknowledged",
        ],
    },
}


def pages() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for path, page in PAGES.items():
        roles = {}
        for role in EdifyRole:
            user = _role_user(role.value)
            roles[role.value] = {
                "page": RolePermissionService.can_view_page(user, page["permission"])
                and bool(can_open_url(user, path)),
                "strip": strip(user, path, "partials/_section_nav.html"),
                "drawers": [d for d in page["drawers"] if can_open_url(user, d)],
            }
        out[path] = {"roles": roles}
    return out


def rules() -> dict:
    from apps.cce_leadership import services
    from apps.cce_leadership.models import ReportStatus
    from apps.core.metrics.payload import HELPER_FIGURE_CHARS
    from apps.core.metrics.reconciled_registry import (
        key_for_source_label,
        source_label_for_key,
    )
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.frontend.views.cce_leadership_views import STATUS_TONES
    from apps.mobile_feed.views import NOT_PASSED

    return {
        "pages": pages(),
        "metric_labels": {
            label: source_label_for_key(key_for_source_label(METRIC_SOURCE, label))
            for page in PAGES.values()
            for label in page["metrics"]
        },
        "report_statuses": dict(ReportStatus.choices),
        "report_tones": {str(k): v for k, v in STATUS_TONES.items()},
        "reporting_starts": services.REPORTING_STARTS.isoformat(),
        "helper_figure_chars": HELPER_FIGURE_CHARS,
        "page_size": TABLE_PAGE_SIZE,
        "query_keys_not_passed": sorted(NOT_PASSED),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the CCE leadership registers' rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
