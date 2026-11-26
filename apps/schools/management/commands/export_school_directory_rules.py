"""Write the School Directory's rules for the Go gateway.

Go owns the School Directory (owner brief, 2026-11-11: "School Directory and
School Profiles"). It reads the vocabularies the directory is built from —
which activities are visits, which statuses mean done, the SSA interventions
and groups, the gap labels, who reads which country, who may open the page —
from platform/backend/internal/schooldirectory/rules.json, which this command
writes from the modules that define them. A change to any of them must be
exported again; apps/schools/test_school_directory_rules_export.py fails until
it is, so the two can never drift.

Page access is not restated: it is computed here by the existing gates
(RolePermissionService.can_view_page, can_open_url) for each role.

    python manage.py export_school_directory_rules
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand

EXPORT_PATH = Path("platform/backend/internal/schooldirectory/rules.json")


def _role_user(role: str):
    """A principal working in its own role, as the page gates read one."""
    return SimpleNamespace(
        id="",
        pk=None,
        user_id="",
        active_role=role,
        roles=[role],
        is_authenticated=True,
        is_superuser=False,
        staff_profile_id=None,
    )


def page_access() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    return {
        role.value: {
            "directory": RolePermissionService.can_view_page(
                _role_user(role.value), "school_directory"
            ),
            "profile": can_open_url(_role_user(role.value), "/schools/0"),
            # school_directory_view's require_export_permission (?export=).
            "data_export": bool(
                RolePermissionService.can_export(_role_user(role.value), "/schools")
            ),
        }
        for role in EdifyRole
    }


def rules() -> dict:
    from apps.activities.cluster_attendance import (
        CLUSTER_CREDIT_STATUSES,
        CLUSTER_TRAINING_TYPES,
        SCHOOL_TRAINING_TYPES,
    )
    from apps.core import scoping
    from apps.core.activity_types import (
        CLUSTER_MEETING_TYPES,
        COMPLETED_WORK_STATUSES,
        VISIT_TYPES,
    )
    from apps.core.enums import SsaIntervention
    from apps.mobile_feed.views import DIRECTORY_TABS
    from apps.planning.country_oversight.rules import TRAINED_TYPES
    from apps.projects.capacity import CAPACITY_EXEMPT_ROLES
    from apps.projects.models import OPEN_PROJECT_STATUSES
    from apps.schools import data_gaps, school_status
    from apps.schools.models import SchoolType
    from apps.ssa.current_year import CURRENT_SSA_STATUSES
    from apps.ssa.presentation import SSA_SCORE_GROUPS

    return {
        "page_access": page_access(),
        "country_roles": sorted(scoping.COUNTRY_ROLES),
        "region_roles": sorted(scoping.REGION_ROLES),
        "summary_only_roles": sorted(scoping.SUMMARY_ONLY_ROLES),
        "take_roles": list(data_gaps.FIELD_ROLES),
        "capacity_exempt_roles": sorted(CAPACITY_EXEMPT_ROLES),
        "allow_cd_operational_planning": bool(
            getattr(settings, "ALLOW_CD_OPERATIONAL_PLANNING", False)
        ),
        "school_types": [[value, str(label)] for value, label in SchoolType.choices],
        "trained_types": list(TRAINED_TYPES),
        "visit_types": [str(t) for t in VISIT_TYPES],
        # The directory's own visit count (SchoolDirectoryViewModel.bulk_progress).
        "visit_count_types": ["school_visit", "core_visit", "baseline_ssa_visit"],
        "cluster_session_types": sorted(
            str(t) for t in school_status.CLUSTER_SESSION_TYPES
        ),
        "cluster_meeting_types": [str(t) for t in CLUSTER_MEETING_TYPES],
        "school_training_types": [str(t) for t in SCHOOL_TRAINING_TYPES],
        "cluster_training_types": [str(t) for t in CLUSTER_TRAINING_TYPES],
        "completed_work_statuses": list(COMPLETED_WORK_STATUSES),
        "cluster_credit_statuses": list(CLUSTER_CREDIT_STATUSES),
        "current_ssa_statuses": list(CURRENT_SSA_STATUSES),
        "dead_statuses": sorted(school_status.DEAD_STATUSES),
        "pending_approval_statuses": sorted(school_status.PENDING_APPROVAL_STATUSES),
        "visit_status_states": dict(sorted(school_status._STATUS_STATE.items())),
        "visit_precedence": list(school_status._PRECEDENCE),
        "visit_labels": school_status.VISIT_LABELS,
        "visit_tones": school_status.VISIT_TONES,
        "ssa_interventions": [
            [value, str(label)] for value, label in SsaIntervention.choices
        ],
        "ssa_groups": [list(group) for group in SSA_SCORE_GROUPS],
        "gap_labels": [[key, label] for key, label in data_gaps.LABELS.items()],
        "open_project_statuses": sorted(str(s.value) for s in OPEN_PROJECT_STATUSES),
        "directory_tabs": [[key, label] for key, label, _count in DIRECTORY_TABS],
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write the School Directory's rules for the Go gateway."

    def handle(self, *args, **options):
        path = Path(settings.BASE_DIR) / EXPORT_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"wrote {EXPORT_PATH}")
