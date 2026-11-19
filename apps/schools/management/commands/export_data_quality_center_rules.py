"""Write the Data Quality Center's rules for the Go gateway.

Go builds the Data Quality Center (/admin-panel/data-quality-center,
apps.frontend.views.extended_views.admin_data_quality_center_view and
pages/admin/data_quality_center.html) from what this command writes to
platform/backend/internal/dataquality/rules.json: who may open the page, the
IA workspace strip each draws, who may open the staff setup queue and a
school's profile; the quality states the tiles count; the issue sections in
order; the statuses that keep a school operating; the unmatched-SSA states
still waiting; and the tables' page size. And the Duplicate Review Queue's
(/data-quality/duplicates: duplicate_review_view): who opens it and who may
open a district's profile from it. A change to any of them must be exported
again; apps/schools/test_data_quality_center_rules_export.py fails
until it is.

    python manage.py export_data_quality_center_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/dataquality/rules.json")

PAGE_PATH = "/admin-panel/data-quality-center"
PAGE_PERMISSION = "data_quality_center"
DUPLICATES_PATH = "/data-quality/duplicates"

#: The tiles, in order: the quality state each counts.
TILES = [
    ["Clean Schools", "Clean", "Fully complete verified roster"],
    ["Needs Review", "Needs Review", "Minor operational gaps"],
    ["Needs Cleanup", "Needs Cleanup", "Moderate gaps present"],
    ["Duplicate Risk", "Duplicate Risk", "Potential duplicate entries"],
    ["Missing Critical Data", "Missing Critical Data", "Missing owner/cluster info"],
]

#: The issue sections, in order: the heading and the issue type each lists.
SECTIONS = [
    ["Missing Phone Numbers", "missing_phone"],
    ["Missing Primary Contact", "missing_contact"],
    ["Missing Enrollment Data", "missing_enrollment"],
    ["Schools Without a Cluster", "no_cluster"],
    ["Unmatched Staff Owners", "unmatched_staff"],
    ["Schools Missing SSA", "no_ssa"],
]

#: The unmatched SSA uploads still waiting to be linked.
UNMATCHED_SSA_STATUSES = ["pending", "hold"]


def rules() -> dict:
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.schools.lifecycle_service import OPERATING_STATUSES

    roles = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        page = RolePermissionService.can_view_page(user, PAGE_PERMISSION) and bool(
            can_open_url(user, PAGE_PATH)
        )
        roles[role.value] = {
            "page": page,
            "strip": strip(user, PAGE_PATH, "partials/_section_nav.html")
            if page
            else None,
            "setup_queue": bool(can_open_url(user, "/admin-panel/staff-setup-queue")),
            "school_profiles": bool(can_open_url(user, "/schools/0")),
            "district_profiles": bool(can_open_url(user, "/districts/0")),
            "duplicates": RolePermissionService.can_view_page(user, PAGE_PERMISSION)
            and bool(can_open_url(user, DUPLICATES_PATH)),
        }
    return {
        "roles": roles,
        "tiles": TILES,
        "sections": SECTIONS,
        "operating_statuses": sorted(str(s) for s in OPERATING_STATUSES),
        "unmatched_ssa_statuses": UNMATCHED_SSA_STATUSES,
        "page_size": TABLE_PAGE_SIZE,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Data Quality Center's rules for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
