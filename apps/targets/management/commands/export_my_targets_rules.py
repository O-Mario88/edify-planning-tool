"""Write My Targets' page rules for Go.

Go builds /my-targets (apps.frontend.views.staff_views.my_targets_view over
apps.targets.my_targets.MyTargetQueryService.get_page) from the target engine
(platform/backend/internal/targets) and what this command writes to
platform/backend/internal/mytargets/rules.json: who may open the page and the
pages it links to; the pace bands; each area's next action and the activity
types its gap reasons read; the workflow statuses those reasons tell apart;
where each role's SSA link goes; the workspace strip each role is shown;
the Project, school-type, intervention and status names the priorities
sections print; the SSA score bands; and the operating statuses. A change to any of them must be exported again;
apps/targets/test_my_targets_rules_export.py fails until it is.

    python manage.py export_my_targets_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

EXPORT_PATH = Path("platform/backend/internal/mytargets/rules.json")
PAGE_PATH = "/my-targets"
PAGE_PERMISSION = "my_target"
#: The links the page draws only for a role that may open them.
LINKED_PAGES = ("/my-performance", "/priorities")
#: Stands in for the reader's id in a link that names it.
READER = "{reader}"


def _ssa_homes(role_user) -> dict[str, dict[str, str]]:
    """Each role's SSA home (analytics_retired.home(user, "ssa")), its own
    profile's address carrying READER where the reader's id goes."""
    from apps.core.rbac import EdifyRole
    from apps.frontend.views import analytics_retired

    out = {}
    for role in EdifyRole:
        user = role_user(role.value)
        user.id = READER
        home = analytics_retired.home(user, "ssa")
        out[role.value] = {"href": home["href"], "label": home["label"]}
    return out


def _bands() -> list[list]:
    """ssa_score_band at each of its floors, highest first."""
    from apps.core.enums import ssa_score_band

    return [
        [floor, *ssa_score_band(floor)[::2]] for floor in (10.0, 8.0, 6.0, 5.0, 0.0)
    ]


def rules() -> dict:
    from apps.analytics.pl_analytics_service import (
        CLUSTER_MEETING_TYPES,
        COMPLETED_STATUSES,
        TRAINING_TYPES,
        VISIT_TYPES,
    )
    from apps.core.enums import SchoolType, SsaIntervention
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.hr.models import PriorityStatus
    from apps.projects.models import (
        LIVE_PROJECT_STATUSES,
        ProjectSchoolFocus,
        ProjectStaffAssignment,
    )
    from apps.professional_development.models import PDStatus
    from apps.projects.staff_priorities import COMPLETED_STATES
    from apps.schools.lifecycle_models import OPERATING_STATUSES
    from apps.schools.management.commands.export_school_directory_rules import (
        _role_user,
    )
    from apps.targets.my_targets import (
        AREA_SOURCES,
        AT_RISK_BAND,
        NEXT_ACTIONS,
        ON_TRACK_BAND,
        RETURNED_FOR_CORRECTION_STATUSES,
        RETURNED_STATUSES,
    )

    def roles(test) -> list[str]:
        return sorted(r.value for r in EdifyRole if test(_role_user(r.value)))

    from apps.audit.management.commands.export_decision_log_rules import strip

    responsibility = ProjectStaffAssignment._meta.get_field("responsibility")
    page_roles = roles(
        lambda u: RolePermissionService.can_view_page(u, PAGE_PERMISSION)
        and bool(can_open_url(u, PAGE_PATH))
    )
    return {
        "page_roles": page_roles,
        # partials/_section_nav.html above the page: the workspace strip
        # each role is shown, as the feed reads it, or None.
        "strips": {
            role: strip(_role_user(role), PAGE_PATH, "partials/_section_nav.html")
            for role in page_roles
        },
        "opens": {
            path: roles(lambda u, path=path: bool(can_open_url(u, path)))
            for path in LINKED_PAGES
        },
        "ssa_homes": _ssa_homes(_role_user),
        "reader": READER,
        "on_track_band": ON_TRACK_BAND,
        "at_risk_band": AT_RISK_BAND,
        "next_actions": {k: list(v) for k, v in NEXT_ACTIONS.items()},
        "area_sources": {
            k: [kind, sorted(str(t) for t in types) if types else []]
            for k, (kind, types) in AREA_SOURCES.items()
        },
        "visit_types": sorted(str(t) for t in VISIT_TYPES),
        "cluster_meeting_types": sorted(str(t) for t in CLUSTER_MEETING_TYPES),
        "training_types": sorted(str(t) for t in TRAINING_TYPES),
        "completed_statuses": sorted(str(s) for s in COMPLETED_STATUSES),
        "returned_statuses": sorted(RETURNED_STATUSES),
        "returned_for_correction_statuses": sorted(RETURNED_FOR_CORRECTION_STATUSES),
        "live_project_statuses": sorted(s.value for s in LIVE_PROJECT_STATUSES),
        "project_completed_states": sorted(COMPLETED_STATES),
        "school_focus_labels": dict(ProjectSchoolFocus.choices),
        "responsibility_labels": dict(responsibility.choices),
        "school_types": [list(c) for c in SchoolType.choices],
        "intervention_labels": dict(SsaIntervention.choices),
        "priority_status_labels": dict(PriorityStatus.choices),
        "pd_status_labels": dict(PDStatus.choices),
        "ssa_bands": _bands(),
        "operating_statuses": sorted(str(s) for s in OPERATING_STATUSES),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write My Targets' page rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"wrote {EXPORT_PATH}")
