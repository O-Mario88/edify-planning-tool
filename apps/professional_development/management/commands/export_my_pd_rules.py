"""Write My Professional Development's rules for the Go gateway.

Go builds My Professional Development (/my-professional-development:
pd_views.my_professional_development_view, StaffPDService.get_page and
partials/professional_development/body.html) and makes the writes its read
makes (PDCourseTrackingService.sync_all, get_or_create_allocation; owner,
2026-11-16: "Same writes") from what this command writes to
platform/backend/internal/mypd/rules.json: who opens the page and the strip
it shows them; the statuses, course types, funding types and document types
and their labels; the status groups the figures, the current course and the
course table count; the Course Progress Tracker's steps and where each status
stands on it; each status's next action; the reminders the clock closes; and
the figures' labels. A change to any of them must be exported again;
apps/professional_development/test_my_pd_rules_export.py fails until it is.

    python manage.py export_my_pd_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/mypd/rules.json")

PAGE_PATH = "/my-professional-development"

#: The figures the page shows, in the order get_page builds them.
METRIC_KEYS = (
    "professional_development_services_annual_pd_allocation",
    "professional_development_services_committed_amount",
    "professional_development_services_funds_used_accounted",
    "professional_development_services_remaining_fund",
    "professional_development_services_active_courses",
    "professional_development_services_certificates_pending",
    "professional_development_services_accountability_pending",
    "professional_development_services_completed_courses",
)


def strip(user):
    """The workspace strip the page shows ``user``, as the feed reads it."""
    from django.template.loader import render_to_string

    from apps.core.navigation import build_workspace
    from apps.mobile_feed import page_blocks

    html = render_to_string(
        "partials/_section_nav.html", {"workspace": build_workspace(user, PAGE_PATH)}
    )
    blocks = page_blocks.read(html)["blocks"]
    return blocks[0]["linkTabs"] if blocks else None


def doors() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            "page": RolePermissionService.can_view_page(
                user, "my_professional_development"
            )
            and bool(can_open_url(user, PAGE_PATH)),
            "strip": strip(user),
        }
    return out


def _values(statuses) -> list[str]:
    return [str(s) for s in statuses]


def rules() -> dict:
    from apps.core.metrics.reconciled_registry import source_label_for_key
    from apps.professional_development import models, reminders, services

    status = models.PDStatus
    return {
        "doors": doors(),
        "status_labels": {str(v): str(label) for v, label in status.choices},
        "course_types": {
            str(v): str(label) for v, label in models.PDCourseType.choices
        },
        "document_types": {
            str(v): str(label) for v, label in models.PDCompletionDocumentType.choices
        },
        "self_funded": str(models.PDFundingType.SELF_FUNDED),
        "funded_types": _values(models.FUNDED_TYPES),
        "active_statuses": _values(models.ACTIVE_COURSE_STATUSES),
        "closed_statuses": _values(models.CLOSED_STATUSES),
        "committed_statuses": _values(models.COMMITTED_STATUSES),
        "timeline_steps": [label for _key, label in services.TIMELINE_STEPS],
        "step_index": {str(k): v for k, v in services._STEP_INDEX.items()},
        "next_actions": {
            str(k): label
            for k, (label, _action) in services.NEXT_ACTION_BY_STATUS.items()
        },
        "starting_event": reminders.PD_COURSE_STARTING,
        "in_progress_event": reminders.PD_COURSE_IN_PROGRESS,
        "metric_labels": [source_label_for_key(key) for key in METRIC_KEYS],
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write My Professional Development's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
