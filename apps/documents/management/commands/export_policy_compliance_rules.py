"""Write the Policy Compliance page's rules for the Go gateway.

Go builds Policy and Manual Compliance (/policy-compliance,
apps.documents.views.compliance_view, apps.documents.compliance and
pages/documents/compliance.html) from what this command writes to
platform/backend/internal/policycompliance/rules.json: for each role, whether
it may open the page, the workspace strip it is shown, whether it reads the
policy comments (`policies.review_comments`) and the line under the title
(`_scope_note`); the labels of the two registered figures; which document
statuses are readable; the labels of an acknowledgement's state and of a
reader's viewer completion; how many rows the table holds and lists a page;
and the query keys the feed never passes. A change to any of them must be
exported again; apps/documents/test_policy_compliance_rules_export.py fails
until it is.

    python manage.py export_policy_compliance_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/policycompliance/rules.json")

PERMISSION = "policy_compliance"
PATH = "/policy-compliance"

#: records = list(qs[:1000]) in PolicyComplianceService.report.
ROW_LIMIT = 1000

#: The two figures the strip registers, and where each drills.
METRICS = {
    "policy_acknowledgements_accepted": "/policy-compliance?state=agreed",
    "policy_acknowledgements_overdue": "/policy-compliance?state=pending",
}

#: Acknowledgement.reading_completion_label, by its key.
COMPLETION_LABELS = {
    "completed": "Completed reading",
    "completed_offline": "Completed outside viewer",
    "partial": "Partial read",
    "not_read": "Did not read",
    "not_monitored": "Not monitored",
}


def rules() -> dict:
    from apps.core.metrics import MetricValue, render_metric
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.core.permissions import (
        RolePermissionService,
        can_open_url,
        has_permission,
    )
    from apps.core.rbac import EdifyRole
    from apps.documents.compliance import _scope_note
    from apps.documents.models import AcknowledgementState, READABLE_STATUSES
    from apps.mobile_feed.views import NOT_PASSED

    roles = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        page = RolePermissionService.can_view_page(user, PERMISSION) and bool(
            can_open_url(user, PATH)
        )
        roles[role.value] = {
            "page": page,
            "strip": strip(user, PATH, "partials/_section_nav.html") if page else None,
            "comments": has_permission(user, "policies.review_comments"),
            "scope_note": _scope_note(user),
        }
    return {
        "roles": roles,
        "metric_labels": {
            key: render_metric(key, MetricValue.measured(0)).label for key in METRICS
        },
        "metric_drilldowns": METRICS,
        "readable_statuses": sorted(str(s) for s in READABLE_STATUSES),
        "states": dict(AcknowledgementState.choices),
        "completion_labels": COMPLETION_LABELS,
        "row_limit": ROW_LIMIT,
        "page_size": TABLE_PAGE_SIZE,
        "query_keys_not_passed": sorted(NOT_PASSED),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Policy Compliance page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
