"""Write My Performance's rules for Go.

Go builds Priorities (/my-performance: apps.frontend.views.hr_views
.my_performance_view and pages/hr/my_performance.html) from what this command
writes to platform/backend/internal/myperformance/rules.json: who may open the
page and the section strip each role is shown above it; which roles see the
header's distribute, team-distribute and configure buttons and which are
managers (whose conversation button closes with the window); the words of the
conversation windows and the review stages the page names itself; the tabs;
and the commitment kinds. A change to any of them must be exported again;
apps/hr/test_my_performance_rules_export.py fails until it is.

    python manage.py export_my_performance_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/myperformance/rules.json")
PATH = "/my-performance"

#: my_performance_view's own lists, as it writes them.
MANAGER_ROLES = [
    "Program Lead",
    "PL",
    "CountryDirector",
    "CD",
    "RegionalVicePresident",
    "RVP",
    "HumanResources",
    "HR",
    "Admin",
]
DISTRIBUTE_ROLES = ["ImpactAssessment", "Admin"]
DISTRIBUTE_TEAM_ROLES = ["Program Lead", "Admin"]
CONFIGURE_ROLES = [
    "ImpactAssessment",
    "Admin",
    "CountryDirector",
    "RegionalVicePresident",
]
WINDOW_LABELS = {
    "priority_setting": "Priority Setting",
    "q1": "Q1 Check-in",
    "q2_midyear": "Q2 Mid-Year",
    "q3": "Q3 Check-in",
    "q4_yearend": "Q4 Year-End",
}
STAGE_LABELS = {
    "not_started": "Draft — not started",
    "draft": "Draft",
    "employee_input": "Employee input",
    "manager_review": "Manager review",
    "approved": "Approved",
    "returned": "Returned",
    "signed_off": "Signed off",
}
SIGNED_STAGES = ["signed_off", "archived"]
TABS = [
    ["distributed", "Distributed Priorities"],
    ["values", "Core Values"],
    ["spiritual", "Spiritual Formation"],
    ["development", "Professional Development"],
]


def rules() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.hr.models import ValueCommitment

    roles = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        roles[role.value] = {
            "page": RolePermissionService.can_view_page(user, "my_performance")
            and bool(can_open_url(user, PATH)),
            "strip": strip(user, PATH, "partials/_section_nav.html"),
        }
    return {
        "roles": roles,
        "manager_roles": MANAGER_ROLES,
        "distribute_roles": DISTRIBUTE_ROLES,
        "distribute_team_roles": DISTRIBUTE_TEAM_ROLES,
        "configure_roles": CONFIGURE_ROLES,
        "window_labels": WINDOW_LABELS,
        "stage_labels": STAGE_LABELS,
        "signed_stages": SIGNED_STAGES,
        "tabs": TABS,
        "value_kinds": dict(ValueCommitment._meta.get_field("kind").choices),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write My Performance's rules for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
