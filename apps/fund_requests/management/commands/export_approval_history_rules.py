"""Write the Finance Approval History page's rules for the Go gateway.

Go builds the page (/accounts/approval-history/:
apps.frontend.views.finance_operating_views.approval_history_view and
pages/accounts/approval_history.html, as the existing feed reads them) from
what this command writes to platform/backend/internal/approvalhistory/
rules.json: for each role, whether it may open the page and the workspace
strip it is shown; the words status_label capitalises as initialisms; and the
table's page size and the query keys its pager does not carry. A change to any
of them must be exported again; apps/fund_requests/
test_approval_history_rules_export.py fails until it is.

    python manage.py export_approval_history_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/approvalhistory/rules.json")

PAGE_PERMISSION = "disbursements"
PATH = "/accounts/approval-history/"


def roles() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        page = RolePermissionService.can_view_page(user, PAGE_PERMISSION) and bool(
            can_open_url(user, PATH)
        )
        out[role.value] = {
            "page": page,
            "strip": strip(user, PATH, "partials/_section_nav.html") if page else None,
        }
    return out


def rules() -> dict:
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.frontend.templatetags.frontend_filters import _STATUS_INITIALISMS
    from apps.mobile_feed.views import NOT_PASSED

    return {
        "roles": roles(),
        "status_initialisms": dict(_STATUS_INITIALISMS),
        "page_size": TABLE_PAGE_SIZE,
        "query_keys_not_passed": sorted(NOT_PASSED),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Finance Approval History page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
