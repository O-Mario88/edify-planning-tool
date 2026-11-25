"""Write the Budget page's rules for Go.

Go builds Budget (/budget: apps.frontend.views.budget_views.budget_view,
apps.budget.services.budget_workspace and pages/budgets/monthly.html) from
what this command writes to platform/backend/internal/budgetpage/rules.json:
who may open the page, who sees its Export button, who has a section strip
above it, whose Budget is the country's, and the name each role is shown
under, and who opens the Consolidated Fund Allocation; the activity
statuses that draw no money; the names of the activity
types and the programme categories; the ledger's training and meeting
types and the lines whose quantity is a headcount; and the day's shared
rates (whose rate is the day's own); and for the country's Budget, its
home country, the states that lock the month's budget and those in which
its requirement is an approved limit, each state's name, the readers of
the workflow, the months, the advance statuses whose money has moved and
the statuses each Finance Health figure counts. A change to any of them must be
exported again; apps/budget/test_budget_rules_export.py fails until it is.

    python manage.py export_budget_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/budgetpage/rules.json")
PATH = "/budget"
FUND_ALLOCATION_PATH = "/finance/fund-allocation"


def _choices(model, field: str) -> dict:
    return {str(k): str(v) for k, v in model._meta.get_field(field).choices}


def rules() -> dict:
    from apps.accounts.hr_dashboard_service import ROLE_LABELS
    from apps.activities.models import Activity
    from apps.budget import services
    from apps.core.activity_types import NON_FUNDABLE_ACTIVITY_STATUSES
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.daily_visit_batches.pricing import KEY_LABELS
    from apps.frontend.views.budget_views import COUNTRY_BUDGET_ROLES

    roles = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        roles[role.value] = {
            "page": RolePermissionService.can_view_page(user, "monthly_budget")
            and bool(can_open_url(user, PATH)),
            "export": bool(can_open_url(user, "/budget/export")),
            # budget_export_view's own check (data.export).
            "data_export": bool(
                RolePermissionService.can_export(user, "/budget/export")
            ),
            "strip": strip(user, PATH, "partials/_section_nav.html") is not None,
            "country": role.value in COUNTRY_BUDGET_ROLES,
        }
    return {
        "roles": roles,
        "role_labels": dict(ROLE_LABELS),
        "non_fundable_statuses": list(NON_FUNDABLE_ACTIVITY_STATUSES),
        "activity_types": _choices(Activity, "activity_type"),
        "programme_activity_types": _choices(Activity, "programme_activity_type"),
        "training_types": sorted(services.LEDGER_TRAINING_TYPES),
        "meeting_types": sorted(services.LEDGER_MEETING_TYPES),
        "participant_line_types": sorted(services.LEDGER_PARTICIPANT_LINE_TYPES),
        "participant_setting_keys": sorted(services.LEDGER_PARTICIPANT_SETTING_KEYS),
        "day_rate_keys": sorted(KEY_LABELS),
        "country": _country_rules(),
        # The Budget workbook's other sheets (services._budget_export_book).
        "export_book": _export_book(),
        # The Activity cost plan as a sheet (services.cost_plan_sheet).
        "cost_plan_sheet": {
            "title": services.COST_PLAN_SHEET_TITLE,
            "caption": services.COST_PLAN_CAPTION,
            "money": services.UGX_MONEY,
            "empty": "No costed activities in this period.",
            "headers": {
                kind: services.cost_plan_column_headers(kind)
                for kind in ("standard", "meeting", "training", "admin")
            },
        },
        "country_ledger_roles": list(services.COUNTRY_LEDGER_ROLES),
        # Who opens the Consolidated Fund Allocation (fund_allocation_view).
        "fund_allocation_roles": [
            role.value
            for role in EdifyRole
            if RolePermissionService.can_view_page(
                _role_user(role.value), "consolidated_fund_allocation"
            )
            and can_open_url(_role_user(role.value), FUND_ALLOCATION_PATH)
        ],
    }


def _export_book() -> dict:
    from apps.activities.models import Activity
    from apps.budget import services
    from apps.core import export_kinds

    return {
        "activity_headers": list(services.ACTIVITY_SHEET_HEADERS),
        "line_headers": list(services.LINE_SHEET_HEADERS),
        "summary_headers": list(services.SUMMARY_SHEET_HEADERS),
        "money": services.MONEY,
        "status_labels": _choices(Activity, "status"),
        "kind_labels": dict(export_kinds.KIND_CHOICES),
        "plan_status_labels": dict(export_kinds.STATUS_LABELS),
        "school_lists": sorted(export_kinds.SCHOOL_LISTS),
    }


def _country_rules() -> dict:
    from apps.analytics import cd_analytics_service as cd
    from apps.fund_requests.models import MONEY_MOVED_ADVANCE_STATUSES
    from apps.monthly_work_plan import country_budget_service as cb

    return {
        "home_country_id": cb.HOME_COUNTRY_ID,
        "locked_statuses": sorted(cb.LOCKED_STATUSES),
        "approved_limit_statuses": sorted(cb.APPROVED_LIMIT_STATUSES),
        "approval_status_labels": dict(cb.APPROVAL_STATUS_LABELS),
        "read_roles": list(cb.READ_ROLES),
        "cd_roles": list(cb.CD_ROLES),
        "rvp_roles": list(cb.RVP_ROLES),
        "months": list(cb.MONTHS),
        "money_moved_statuses": [str(s) for s in MONEY_MOVED_ADVANCE_STATUSES],
        "finance": {
            "pending": list(cd.FINANCE_PENDING_STATUSES),
            "confirmed": list(cd.FINANCE_CONFIRMED_STATUSES),
            "disbursed": list(cd.FINANCE_DISBURSED_STATUSES),
            "accounted": list(cd.FINANCE_ACCOUNTED_STATUSES),
        },
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Budget page's rules for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
