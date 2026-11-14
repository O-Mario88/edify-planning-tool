"""Write the Ownership Transfers page's rules for the Go gateway.

Go builds Ownership Transfers (/ownership-transfers/,
apps.frontend.views.ownership_views.ownership_transfers_view and
pages/schools/ownership_transfers.html) from what this command writes to
platform/backend/internal/ownership/rules.json: who may open the page and who
may move a district portfolio; who may open a district's or a school's
profile, so a name is a link; the open-activity decisions' labels; how many
batches and transfers the page lists; and the tables' page size. A change to
any of them must be exported again;
apps/schools/test_ownership_transfers_rules_export.py fails until it is.

    python manage.py export_ownership_transfers_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/ownership/rules.json")

PAGE_PATH = "/ownership-transfers/"
PAGE_PERMISSION = "ownership_transfers"

#: ownership_transfers_view: batches[:25], transfers[:50], reconciliations[:50].
LIMITS = {"batches": 25, "transfers": 50, "reconciliations": 50}


def rules() -> dict:
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.schools import ownership_transfer as transfers
    from apps.schools.ownership_models import (
        OpenActivityDecision,
        TargetReconciliation,
    )

    def roles(test) -> list[str]:
        return sorted(r.value for r in EdifyRole if test(_role_user(r.value)))

    return {
        "page_roles": roles(
            lambda u: RolePermissionService.can_view_page(u, PAGE_PERMISSION)
            and bool(can_open_url(u, PAGE_PATH))
        ),
        "district_transfer_roles": roles(transfers.may_transfer_district),
        "district_profile_roles": roles(
            lambda u: bool(can_open_url(u, "/districts/0"))
        ),
        "open_activity_decisions": {k: str(v) for k, v in OpenActivityDecision.choices},
        "required_reconciliation": TargetReconciliation.REQUIRED.value,
        "limits": LIMITS,
        "page_size": TABLE_PAGE_SIZE,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Ownership Transfers page's rules for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
