"""Write the Accounts desks' rules for the Go gateway.

Go builds the Accountant's desk pages (/accounts/accountability, /advances,
/audit-log, /blocked, /budget-amendments, /cleared, /returned,
/variance-review and /weekly-requests: apps.frontend.views.
finance_operating_views and templates/pages/accounts/*.html) as the existing
feed reads them, from what this command writes to
platform/backend/internal/financedesks/rules.json: for each role, which desks
it may open and whether a school's name opens its profile. A change to any of
them must be exported again; apps/fund_requests/test_finance_desks_rules_export.py
fails until it is.

    python manage.py export_finance_desks_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/financedesks/rules.json")

#: The page permission every desk view requires (require_page_permission).
DESK_PERMISSION = "disbursements"
DESKS = (
    "/accounts/accountability",
    "/accounts/advances",
    "/accounts/audit-log",
    "/accounts/blocked",
    "/accounts/budget-amendments",
    "/accounts/cleared",
    "/accounts/returned",
    "/accounts/variance-review",
    "/accounts/weekly-requests",
)


def roles() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        permitted = RolePermissionService.can_view_page(user, DESK_PERMISSION)
        out[role.value] = {
            "desks": {
                path: bool(permitted and can_open_url(user, path)) for path in DESKS
            },
            # school_links._may_open.
            "open_school": bool(can_open_url(user, "/schools/0")),
        }
    return out


def rules() -> dict:
    from apps.activities.models import Activity
    from apps.activities.salesforce import NO_SALESFORCE_RECORD_TYPES
    from apps.core.activity_types import NOT_IN_PLAN_ACTIVITY_STATUSES
    from apps.fund_requests.finance_services import (
        PARTNER_PAID_STATUSES,
        FinanceBlockedReasonService,
    )

    return {
        "roles": roles(),
        # FinanceBlockedReasonService.blocked_activities' rules.
        "not_in_plan_statuses": list(NOT_IN_PLAN_ACTIVITY_STATUSES),
        "ia_verified_statuses": list(FinanceBlockedReasonService.IA_VERIFIED_STATUSES),
        "no_salesforce_record_types": sorted(NO_SALESFORCE_RECORD_TYPES),
        # ready_for_advance_view leaves out partner work already paid.
        "partner_paid_statuses": list(PARTNER_PAID_STATUSES),
        "activity_types": {
            str(value): str(label)
            for value, label in Activity._meta.get_field("activity_type").choices
        },
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Accounts desks' rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
