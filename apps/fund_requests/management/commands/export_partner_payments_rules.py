"""Write the Partner Payment Queue's rules for the Go gateway.

Go builds the page (/accounts/partner-payments/:
apps.frontend.views.finance_operating_views.partner_payments_view and
pages/accounts/partner_payments.html, as the existing feed reads them) from
what this command writes to platform/backend/internal/partnerpayments/
rules.json: for each role, whether it may open the page, the workspace strip
it is shown and whether a school's or a partner's name opens its profile;
the activity and invoice types' names; the statuses that keep work out of
every money channel; the payment statuses that make verified partner work
payable; and the table's page size. A change to any of them must be exported
again; apps/fund_requests/test_partner_payments_rules_export.py fails until
it is.

    python manage.py export_partner_payments_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/partnerpayments/rules.json")

PAGE_PERMISSION = "disbursements"
PATH = "/accounts/partner-payments/"


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
            "school_links": bool(can_open_url(user, "/schools/0")),
            "partner_links": bool(can_open_url(user, "/partners/0")),
        }
    return out


def rules() -> dict:
    from apps.activities.models import Activity
    from apps.core.activity_types import NON_FUNDABLE_ACTIVITY_STATUSES
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.fund_requests.finance_models import PartnerInvoice
    from apps.fund_requests import partner_invoices
    from apps.fund_requests.finance_services import PARTNER_PAYABLE_STATUSES

    return {
        "roles": roles(),
        "activity_types": {
            str(k): str(v) for k, v in Activity._meta.get_field("activity_type").choices
        },
        "invoice_types": {str(k): str(v) for k, v in PartnerInvoice.TYPE_CHOICES},
        "non_fundable_statuses": list(NON_FUNDABLE_ACTIVITY_STATUSES),
        "partner_payable_statuses": list(PARTNER_PAYABLE_STATUSES),
        "page_size": TABLE_PAGE_SIZE,
        # The partner's own invoice document (partner_invoices.invoice_file):
        # where it is kept, who may download it whatever its Lead, and the
        # Lead's own role.
        "document": {
            "namespace": partner_invoices.INVOICE_NAMESPACE,
            "finance_roles": list(partner_invoices._FINANCE_ROLES),
            "lead_role": "Program Lead",
        },
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Partner Payment Queue's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
