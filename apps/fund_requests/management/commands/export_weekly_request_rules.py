"""Write the Weekly Advance Request page's rules for the Go gateway.

Go builds the page's week (/fund-requests/weekly:
apps.frontend.views.budget_views.weekly_fund_requests_view,
_build_fund_requests_context and partials/fund_requests/*, as the existing
feed reads them) from what this command writes to
platform/backend/internal/weeklyrequest/rules.json: for each role, whether it
may open the page, the workspace strip it is shown, and the doors the page
draws (Add Non-School Activity, Export, Disburse, clearing an escalated
request, the monthly request and the report links); the staff value that
means everyone; the activity statuses that draw no money; and the six stages
of the weekly money chain, and the purpose interventions' names. A change to any of them must be exported again;
apps/fund_requests/test_weekly_request_rules_export.py fails until it is.

    python manage.py export_weekly_request_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/weeklyrequest/rules.json")

PAGE_PERMISSION = "fund_requests"
PATH = "/fund-requests/weekly"
EXPORT_DRAWER = "/fund-requests/weekly/export-drawer"


def roles() -> dict:
    from apps.core.permissions import (
        RolePermissionService,
        can_open_url,
        has_permission,
    )
    from apps.core.rbac import EdifyRole, Permission

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        page = RolePermissionService.can_view_page(user, PAGE_PERMISSION) and bool(
            can_open_url(user, PATH)
        )
        out[role.value] = {
            "page": page,
            "strip": strip(user, PATH, "partials/_section_nav.html") if page else None,
            "add_activity": has_permission(
                user, Permission.MANUAL_ACTIVITY_CREATE.value
            ),
            "export": bool(can_open_url(user, EXPORT_DRAWER)),
            "payment_act": has_permission(user, Permission.PAYMENT_ACT.value),
            # _require_weekly_approver's can_clear_escalated.
            "clears_escalated": has_permission(
                user, Permission.FUND_REQUEST_APPROVE_ESCALATED.value
            )
            or role.value == "CountryDirector",
            "monthly_request": RolePermissionService.can_view_page(
                user, "monthly_request"
            ),
            "reports": RolePermissionService.can_view_page(user, "reports"),
        }
    return out


def rules() -> dict:
    from apps.activities.models import Activity
    from apps.core.activity_types import NON_FUNDABLE_ACTIVITY_STATUSES
    from apps.frontend.views.budget_views import EVERYONE_STAFF, WEEKLY_STAGE_LABELS

    purposes = Activity._meta.get_field("purpose_intervention").choices

    return {
        "roles": roles(),
        "everyone_staff": EVERYONE_STAFF,
        "non_fundable_statuses": sorted(NON_FUNDABLE_ACTIVITY_STATUSES),
        "stage_labels": list(WEEKLY_STAGE_LABELS),
        # get_purpose_intervention_display(), a source activity's purpose line.
        "purpose_interventions": {str(value): str(label) for value, label in purposes},
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Weekly Advance Request page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
