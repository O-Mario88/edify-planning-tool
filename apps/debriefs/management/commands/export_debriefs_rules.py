"""Write the Field Debrief Dashboard's rules for the Go gateway.

Go builds the dashboard (/debriefs: apps.frontend.views.debrief_views
.field_debrief_dashboard_view, apps.debriefs.dashboard_service
.FieldDebriefDashboardService, apps.debriefs.field_debrief_service
.FieldDebriefService.scoped_queryset and pages/debriefs/dashboard.html) from
what this command writes to platform/backend/internal/debriefs/rules.json:
which roles open the page; the partner roles; the statuses a Programme Lead
reviews; the names of each status, risk level, completion, kind, challenge
and activity type; the figures' labels; and the page size. It also writes
the Daily Debrief's (/debriefs/submit: field_debrief_submit_view over
DailyDebriefFlowService.get_state, pages/debriefs/submit.html): which roles
open it and which may submit; the work states it ticks, hides and keeps
editable; and the names of each activity state and intervention. And the
Weekly Debrief Report's (/debriefs/weekly-report: weekly_debrief_report_view
over WeeklyDebriefReportService.visible_report, pages/debriefs/
weekly_report.html): which roles open it, which report each role lands on,
whose page writes a missing report as it opens, who is offered Generate,
and the names of each report scope and state. A change to any of them must
be exported again; apps/debriefs/test_debriefs_rules_export.py
fails until it is.

    python manage.py export_debriefs_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/debriefs/rules.json")

PAGE_PERMISSION = "debriefs_list"
PATH = "/debriefs"
SUBMIT_PATH = "/debriefs/submit"
WEEKLY_PATH = "/debriefs/weekly-report"

#: The strip's figures, in the order _kpis builds them.
METRIC_KEYS = (
    "debriefs_dashboard_service_debriefs_submitted",
    "debriefs_dashboard_service_activities_completed",
    "debriefs_dashboard_service_partially_completed",
    "debriefs_dashboard_service_unsuccessful_cancelled",
    "debriefs_dashboard_service_action_required",
    "debriefs_dashboard_service_critical_escalations",
    "debriefs_dashboard_service_open_commitments",
    "debriefs_dashboard_service_peer_solutions",
)


def rules() -> dict:
    from apps.activities.models import ActivityType
    from apps.core.metrics.reconciled_registry import source_label_for_key
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.debriefs.dashboard_service import PER_PAGE
    from apps.activities.models import ActivityStatus
    from apps.core.enums import SsaIntervention
    from apps.debriefs.field_debrief_service import (
        DAILY_EDITABLE_STATUSES,
        DAILY_HIDDEN_STATUSES,
        DAILY_PRESELECT_STATUSES,
        PARTNER_ROLES,
        REVIEWABLE_STATUSES,
        SUBMITTER_ROLES,
    )
    from apps.debriefs.models import (
        CompletionStatus,
        DebriefChallengeType,
        DebriefKind,
        DebriefStatus,
        RiskLevel,
    )

    pages, submit_pages, weekly_pages = {}, {}, {}
    for role in EdifyRole:
        user = _role_user(role.value)
        opens = RolePermissionService.can_view_page(user, PAGE_PERMISSION)
        pages[role.value] = opens and bool(can_open_url(user, PATH))
        submit_pages[role.value] = opens and bool(can_open_url(user, SUBMIT_PATH))
        weekly_pages[role.value] = opens and bool(can_open_url(user, WEEKLY_PATH))
    return {
        "pages": pages,
        "partner_roles": list(PARTNER_ROLES),
        "reviewable_statuses": [str(s) for s in REVIEWABLE_STATUSES],
        "statuses": dict(DebriefStatus.choices),
        "risk_levels": [list(pair) for pair in RiskLevel.choices],
        "completions": dict(CompletionStatus.choices),
        "kinds": dict(DebriefKind.choices),
        "challenge_types": dict(DebriefChallengeType.choices),
        "activity_types": {str(v): str(label) for v, label in ActivityType.choices},
        "metric_labels": [source_label_for_key(key) for key in METRIC_KEYS],
        "page_size": PER_PAGE,
        "submit_pages": submit_pages,
        "submitter_roles": [str(r) for r in SUBMITTER_ROLES],
        "daily_preselect_statuses": list(DAILY_PRESELECT_STATUSES),
        "daily_hidden_statuses": list(DAILY_HIDDEN_STATUSES),
        "daily_editable_statuses": [str(s) for s in DAILY_EDITABLE_STATUSES],
        "activity_statuses": {str(v): str(lb) for v, lb in ActivityStatus.choices},
        "interventions": {str(v): str(lb) for v, lb in SsaIntervention.choices},
        "weekly": weekly_rules(weekly_pages),
    }


def weekly_rules(pages: dict) -> dict:
    """The Weekly Debrief Report's roles, as visible_report and the view
    name them."""
    from apps.core.rbac import EdifyRole
    from apps.debriefs.models import WeeklyReportScope, WeeklyReportStatus

    lead = EdifyRole.COUNTRY_PROGRAM_LEAD.value
    director = EdifyRole.COUNTRY_DIRECTOR.value
    return {
        "pages": pages,
        # visible_report: a Lead reads their team's report; these read the
        # country's, a Director their own country's when they have one.
        "team_reader": lead,
        "country_readers": [
            director,
            EdifyRole.HUMAN_RESOURCES.value,
            EdifyRole.REGIONAL_VICE_PRESIDENT.value,
            EdifyRole.ADMIN.value,
        ],
        "own_country_reader": director,
        # They read only a finalized country report.
        "finalized_readers": [
            EdifyRole.REGIONAL_VICE_PRESIDENT.value,
            EdifyRole.HUMAN_RESOURCES.value,
        ],
        # The view generates a missing report as these open the page.
        "writes_on_open": [lead, director],
        # The empty page offers these Generate Draft Report.
        "generators": [lead, director, EdifyRole.ADMIN.value],
        "scopes": {str(v): str(lb) for v, lb in WeeklyReportScope.choices},
        "statuses": {str(v): str(lb) for v, lb in WeeklyReportStatus.choices},
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Field Debrief Dashboard's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
