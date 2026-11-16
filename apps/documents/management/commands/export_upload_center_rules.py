"""Write the Upload Center's rules for the Go gateway.

Go builds the Upload Center (/uploads: apps.documents.views
.upload_center_view, apps.documents.upload_center.UploadCenterService and
pages/documents/upload_center.html) from what this command writes to
platform/backend/internal/uploadcenter/rules.json: for each role, whether it
may open the page, the upload actions it is offered, whether it has the
Admin's upload drawer, the permissions that decide which uploads and
figures it sees, and the role's slug (an audience rule may name either);
the figures' labels; the names of each record type and status; the
training document types; and the page size. A change to any of them must be
exported again; apps/documents/test_upload_center_rules_export.py fails
until it is.

    python manage.py export_upload_center_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/uploadcenter/rules.json")

PAGE_PERMISSION = "uploads"
PATH = "/uploads"

#: The strip's figures, in order.
METRIC_KEYS = (
    "uploads_awaiting_review",
    "uploads_documents_published",
    "policy_acknowledgements_overdue",
)


def roles() -> dict:
    from apps.core.navigation import get_user_role_slug
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole, Permission, permissions_for_role
    from apps.documents.services import has_permission
    from apps.documents.upload_center import UploadCenterService

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        held = set(permissions_for_role(role.value))
        out[role.value] = {
            # require_page_permission("uploads"), the feed's can_open_url and
            # the service's uploads.view (without it the page redirects).
            "page": RolePermissionService.can_view_page(user, PAGE_PERMISSION)
            and bool(can_open_url(user, PATH))
            and has_permission(user, "uploads.view"),
            "actions": UploadCenterService.launch_actions(user),
            "admin_menu": role.value == "Admin",
            "school_upload": Permission.SCHOOL_UPLOAD.value in held,
            "ssa_upload": Permission.SSA_UPLOAD.value in held,
            "documents_create": has_permission(user, "documents.create"),
            "training_create": has_permission(user, "training_resources.create"),
            "manage_acknowledgements": has_permission(
                user, "policies.manage_acknowledgements"
            ),
            "slug": get_user_role_slug(user),
        }
    return out


def rules() -> dict:
    from apps.core.metrics import MetricValue, render_metric
    from apps.documents.models import (
        DocumentStatus,
        DocumentType,
        PreviewStatus,
        TRAINING_TYPES,
    )
    from apps.documents.upload_center import UploadCenterService
    from apps.frontend.templatetags.frontend_filters import status_label
    from apps.schools.models import SchoolImportBatch, SSAImportBatch

    record_types = [str(v) for v, _ in DocumentType.choices] + [
        "school_import",
        "ssa_import",
    ]
    return {
        "roles": roles(),
        "metric_labels": [
            render_metric(key, MetricValue.measured(0)).label for key in METRIC_KEYS
        ],
        "type_labels": {t: status_label(t) for t in record_types},
        "document_statuses": dict(DocumentStatus.choices),
        "preview_statuses": dict(PreviewStatus.choices),
        "school_import_statuses": dict(SchoolImportBatch.STATUSES),
        "ssa_import_statuses": dict(SSAImportBatch.STATUSES),
        "training_types": sorted(str(t) for t in TRAINING_TYPES),
        "page_size": UploadCenterService.PAGE_SIZE,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Upload Center's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
