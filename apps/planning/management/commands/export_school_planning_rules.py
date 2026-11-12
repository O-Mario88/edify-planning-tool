"""Write the school planning rules for the Go gateway.

Go owns District and Cluster management and Activity planning (owner brief,
2026-11-11). Every list where people plan shows, per school, the Visit and
Training planning badges (apps.planning.school_planning_badges), who supports
the school (apps.partners.support_responsibility) and its Next Activity
(apps.planning.planning_support). Go builds those from the vocabularies this
command writes to platform/backend/internal/schoolplanning/rules.json. A
change to any of them must be exported again;
apps/planning/test_school_planning_rules_export.py fails until it is, so the
two can never drift.

    python manage.py export_school_planning_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

EXPORT_PATH = Path("platform/backend/internal/schoolplanning/rules.json")


def rules() -> dict:
    from apps.core.activity_types import (
        CLUSTER_MEETING_TYPES,
        TRAINING_TYPES,
        VISIT_TYPES,
    )
    from apps.partners import support_responsibility
    from apps.planning import fy_policy, planning_support
    from apps.planning import school_planning_badges as badges

    return {
        # Workflow status -> badge bucket.
        "planned_statuses": sorted(badges.PLANNED_STATUSES),
        "awaiting_verification_statuses": sorted(badges.AWAITING_VERIFICATION_STATUSES),
        "verified_statuses": sorted(badges.VERIFIED_STATUSES),
        "needs_replanning_statuses": sorted(badges.NEEDS_REPLANNING_STATUSES),
        # Which badge an activity belongs to.
        "visit_types": [str(t) for t in VISIT_TYPES],
        "training_types": [str(t) for t in TRAINING_TYPES],
        "cluster_meeting_types": [str(t) for t in CLUSTER_MEETING_TYPES],
        "cluster_session_types": list(badges.CLUSTER_SESSION_TYPES),
        # Next Activity's words, by activity type and then by badge.
        "next_nouns": dict(planning_support._NEXT_NOUN),
        "kind_nouns": dict(planning_support._KIND_NOUN),
        # A partner's hold on a school ends when its activity reaches these.
        "closed_handover_activity_statuses": list(
            support_responsibility.CLOSED_ACTIVITY_STATUSES
        ),
        # The planning horizon: the first fiscal year, and whose planning
        # calendar is read.
        "first_fy": fy_policy.FIRST_FY,
        "default_country": fy_policy.default_country(),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write the school planning rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
