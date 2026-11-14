"""Write the Leave Approvals page's rules for the Go gateway.

Go builds Leave Approvals (/leave/approvals, apps.frontend.views.leave_views
.leave_approvals_view over apps.hr.leave_services, drawn by
pages/leave/leave_approvals.html and partials/leave/impact_panel.html) from
what this command writes to platform/backend/internal/leaveapprovals/rules.json:
who may open the page and the workspace strip each role is shown above it;
which roles' availability card reads everyone;
the six figures' labels; the fund-request statuses a leave holds up; and the
page size. A change to any of them must be exported again;
apps/hr/test_leave_approvals_rules_export.py fails until it is.

    python manage.py export_leave_approvals_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/leaveapprovals/rules.json")

PAGE_PATH = "/leave/approvals"

#: The registry keys of the page's six figures, in the order it draws them.
METRIC_KEYS = [
    "frontend_views_leave_views_pending_approvals",
    "frontend_views_leave_views_approved_7_days",
    "frontend_views_leave_views_coverage_ready",
    "frontend_views_leave_views_critical_conflicts",
    "frontend_views_leave_views_away_this_week",
    "frontend_views_leave_views_balance_alerts",
]


#: The roles whose availability card reads everyone, not their own team
#: (the view's `role in ["CD", "HR", "ADMIN"]`).
HEATMAP_EVERYONE_SLUGS = ("CD", "HR", "ADMIN")


def rules() -> dict:
    from apps.core.metrics.payload import render_precomputed_metric_item
    from apps.core.navigation import get_user_role_slug
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.fund_requests.models import FundRequestStatus

    roles, everyone = {}, []
    for role in EdifyRole:
        user = _role_user(role.value)
        if get_user_role_slug(user) in HEATMAP_EVERYONE_SLUGS:
            everyone.append(role.value)
        roles[role.value] = {
            "page": RolePermissionService.can_view_page(user, "leave_approvals")
            and bool(can_open_url(user, PAGE_PATH)),
            "strip": strip(user, PAGE_PATH, "partials/_section_nav.html"),
        }
    return {
        "roles": roles,
        "heatmap_everyone_roles": sorted(everyone),
        "metric_labels": [
            render_precomputed_metric_item(key, "0")["label"] for key in METRIC_KEYS
        ],
        "fund_request_statuses": [
            FundRequestStatus.SUBMITTED.value,
            FundRequestStatus.SUBMITTED_TO_PL.value,
        ],
        "page_size": TABLE_PAGE_SIZE,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Leave Approvals page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
