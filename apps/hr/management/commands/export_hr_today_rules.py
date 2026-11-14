"""Write HR Today's rules for the Go gateway.

Go builds HR Today (/hr-today, apps.frontend.views.hr_today_views
.hr_today_page over apps.hr.hr_exceptions, drawn by pages/hr/hr_today.html)
from what this command writes to platform/backend/internal/hrtoday/rules.json:
who may open the page; which of the registers its rows point at each role may
open; the four queues' labels and the line under each figure; the roles that
see the policy and account queues and every conversation; the review chain
and the employment states that hold authority; the policy statuses waiting on
HR; the windows the queues use; and how many rows each queue shows and when
alike rows fold. A change to any of them must be exported again;
apps/hr/test_hr_today_rules_export.py fails until it is.

    python manage.py export_hr_today_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/hrtoday/rules.json")

PAGE_PATH = "/hr-today"

#: One link of each kind a row can carry, keyed by the kind's prefix.
LINKS = {
    "/leave/approvals": "/leave/approvals?id=x",
    "/my-professional-development/request": "/my-professional-development/request?id=x",
    "/documents/": "/documents/x/manage",
    "/onboarding": "/onboarding",
    "/performance-conversation": "/performance-conversation?staff=x",
    "/org-structure": "/org-structure",
    "/admin-panel/users": "/admin-panel/users",
    "/leave/coverage": "/leave/coverage",
    "/hr/performance-cycle": "/hr/performance-cycle",
    "/offboarding": "/offboarding",
    "/compliance-register": "/compliance-register",
}

#: The roles hr_exceptions lets see the policy and account queues, and every
#: conversation (its `role in ("HumanResources", "Human Resources", "Admin")`).
GOVERNING_ROLES = ["HumanResources", "Human Resources", "Admin"]


def rules() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.frontend.views import hr_today_views as view
    from apps.hr import hr_exceptions as hx
    from apps.hr import review_authority

    roles = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        roles[role.value] = {
            "page": RolePermissionService.can_view_page(user, "hr_today")
            and bool(can_open_url(user, PAGE_PATH)),
            "opens": sorted(
                prefix for prefix, url in LINKS.items() if can_open_url(user, url)
            ),
        }
    return {
        "roles": roles,
        "groups": [
            {
                "key": key,
                "label": hx.GROUP_LABELS[key],
                "helper": view._CARD_HELPERS[key],
            }
            for key in (
                hx.WAITING_ON_HR,
                hx.MANAGER_OVERDUE,
                hx.PEOPLE_RISK,
                hx.DEADLINES,
            )
        ],
        "governing_roles": GOVERNING_ROLES,
        "reviewer_role_for": {
            k: list(v) for k, v in review_authority.REVIEWER_ROLE_FOR.items()
        },
        "live_states": list(review_authority.LIVE_STATES),
        "policy_awaiting_statuses": list(hx.POLICY_AWAITING_PUBLICATION_STATUSES),
        "leave_decision_days": hx.LEAVE_DECISION_DAYS,
        "review_overdue_days": hx.REVIEW_OVERDUE_DAYS,
        "deadline_horizon_days": hx.DEADLINE_HORIZON_DAYS,
        "visible_per_queue": view.VISIBLE_PER_QUEUE,
        "fold_from": view.FOLD_FROM,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write HR Today's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
