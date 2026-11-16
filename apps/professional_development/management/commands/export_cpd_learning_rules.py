"""Write the HR Professional Development Dashboard's rules for the Go gateway.

Go builds the dashboard (/cpd-learning: apps.frontend.views.hr_views
.cpd_learning_view, apps.professional_development.hr_dashboard_service
.HRPDDashboardService and partials/hr/pd_dashboard/body.html) from what this
command writes to platform/backend/internal/cpdlearning/rules.json: for each
role, whether it may open the page, the workspace strip it is shown, whether
it reads the team view, may adjust allocations or sign off, and whether a
staff member's name opens their profile; the eligible roles; the names of
each status, course type and next action; the status sets each figure and
queue counts; and the figures' labels. A change to any of them must be
exported again; apps/professional_development/
test_cpd_learning_rules_export.py fails until it is.

    python manage.py export_cpd_learning_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.audit.management.commands.export_decision_log_rules import strip
from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/cpdlearning/rules.json")

PAGE_PERMISSION = "cpd_learning"
PATH = "/cpd-learning"

#: The strip's figures, in the order get_dashboard builds them.
METRIC_KEYS = (
    "professional_development_hr_dashboard_service_total_annual_pd_allocation",
    "professional_development_hr_dashboard_service_funds_committed",
    "professional_development_hr_dashboard_service_funds_accounted_for",
    "professional_development_hr_dashboard_service_staff_enrolled",
    "professional_development_hr_dashboard_service_courses_in_progress",
    "professional_development_hr_dashboard_service_pending_certificate_uploads",
    "professional_development_hr_dashboard_service_pending_accountability",
    "professional_development_hr_dashboard_service_hr_sign_off_pending",
)


def _values(statuses) -> list[str]:
    return [str(s) for s in statuses]


def roles() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        page = RolePermissionService.can_view_page(user, PAGE_PERMISSION) and bool(
            can_open_url(user, PATH)
        )
        out[role.value] = {
            "page": page,
            "strip": strip(user, PATH, "partials/_section_nav.html") if page else None,
            "team_view": role.value == "Program Lead",
            "adjust_allocation": role.value in ("HumanResources", "Admin"),
            "sign_off": role.value in ("HumanResources", "Admin"),
            "staff_links": bool(can_open_url(user, "/staff/0")),
        }
    return out


def rules() -> dict:
    from apps.core.metrics.reconciled_registry import source_label_for_key
    from apps.professional_development import hr_dashboard_service as hr
    from apps.professional_development.models import (
        COMMITTED_STATUSES,
        FUNDED_TYPES,
        PDCourseType,
        PDStatus,
    )
    from apps.professional_development.services import NEXT_ACTION_BY_STATUS

    return {
        "roles": roles(),
        "eligible_roles": [list(pair) for pair in hr.PD_ELIGIBLE_ROLES],
        "statuses": dict(PDStatus.choices),
        "course_types": dict(PDCourseType.choices),
        "next_actions": {str(k): v[0] for k, v in NEXT_ACTION_BY_STATUS.items()},
        "committed_statuses": _values(COMMITTED_STATUSES),
        "funded_types": _values(FUNDED_TYPES),
        "not_started_statuses": _values(hr.NOT_STARTED_STATUSES),
        "in_progress_statuses": _values(hr.IN_PROGRESS_STATUSES),
        "pending_certificate_statuses": _values(hr.PENDING_CERT_STATUSES),
        "employee_done_statuses": _values(hr.EMPLOYEE_DONE_STATUSES),
        "signed_off_statuses": _values(hr.SIGNED_OFF_STATUSES),
        "pending_accountability_statuses": _values(hr.PENDING_ACCOUNTABILITY_STATUSES),
        "status_buckets": [list(pair) for pair in hr.STATUS_BUCKET_OPTIONS],
        "reminders": [list(pair) for pair in hr.REMINDER_OPTIONS],
        "fund_status_labels": dict(hr.FUND_STATUS_LABELS),
        "not_applied_statuses": _values(hr.NOT_APPLIED_REQUEST_STATUSES),
        "fund_applied_statuses": _values(hr.FUND_APPLIED_STATUSES),
        "fund_processing_statuses": _values(hr.FUND_PROCESSING_STATUSES),
        "fund_in_progress_statuses": _values(hr.FUND_IN_PROGRESS_STATUSES),
        "fund_completed_statuses": _values(hr.FUND_COMPLETED_STATUSES),
        "certificate_labels": dict(hr.CERTIFICATE_STATUS_LABELS),
        "on_bamboohr_statuses": _values(hr._ON_BAMBOOHR_STATUSES),
        "metric_labels": [source_label_for_key(key) for key in METRIC_KEYS],
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the HR Professional Development Dashboard's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
