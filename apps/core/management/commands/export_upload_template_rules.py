"""Write the upload templates' rules for the Go gateway.

Three downloads hand a reader the file an upload reads: the SSA scores
template (ssa_views.ssa_template_download_view), the learning results
template (ia_school_evidence_views.learning_template_csv) and the strategic
priorities import template (target_distribution_views
.target_distribution_import_template). Their columns and the roles that may
take each are exported here, read from the views' own sources.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/uploadtemplates/rules.json")


def rules() -> dict:
    from apps.core.enums import SsaIntervention
    from apps.core.permissions import RolePermissionService, has_permission
    from apps.core.rbac import EdifyRole, Permission
    from apps.frontend.views.ssa_views import UPLOAD_ONLY_MESSAGE
    from apps.hr.priority_import import csv_template
    from apps.impact.evidence_services import LEARNING_CSV_COLUMNS

    doors = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        doors[role.value] = {
            "ssa_page": bool(RolePermissionService.can_view_page(user, "ssa")),
            "ssa_upload": bool(has_permission(user, Permission.SSA_UPLOAD.value)),
            "evidence_page": bool(
                RolePermissionService.can_view_page(user, "ia_school_evidence")
            ),
            "targets_page": bool(
                RolePermissionService.can_view_page(user, "target_distribution")
            ),
            "priorities_import": bool(
                has_permission(user, Permission.STRATEGIC_PRIORITIES_IMPORT.value)
            ),
        }
    return {
        "doors": doors,
        "ssa_refusal": UPLOAD_ONLY_MESSAGE,
        "ssa_interventions": [str(label) for _code, label in SsaIntervention.choices],
        "learning_columns": list(LEARNING_CSV_COLUMNS),
        "priority_template": csv_template(),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the upload templates' rules for the Go gateway."

    def add_arguments(self, parser):
        parser.add_argument("--check", action="store_true")

    def handle(self, *args, **options):
        text = rendered()
        if options["check"]:
            if not EXPORT_PATH.exists() or EXPORT_PATH.read_text() != text:
                raise SystemExit(f"{EXPORT_PATH} is out of date")
            return
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(text, encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
