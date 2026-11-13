"""Write the HR registers' rules for the Go gateway.

Go builds the HR programme registers (apps.frontend.views.hr_views pages drawn
by `_render_workspace`: pages/hr/module_workspace.html and
partials/hr/module_register.html) from the vocabularies this command writes
to platform/backend/internal/hrregister/rules.json: for each register Go
answers, who may open it, the workspace strip each role is shown above it and
which of its drawer buttons each role is shown; the labels of a People
record's lifecycle, a recognition's category and a safety incident's
category, severity and status, an onboarding plan's status and an exit's
reason, and which reasons are voluntary, an application's stage and an employee's compliance status; the label each context figure
is drawn with; how long the line under a figure may stay; and the register's
page size. A change to any of them must be exported again;
apps/hr/test_hr_register_rules_export.py fails until it is, so the two can
never drift.

The doors, the strip and the buttons are not restated: each role's answer is
computed here by the gates the page itself asks (`require_page_permission`,
the feed's `can_open_url` and the template's `can_open` for every button),
and the strip is the workspace template rendered for that role and read by
the feed's own reader.

    python manage.py export_hr_register_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/hrregister/rules.json")

#: The metric source every register's figures are registered under.
METRIC_SOURCE = "apps.frontend.views.hr_views:_metric"

#: The registers Go answers: their path, page permission, the drawers their
#: header buttons open and the labels of their context figures, as the views
#: write them.
PAGES = {
    "/org-structure": {
        "permission": "org_structure",
        "drawers": [],
        "metrics": ["People in scope", "Active", "Departments", "No reporting line"],
    },
    "/recognition": {
        "permission": "recognition",
        "drawers": ["/recognition/new"],
        "metrics": ["Recognitions", "People recognised"],
    },
    "/onboarding": {
        "permission": "onboarding",
        "drawers": [],
        "metrics": ["Plans", "Overdue", "Awaiting supervisor", "Ready for activation"],
    },
    "/offboarding": {
        "permission": "offboarding",
        "drawers": ["/offboarding/new"],
        "metrics": [
            "In progress",
            "Handover gaps",
            "Voluntary exits",
            "Past exit date, still active",
        ],
    },
    "/candidate-pipeline": {
        "permission": "candidate_pipeline",
        "drawers": ["/candidate-pipeline/new"],
        "metrics": ["Applications", "Screening", "Interviews", "Offers", "Hired"],
    },
    "/compliance-register": {
        "permission": "compliance_register",
        "drawers": ["/compliance-register/new", "/compliance-register/requirement"],
        "metrics": ["Requirements", "Compliant", "Due soon", "Missing or expired"],
    },
    "/hr-audit-log": {
        "permission": "hr_audit_log",
        "drawers": [],
        "metrics": ["Events", "Refused actions", "Acting roles", "Showing"],
    },
    "/health-safety": {
        "permission": "health_safety",
        "drawers": ["/health-safety/new"],
        "metrics": ["Open incidents", "Serious incidents", "Near misses", "Days lost"],
    },
}


def pages() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for path, page in PAGES.items():
        roles = {}
        for role in EdifyRole:
            user = _role_user(role.value)
            roles[role.value] = {
                "page": RolePermissionService.can_view_page(user, page["permission"])
                and bool(can_open_url(user, path)),
                "strip": strip(user, path, "partials/_section_nav.html"),
                "drawers": [d for d in page["drawers"] if can_open_url(user, d)],
            }
        out[path] = {"roles": roles}
    return out


def metric_labels() -> dict:
    """The label each figure is drawn with (the registry's source label)."""
    from apps.core.metrics.reconciled_registry import (
        key_for_source_label,
        source_label_for_key,
    )

    return {
        label: source_label_for_key(key_for_source_label(METRIC_SOURCE, label))
        for page in PAGES.values()
        for label in page["metrics"]
    }


def rules() -> dict:
    from apps.accounts.models import StaffOnboardingState
    from apps.core.metrics.payload import HELPER_FIGURE_CHARS
    from apps.hr.models import (
        VOLUNTARY_EXIT_REASONS,
        ApplicationStage,
        ComplianceStatus,
        ERSeverity,
        ExitReason,
        OnboardingStatus,
        RecognitionCategory,
        SafetyIncidentCategory,
        SafetyIncidentStatus,
    )
    from apps.core.pagination import TABLE_PAGE_SIZE

    return {
        "pages": pages(),
        "onboarding_states": dict(StaffOnboardingState.choices),
        "recognition_categories": dict(RecognitionCategory.choices),
        "safety_categories": dict(SafetyIncidentCategory.choices),
        "severities": dict(ERSeverity.choices),
        "safety_statuses": dict(SafetyIncidentStatus.choices),
        "onboarding_statuses": dict(OnboardingStatus.choices),
        "exit_reasons": dict(ExitReason.choices),
        "voluntary_exit_reasons": sorted(str(r) for r in VOLUNTARY_EXIT_REASONS),
        "application_stages": dict(ApplicationStage.choices),
        "compliance_statuses": dict(ComplianceStatus.choices),
        "metric_labels": metric_labels(),
        "helper_figure_chars": HELPER_FIGURE_CHARS,
        "page_size": TABLE_PAGE_SIZE,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the HR registers' rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
