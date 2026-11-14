"""Write the Closure Quality page's rules for the Go gateway.

Go builds Closure Quality (/analytics/closure-quality,
apps.frontend.views.closure_quality_views.closure_quality_view,
apps.schools.closure_analytics and the closure-quality partials) from what
this command writes to platform/backend/internal/closurequality/rules.json:
who may open the page; each closure reason's label and the reasons that are
weak ground; the duplicate state that strands a merge; how late a recording
may be; how many rows a list reads; and the table page size. A change to any
of them must be exported again;
apps/schools/test_closure_quality_rules_export.py fails until it is.

    python manage.py export_closure_quality_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/closurequality/rules.json")

PAGE_PATH = "/analytics/closure-quality"
PAGE_PERMISSION = "closure_quality"


def rules() -> dict:
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.schools import closure_analytics as ca
    from apps.schools.lifecycle_models import ClosureReason

    return {
        "page_roles": sorted(
            role.value
            for role in EdifyRole
            if RolePermissionService.can_view_page(
                _role_user(role.value), PAGE_PERMISSION
            )
            and can_open_url(_role_user(role.value), PAGE_PATH)
        ),
        "reasons": {k: str(v) for k, v in ClosureReason.choices},
        "weak_ground_reasons": sorted(str(r) for r in ca.WEAK_GROUND_REASONS),
        "unresolved_duplicate": ca.UNRESOLVED_DUPLICATE,
        "stale_recording_days": ca.STALE_RECORDING_DAYS,
        "max_rows": ca.MAX_ROWS,
        "page_size": TABLE_PAGE_SIZE,
        # Who may open a school's profile, so a school's name is a link
        # (apps.frontend.templatetags.school_links._may_open_profiles).
        "school_profile_roles": sorted(
            role.value
            for role in EdifyRole
            if can_open_url(_role_user(role.value), "/schools/0")
        ),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Closure Quality page's rules for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
