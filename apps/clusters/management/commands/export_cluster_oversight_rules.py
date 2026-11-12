"""Write the Cluster Oversight page's rules for the Go gateway.

Go owns District and Cluster management (owner brief, 2026-11-11). It builds
the Cluster Oversight page as the app opens it (/cluster-oversight/, the
Command Center of apps.clusters.workspace) from the vocabularies this command
writes to platform/backend/internal/clusteroversight/rules.json: who may open
the page and each of its doors, its sections, the Command Center's columns
and words, the statuses and activity types each figure counts, the SSA
interventions, the change rule's constants, and what each score is made of.
A change to any of them must be exported again;
apps/clusters/test_cluster_oversight_rules_export.py fails until it is, so
the two can never drift.

The doors are not restated: each role's answer is computed here by the gates
the page itself asks (cluster_management_views.cluster_oversight_view and its
template).

    python manage.py export_cluster_oversight_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/clusteroversight/rules.json")

#: The page as the app's feed opens it, and one of its section addresses.
PAGE_PATH = "/cluster-oversight/"
SECTION_URL_NAME = "cluster_oversight_section"


def doors() -> dict:
    """What each role may do on Cluster Oversight, by the page's own gates."""
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            # require_page_permission("cluster_oversight") and the feed's
            # can_open_url.
            "page": RolePermissionService.can_view_page(user, "cluster_oversight")
            and bool(can_open_url(user, PAGE_PATH)),
            # The Clusters door among the sections (can_open:"/clusters").
            "directory": bool(can_open_url(user, "/clusters")),
            # A figure's link to the cluster profile (can_open:"/clusters/0").
            "cluster": bool(can_open_url(user, "/clusters/0")),
            # workspace.load's may_read_loans.
            "loans": RolePermissionService.can_view_page(user, "loans"),
        }
    return out


def _bands() -> list:
    """scores.band at each of its steps: [floor, label, tone], highest first,
    and the answer where there is no score."""
    from apps.clusters import scores

    return [
        [scores.HIGH, *scores.band(scores.HIGH)],
        [scores.MEDIUM, *scores.band(scores.MEDIUM)],
        [0, *scores.band(0)],
        [None, *scores.band(None)],
    ]


def rules() -> dict:
    from apps.activities.training_names import _TRAINING_TYPES
    from apps.activity_catalogue.models import MappingStatus
    from apps.clusters import outcomes, scores, workspace
    from apps.clusters import profile_insights as insights
    from apps.core.activity_types import (
        CLUSTER_MEETING_TYPES,
        NOT_IN_PLAN_ACTIVITY_STATUSES,
        TRAINING_TYPES,
    )
    from apps.core.enums import SsaIntervention, VerificationStatus
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.mobile_feed.views import NATIVE_PAGES, NOT_PASSED
    from apps.planning.school_planning_badges import (
        AWAITING_VERIFICATION_STATUSES,
        CLUSTER_SESSION_TYPES,
        VERIFIED_STATUSES,
    )
    from apps.schools.lifecycle_models import OPERATING_STATUSES
    from apps.ssa import change_rules
    from apps.ssa.current_year import CURRENT_SSA_STATUSES
    from apps.targets.models import MSCSStatus

    return {
        "doors": doors(),
        # Whether the feed opens a section's own address; while it does not,
        # every address under the page but the page itself is not found.
        "feed_opens_sections": SECTION_URL_NAME in NATIVE_PAGES,
        "not_passed_query_keys": sorted(NOT_PASSED),
        "table_page_size": TABLE_PAGE_SIZE,
        "sections": [
            {
                "key": s.key,
                "label": s.label,
                "description": s.description,
                "url": s.url,
            }
            for s in workspace.SECTIONS
        ],
        "default_section": workspace.DEFAULT_SECTION,
        "command": {
            "title": workspace.COMMAND_TITLE,
            "columns": [[c["label"], c["numeric"]] for c in workspace.COMMAND_COLUMNS],
            "note": workspace.COMMAND_NOTE,
            "empty": workspace.COMMAND_EMPTY,
        },
        "dash": workspace.DASH,
        "missed_in_a_row_alert": insights.MISSED_IN_A_ROW_ALERT,
        "operating_statuses": [str(s) for s in OPERATING_STATUSES],
        "cluster_session_types": [str(t) for t in CLUSTER_SESSION_TYPES],
        "training_session_types": list(scores._TRAINING_SESSIONS),
        "training_types": sorted(str(t) for t in _TRAINING_TYPES),
        "last_activity_types": [
            str(getattr(t, "value", t)) for t in CLUSTER_MEETING_TYPES + TRAINING_TYPES
        ],
        "delivered_statuses": sorted(
            AWAITING_VERIFICATION_STATUSES | VERIFIED_STATUSES
        ),
        "not_in_plan_statuses": list(NOT_IN_PLAN_ACTIVITY_STATUSES),
        "confirmed_status": VerificationStatus.CONFIRMED.value,
        "current_ssa_statuses": list(CURRENT_SSA_STATUSES),
        "funded_loan_statuses": list(outcomes._FUNDED),
        "story_draft_status": MSCSStatus.DRAFT.value,
        "story_approved_status": MSCSStatus.APPROVED.value,
        "published_mapping_status": MappingStatus.PUBLISHED.value,
        "ssa_interventions": [[key.value, key.label] for key in SsaIntervention],
        "change": {
            "min_interval_days": change_rules.MIN_INTERVAL_DAYS,
            "strong_score": change_rules.STRONG_SCORE,
            "improved": change_rules.IMPROVED,
            "declined": change_rules.DECLINED,
            "no_change": change_rules.NO_CHANGE,
            "maintained_strong": change_rules.MAINTAINED_STRONG,
            "maintain_direction": "maintain_strong",
        },
        "scores": {
            key: {
                "title": title,
                "dimensions": [[dim, label, weight] for dim, label, weight in parts],
            }
            for key, (title, parts) in scores.SCORES.items()
        },
        "bands": _bands(),
        "maturity_levels": [[level, label] for level, label in scores.MATURITY_LEVELS],
        "maturity_defaults": dict(scores.MATURITY_DEFAULTS),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write the Cluster Oversight page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
