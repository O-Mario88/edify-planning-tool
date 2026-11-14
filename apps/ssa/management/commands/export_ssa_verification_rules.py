"""Write the SSA Verification queue's rules for the Go gateway.

Go builds SSA Verification (/ssa/verification/,
apps.frontend.views.ssa_views.ssa_verification_queue_view over
apps.ssa.services.readable_records / verifiable_records and
pages/ssa/verification_queue.html) from what this command writes to
platform/backend/internal/ssaverify/rules.json: who may open the page and the
IA workspace strip each draws; who verifies with the IA permission; the
Country Director and lead roles; the queue's statuses; the words for where
scores came from and who collected them; the roles that open a visit in its
review workspace; and the page size. A change to any of them must be
exported again; apps/ssa/test_ssa_verification_rules_export.py fails until it
is.

    python manage.py export_ssa_verification_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/ssaverify/rules.json")

PAGE_PATH = "/ssa/verification/"
PAGE_PERMISSION = "ssa"

#: ssa_verification_queue_view's visit door: these roles open the visit in
#: its review workspace, everyone else in their plan.
VISIT_REVIEW_ROLES = ["ImpactAssessment", "CountryDirector"]

#: _collector_label's words for who collected the scores.
COLLECTOR_KINDS = {"ia": "Impact Assessment", "partner": "Partner", "staff": "Staff"}


def rules() -> dict:
    from apps.analytics.ia_collection import PAGE_SIZE
    from apps.core.permissions import (
        Permission,
        RolePermissionService,
        can_open_url,
        has_permission,
    )
    from apps.core.rbac import EdifyRole
    from apps.frontend.views.ssa_views import QUEUE_STATUSES
    from apps.ssa import services as svc

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
            "ia_verify": has_permission(user, Permission.IA_VERIFY.value),
        }
    return {
        "roles": roles,
        "country_director_role": EdifyRole.COUNTRY_DIRECTOR.value,
        "lead_role": EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        "ia_role": EdifyRole.IMPACT_ASSESSMENT.value,
        "queue_statuses": [[k, str(v)] for k, v in QUEUE_STATUSES.items()],
        "sources": {
            svc.SOURCE_STAFF_KEYED: "Keyed by staff",
            svc.SOURCE_IA_KEYED: "Keyed by Impact Assessment",
            svc.SOURCE_FILE_IMPORT: "File import",
            svc.SOURCE_PARTNER: "Partner submission",
        },
        "staff_keyed_source": svc.SOURCE_STAFF_KEYED,
        "collector_kinds": COLLECTOR_KINDS,
        "visit_review_roles": VISIT_REVIEW_ROLES,
        "page_size": PAGE_SIZE,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the SSA Verification queue's rules for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
