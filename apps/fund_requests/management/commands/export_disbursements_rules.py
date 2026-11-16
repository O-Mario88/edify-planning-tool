"""Write the Fund Disbursement Dashboard's rules for the Go gateway.

Go builds Disbursements (/disbursements: finance_views.disbursements_view,
apps.fund_requests.disbursement_dashboard_service.get_disbursement_dashboard
and partials/finance/fund_workspace.html) from what this command writes to
platform/backend/internal/disbursements/rules.json: which roles open the
page and its export; the queue's status names, tones and order; the monthly
and weekly status sets; the advance ledger's buckets; the partner payable
states; the statuses that draw no money; the fund categories and the
weekly line labels; the activity type names; and the figures' labels. A
change to any of them must be exported again;
apps/fund_requests/test_disbursements_rules_export.py fails until it is.

    python manage.py export_disbursements_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/disbursements/rules.json")

PAGE_PATH = "/disbursements"

#: The figures the page builds, in the order get_disbursement_dashboard
#: builds them (the strip shows the first four).
METRIC_KEYS = (
    "fund_requests_disbursement_dashboard_service_total_funds_this_month",
    "fund_requests_disbursement_dashboard_service_pending_disbursement",
    "fund_requests_disbursement_dashboard_service_disbursed_today",
    "fund_requests_disbursement_dashboard_service_awaiting_approval_completion",
)


def doors() -> dict:
    """What each role is given, by the page's own gates."""
    from apps.core.exceptions import Forbidden
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.fund_requests.disbursement_dashboard_service import (
        _require_accountant,
    )

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        try:
            _require_accountant(user)
            desk = True
        except Forbidden:
            desk = False
        out[role.value] = {
            # require_page_permission("disbursements"), the feed's
            # can_open_url and the service's own Accountant/Admin check.
            "page": RolePermissionService.can_view_page(user, "disbursements")
            and bool(can_open_url(user, PAGE_PATH))
            and desk,
            # require_export_permission: the header's Export.
            "export": RolePermissionService.can_export(user, PAGE_PATH),
        }
    return out


def rules() -> dict:
    from apps.activities.models import ActivityType
    from apps.core.activity_types import (
        NON_FUNDABLE_ACTIVITY_STATUSES,
        TRAINING_TYPES,
        VISIT_TYPES,
    )
    from apps.core.metrics.reconciled_registry import source_label_for_key
    from apps.fund_requests import disbursement_dashboard_service as disb
    from apps.fund_requests import fund_workspace, pl_approval_service as pl
    from apps.fund_requests.finance_services import PARTNER_PAYABLE_STATUSES
    from apps.fund_requests.models import MONEY_MOVED_ADVANCE_STATUSES

    return {
        "doors": doors(),
        "status_options": list(disb.STATUS_OPTIONS),
        "status_tones": dict(disb.STATUS_TONES),
        "status_sort": dict(disb._STATUS_SORT),
        "monthly_pending_approval": sorted(disb.M_PENDING_APPROVAL),
        "monthly_pending_disbursement": sorted(disb.M_PENDING_DISB),
        "monthly_returned": sorted(disb.M_RETURNED),
        "advance_pre_approval": list(disb.A_PRE_APPROVAL),
        "advance_approved_undisbursed": list(disb.A_APPROVED_UNDISBURSED),
        "money_moved_advance_statuses": [str(s) for s in MONEY_MOVED_ADVANCE_STATUSES],
        "partner_payable_statuses": list(PARTNER_PAYABLE_STATUSES),
        "non_fundable_statuses": list(NON_FUNDABLE_ACTIVITY_STATUSES),
        "category_order": list(pl.CATEGORY_ORDER),
        "visit_types": sorted(VISIT_TYPES),
        "ssa_visit_types": list(pl.SSA_VISIT_TYPES),
        "cluster_meeting_types": list(pl.CLUSTER_MEETING),
        "cluster_training_types": list(pl.CLUSTER_TRAINING),
        "training_types": sorted(TRAINING_TYPES),
        "line_type_labels": dict(disb.LINE_TYPE_LABELS),
        "mix_colours": dict(fund_workspace.MIX_COLOURS),
        "months": list(pl.MONTHS),
        "activity_types": {str(v): str(label) for v, label in ActivityType.choices},
        "metric_labels": [source_label_for_key(key) for key in METRIC_KEYS],
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Fund Disbursement Dashboard's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
