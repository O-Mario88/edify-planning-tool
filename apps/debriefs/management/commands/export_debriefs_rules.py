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
editable; and the names of each activity state and intervention. A change
to any of them must be exported again; apps/debriefs/test_debriefs_rules_export.py
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

    pages, submit_pages = {}, {}
    for role in EdifyRole:
        user = _role_user(role.value)
        opens = RolePermissionService.can_view_page(user, PAGE_PERMISSION)
        pages[role.value] = opens and bool(can_open_url(user, PATH))
        submit_pages[role.value] = opens and bool(can_open_url(user, SUBMIT_PATH))
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
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Field Debrief Dashboard's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
