"""Write the Fund Approvals page's rules for the Go gateway.

Go builds Fund Approvals (/fund-approvals: extended_views
.pl_fund_approvals_view, apps.fund_requests.pl_approval_service
.get_pl_fund_approvals and partials/finance/fund_workspace.html) from what
this command writes to platform/backend/internal/fundapprovals/rules.json:
which roles open the page and its export; the roles whose requests reach
the Country Director; the weekly request's status names and the hint each
status shows; the activity sets the plan's chips, categories and checks
read; the activity type names; and the figures' labels. A change to any of
them must be exported again; apps/fund_requests/
test_fund_approvals_rules_export.py fails until it is.

    python manage.py export_fund_approvals_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/fundapprovals/rules.json")

PAGE_PATH = "/fund-approvals"

#: The strip's figures, in the order get_pl_fund_approvals builds them.
METRIC_KEYS = (
    "fund_requests_pl_approval_service_requested_this_week",
    "fund_requests_pl_approval_service_awaiting_your_approval",
    "fund_requests_pl_approval_service_approved_this_week",
    "fund_requests_pl_approval_service_returned_for_review",
)


def doors() -> dict:
    """What each role is given, by the page's own gates."""
    from apps.core.exceptions import Forbidden
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.fund_requests.pl_approval_service import _require_pl

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        try:
            _require_pl(user)
            desk = True
        except Forbidden:
            desk = False
        out[role.value] = {
            # require_page_permission("fund_approvals"), the feed's
            # can_open_url and the service's own Lead/CD/Admin check.
            "page": RolePermissionService.can_view_page(user, "fund_approvals")
            and bool(can_open_url(user, PAGE_PATH))
            and desk,
            # require_export_permission: the header's Export.
            "export": RolePermissionService.can_export(user, PAGE_PATH),
        }
    return out


def _keyed(mapping: dict) -> dict:
    """A status-keyed map with "" for no request (None)."""
    return {("" if key is None else key): value for key, value in mapping.items()}


def rules() -> dict:
    from apps.activities.models import ActivityType
    from apps.core.activity_types import TRAINING_TYPES, VISIT_TYPES
    from apps.core.metrics.reconciled_registry import source_label_for_key
    from apps.fund_requests import fund_workspace
    from apps.fund_requests import pl_approval_service as pl

    return {
        "doors": doors(),
        "cd_approval_roles": list(pl.CD_APPROVAL_ROLES),
        "status_labels": {
            k: list(v) for k, v in _keyed(pl.WEEKLY_STATUS_LABELS).items()
        },
        "hints": _keyed(pl.WAITING_HINTS),
        "visit_types": sorted(VISIT_TYPES),
        "training_types": sorted(TRAINING_TYPES),
        "ssa_visit_types": list(pl.SSA_VISIT_TYPES),
        "cluster_meeting_types": list(pl.CLUSTER_MEETING),
        "cluster_training_types": list(pl.CLUSTER_TRAINING),
        "months": list(pl.MONTHS),
        "mix_colours": dict(fund_workspace.MIX_COLOURS),
        "activity_types": {str(v): str(label) for v, label in ActivityType.choices},
        "metric_labels": [source_label_for_key(key) for key in METRIC_KEYS],
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Fund Approvals page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
