"""Write the target engine's rules for Go.

Go computes a person's targets, validated achievements, weighted share and
pace-aware status (apps.targets.my_targets, team_targets and fy_calendar) from
what this command writes to platform/backend/internal/targets/rules.json:
which performance metric feeds which target area; the official areas (a
missing one is repaired on read, which Go hands on); which StaffTargetProfile
columns each area's annual fallback adds; the review stages that are not yet
an agreement; the pace bands; the quarter and month names. A change to any of
them must be exported again; apps/targets/test_targets_rules_export.py fails
until it is.

    python manage.py export_targets_rules
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from django.core.management.base import BaseCommand

EXPORT_PATH = Path("platform/backend/internal/targets/rules.json")

#: priority_target_areas_for_users excludes these stages: not yet agreed.
UNAGREED_STAGES = ("not_started", "priorities_draft", "priorities_manager_review")


def _fallback_columns() -> dict[str, list[str]]:
    """Each area's ANNUAL_FALLBACK read back as the profile columns it adds:
    every column is given its own power of two and the sum is decoded, so the
    export follows the lambdas rather than restating them."""
    from apps.accounts.models import StaffTargetProfile
    from apps.targets.my_targets import ANNUAL_FALLBACK

    columns = sorted(
        f.name
        for f in StaffTargetProfile._meta.get_fields()
        if getattr(f, "get_internal_type", lambda: "")() == "IntegerField"
        and f.name.endswith("_target")
    )
    profile = SimpleNamespace(**{name: 1 << i for i, name in enumerate(columns)})
    out = {}
    for area, fallback in ANNUAL_FALLBACK.items():
        total = fallback(profile)
        out[area] = [name for i, name in enumerate(columns) if total & (1 << i)]
    return out


def rules() -> dict:
    from apps.hr.models import ReviewType
    from apps.targets import team_targets
    from apps.targets.fy_calendar import MONTH_LABELS, QUARTERS
    from apps.targets.my_targets import (
        OFFICIAL_TARGET_AREAS,
        PERFORMANCE_METRIC_TO_AREA,
    )

    return {
        "metric_to_area": dict(PERFORMANCE_METRIC_TO_AREA),
        "official_areas": [key for key, *_ in OFFICIAL_TARGET_AREAS],
        "annual_fallback": _fallback_columns(),
        "agreement_review_type": ReviewType.ANNUAL_PRIORITIES.value,
        "unagreed_stages": list(UNAGREED_STAGES),
        "bands": {
            "on_track": team_targets.TEAM_ON_TRACK_BAND,
            "slight": team_targets.TEAM_SLIGHT_BAND,
            "high_risk": team_targets.TEAM_HIGH_RISK_BAND,
        },
        "quarters": list(QUARTERS),
        "month_labels": list(MONTH_LABELS),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the target engine's rules for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
