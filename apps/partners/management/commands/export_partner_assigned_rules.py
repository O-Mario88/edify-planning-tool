"""Write the partner's Assigned Schools and Assigned Activities rules for Go.

Go builds Assigned Schools (/partner/assigned-schools) and Assigned
Activities (/partner/assigned-activities) and Evidence (/partner/evidence)
(apps.frontend.views.partner_views
._assigned_intake and pages/partner/assigned_list.html) from what this
command writes to platform/backend/internal/partnerassigned/rules.json: who
may open each page; the assignment statuses the queue lists and how many;
the activity types that make an assignment cluster work; the label of each
coded visit purpose (apps.partners.purposes.visit_purpose_label); whether
the demo role-bridge pins a partner login to the first partner
(PARTNER_ROLE_BRIDGE); the table's page size; and the query keys the feed
never passes. A change to any of them must be exported again;
apps/partners/test_partner_assigned_rules_export.py fails until it is.

    python manage.py export_partner_assigned_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/partnerassigned/rules.json")

#: Each page and its permission.
PAGES = {
    "/partner/assigned-schools": "partner_schools",
    "/partner/assigned-activities": "partner_assignments",
    "/partner/evidence": "partner_evidence",
}

#: partner_evidence_view: the newest uploads and the completed work still
#: missing evidence it lists.
EVIDENCE_LIMIT = 50
MISSING_EVIDENCE_LIMIT = 10

#: _assigned_intake's queue: these statuses, the newest 300.
QUEUE_STATUSES = ["assigned", "pending_scheduling", "returned"]
QUEUE_LIMIT = 300


def rules() -> dict:
    from django.conf import settings

    from apps.activities.models import ActivityType
    from apps.core.activity_types import COMPLETED_WORK_STATUSES
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.frontend.views.partner_views import _CLUSTER_SCOPE_TYPES
    from apps.mobile_feed.views import NOT_PASSED
    from apps.partners.purposes import _LABELS

    return {
        "page_roles": {
            path: sorted(
                role.value
                for role in EdifyRole
                if RolePermissionService.can_view_page(
                    _role_user(role.value), permission
                )
                and can_open_url(_role_user(role.value), path)
            )
            for path, permission in PAGES.items()
        },
        "queue_statuses": QUEUE_STATUSES,
        "queue_limit": QUEUE_LIMIT,
        "cluster_scope_types": sorted(_CLUSTER_SCOPE_TYPES),
        "purpose_labels": {str(k): str(v) for k, v in _LABELS.items()},
        "partner_role_bridge": bool(getattr(settings, "PARTNER_ROLE_BRIDGE", False)),
        "page_size": TABLE_PAGE_SIZE,
        "query_keys_not_passed": sorted(NOT_PASSED),
        # The partner's Evidence page (partner_evidence_view).
        "activity_types": {k: str(v) for k, v in ActivityType.choices},
        "completed_work_statuses": list(COMPLETED_WORK_STATUSES),
        "evidence_limit": EVIDENCE_LIMIT,
        "missing_evidence_limit": MISSING_EVIDENCE_LIMIT,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the partner's Assigned Schools and Activities rules for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
