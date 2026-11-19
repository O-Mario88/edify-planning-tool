"""Write the finance overviews' rules for the Go gateway.

Go builds the Budget Overview (/budgets/overview: apps.frontend.views.
finance_views.budget_overview_view over apps.budget.services.fy_budget and
monthly_budgets, pages/budget/index.html) and the Submitted Budgets history
(/country-budget/history: country_budget_history_view over
country_budget_service.list_submitted_budgets) as the existing feed reads
them, from what this command writes to
platform/backend/internal/financedesks/overviews.json: for each role, which
page it may open; the advance and activity states each budget figure counts;
the states a submitted budget is locked in, and each state's words. A change
to any of them must be exported again;
apps/budget/test_finance_overviews_rules_export.py fails until it is.

    python manage.py export_finance_overviews_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/financedesks/overviews.json")

#: Each page, its permission and its path.
PAGES = {
    "overview": ("consolidated_fund_allocation", "/budgets/overview"),
    "history": ("country_budget", "/country-budget/history"),
}


def roles() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.monthly_work_plan.country_budget_service import READ_ROLES

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        doors = {
            name: bool(
                RolePermissionService.can_view_page(user, permission)
                and can_open_url(user, path)
            )
            for name, (permission, path) in PAGES.items()
        }
        # list_submitted_budgets refuses a reader outside READ_ROLES.
        doors["history_reads"] = role.value in READ_ROLES
        out[role.value] = doors
    return out


def rules() -> dict:
    from apps.budget import services as budget
    from apps.core.activity_types import NON_FUNDABLE_ACTIVITY_STATUSES
    from apps.frontend.views.finance_views import AWAITING_APPROVAL_WEEKLY_STATUSES
    from apps.monthly_work_plan.country_budget_service import LOCKED_STATUSES
    from apps.monthly_work_plan.models import MonthlyWorkPlanBudgetStatus

    return {
        "roles": roles(),
        "non_fundable_statuses": list(NON_FUNDABLE_ACTIVITY_STATUSES),
        "requested_advance_statuses": list(budget._REQUESTED_ADVANCE_STATUSES),
        "approved_advance_statuses": list(budget._APPROVED_ADVANCE_STATUSES),
        "disbursed_advance_statuses": list(budget._DISBURSED_ADVANCE_STATUSES),
        "accounted_advance_statuses": list(budget._ACCOUNTED_ADVANCE_STATUSES),
        # budget_overview_view's notice of weekly requests awaiting approval.
        "awaiting_weekly_statuses": list(AWAITING_APPROVAL_WEEKLY_STATUSES),
        "locked_budget_statuses": sorted(LOCKED_STATUSES),
        "budget_status_labels": {
            str(value): str(label)
            for value, label in MonthlyWorkPlanBudgetStatus.choices
        },
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the finance overviews' rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
