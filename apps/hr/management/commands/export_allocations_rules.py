"""Write the allocations engine's rules for Go.

Go reads a person's approved priority contract (apps.hr.accountability
.allocation_priorities, with milestone_progress and target_distribution
.milestone_plan_progress) from what this command writes to
platform/backend/internal/allocations/rules.json: the measurement types that
are rates; the counting bases of each unit family; the statuses that are
planned output and completed work; the school types each rule family
reaches; and the achievement bands and states classify_achievement names a
milestone's progress by. A change to any of them must be exported again;
apps/hr/test_allocations_rules_export.py fails until it is.

    python manage.py export_allocations_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

EXPORT_PATH = Path("platform/backend/internal/allocations/rules.json")


def rules() -> dict:
    from apps.core.activity_types import COMPLETED_WORK_STATUSES
    from apps.hr import milestone_progress, target_distribution

    return {
        "rate_measurement_types": sorted(milestone_progress.RATE_MEASUREMENT_TYPES),
        "school_bases": sorted(milestone_progress.SCHOOL_BASES),
        "teacher_bases": sorted(milestone_progress.TEACHER_BASES),
        "leader_bases": sorted(milestone_progress.LEADER_BASES),
        "planned_output_statuses": list(target_distribution.PLANNED_OUTPUT_STATUSES),
        "completed_work_statuses": list(COMPLETED_WORK_STATUSES),
        "school_type_families": {
            "core": list(target_distribution.CORE_FAMILY),
            "client": list(target_distribution.CLIENT_FAMILY),
        },
        # classify_achievement's bands, lowest first, and its other states.
        "achievement_bands": [
            {
                "bound": str(bound),
                "inclusive": inclusive,
                "key": key,
                "label": label,
                "tone": tone,
            }
            for bound, inclusive, key, label, tone in target_distribution.ACHIEVEMENT_BANDS
        ],
        "far_exceeded": list(target_distribution.FAR_EXCEEDED),
        "non_scoring_states": {
            key: list(value)
            for key, value in target_distribution.NON_SCORING_STATES.items()
        },
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the allocations engine's rules for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
