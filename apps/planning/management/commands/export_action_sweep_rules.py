"""Write the delegated-action sweep's rules for Go.

Go runs the hourly `school_action_sweep` job
(apps.planning.action_service.resolve_due_actions and mark_overdue_actions)
from what this command writes to
platform/backend/internal/actionsweep/rules.json: which issue types the
system may settle and through which detector, the states an action is active
in and is flagged overdue from, the statuses that count as verified work, the
visit and training types, the SSA score bands, and what send_action asks
(each issue's action, route and reason, the due days by severity and the
priority each severity sends at). A change to any of them
must be exported again; apps/planning/test_action_sweep_rules_export.py fails
until it is.

    python manage.py export_action_sweep_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

EXPORT_PATH = Path("platform/backend/internal/actionsweep/rules.json")


def _bands() -> list[list]:
    """ssa_score_band's label at each of its floors, highest first."""
    from apps.core.enums import ssa_score_band

    return [[floor, ssa_score_band(floor)[0]] for floor in (10.0, 8.0, 6.0, 5.0, 0.0)]


def rules() -> dict:
    from apps.planning import action_service as svc
    from apps.planning.action_models import ACTIVE_STATES, ActionState
    from apps.planning.country_oversight.followups import SCHOOL_GAP_FIGURE
    from apps.planning.urgent_attention import _TRAINING_TYPES, _VISIT_TYPES
    from apps.targets.my_targets import IA_VERIFIED_STATUSES

    return {
        "system_verifiable": sorted(svc.SYSTEM_VERIFIABLE),
        "oversight_risk_keys": sorted(svc.OVERSIGHT_RISK_KEYS),
        "partner_oversight_risk_keys": sorted(svc.PARTNER_OVERSIGHT_RISK_KEYS),
        "core_oversight_risk_keys": sorted(svc.CORE_OVERSIGHT_RISK_KEYS),
        "planning_gap_keys": sorted(svc.PLANNING_GAP_KEYS),
        "school_gap_figure": dict(sorted(SCHOOL_GAP_FIGURE.items())),
        "active_states": sorted(str(s) for s in ACTIVE_STATES),
        "overdue_from_states": sorted(str(s) for s in svc.OVERDUE_FROM_STATES),
        "resolved_state": str(ActionState.RESOLVED),
        "overdue_state": str(ActionState.OVERDUE),
        "oversight_key_prefixes": [
            svc.OVERSIGHT_KEY_PREFIX,
            svc.PARTNER_OVERSIGHT_KEY_PREFIX,
        ],
        "ia_verified_statuses": sorted(IA_VERIFIED_STATUSES),
        "visit_types": sorted(_VISIT_TYPES),
        "training_types": sorted(_TRAINING_TYPES),
        "ssa_bands": _bands(),
        "playbook": {
            key: dict(sorted(entry.items()))
            for key, entry in sorted(svc.ISSUE_PLAYBOOK.items())
        },
        "default_due_days": dict(sorted(svc.DEFAULT_DUE_DAYS.items())),
        "priority_for": {
            severity: str(svc._priority_for(severity))
            for severity in ("critical", "high", "warning", "normal")
        },
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the delegated-action sweep's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"wrote {EXPORT_PATH}")
