"""Write the Completion Reviews page's rules for the Go gateway.

Go builds Completion Reviews (/pl/review-queue,
apps.frontend.views.my_plan_views.pl_queue_view,
apps.pl_review.services.review_register and
partials/my_plan/completion_reviews_register.html) from what this command
writes to platform/backend/internal/plreview/rules.json: who may open the
page and the role that is sent to its dashboard tab instead; the roles whose
staff-delivered work a lead verifies; the activity labels and the
intervention abbreviations; and the register's page size. A change to any of
them must be exported again;
apps/pl_review/test_completion_reviews_rules_export.py fails until it is.

    python manage.py export_completion_reviews_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/plreview/rules.json")

PAGE_PATH = "/pl/review-queue"
PAGE_PERMISSION = "pl_review_queue"


def rules() -> dict:
    from apps.activities.models import ActivityType
    from apps.core.interventions import INTERVENTION_ABBREVIATIONS
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.frontend.views.dashboard_embed import PROGRAM_LEAD
    from apps.pl_review.services import LEAD_VERIFIED_ROLES

    return {
        "page_roles": sorted(
            role.value
            for role in EdifyRole
            if RolePermissionService.can_view_page(
                _role_user(role.value), PAGE_PERMISSION
            )
            and can_open_url(_role_user(role.value), PAGE_PATH)
        ),
        # dashboard_embed.reads_on_dashboard: this role reads the register on
        # its dashboard's Execution & Completion tab.
        "dashboard_role": PROGRAM_LEAD,
        "lead_role": EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        "admin_role": EdifyRole.ADMIN.value,
        "lead_verified_roles": list(LEAD_VERIFIED_ROLES),
        "activity_types": {k: str(v) for k, v in ActivityType.choices},
        "intervention_abbreviations": {
            str(k): v for k, v in INTERVENTION_ABBREVIATIONS.items()
        },
        "page_size": TABLE_PAGE_SIZE,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Completion Reviews page's rules for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
