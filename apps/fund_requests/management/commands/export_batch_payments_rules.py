"""Write the Batch Payments Center's rules for the Go gateway.

Go builds the page (/accounts/batch-payments/:
apps.frontend.views.finance_operating_views.batch_payments_view and
pages/accounts/batch_payments.html, as the existing feed reads them) from
what this command writes to platform/backend/internal/batchpayments/
rules.json: for each role, whether it may open the page and the workspace
strip it is shown; the activity types' names; the advance status that makes
staff work payable; and the payment statuses that make partner work payable
and that mean money already left. A change to any of them must be exported
again; apps/fund_requests/test_batch_payments_rules_export.py fails until it
is.

    python manage.py export_batch_payments_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/batchpayments/rules.json")

PAGE_PERMISSION = "disbursements"
PATH = "/accounts/batch-payments/"


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
    from apps.activities.models import Activity
    from apps.fund_requests.finance_services import (
        PARTNER_PAID_STATUSES,
        PARTNER_PAYABLE_STATUSES,
    )
    from apps.fund_requests.models import AdvanceRequestStatus

    return {
        "roles": roles(),
        "activity_types": {
            str(k): str(v) for k, v in Activity._meta.get_field("activity_type").choices
        },
        "advance_payable_status": str(AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE),
        "partner_payable_statuses": list(PARTNER_PAYABLE_STATUSES),
        "partner_paid_statuses": list(PARTNER_PAID_STATUSES),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Batch Payments Center's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
