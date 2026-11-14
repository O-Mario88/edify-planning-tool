"""Write the Smart Route Planner's rules for the Go gateway.

Go plans a field day (platform/backend/internal/routeplan) from what this
command writes to platform/backend/internal/routeplan/rules.json: the
working day, lunch, visit length, buffer, planning speed and nearby radius of
the existing route engine (apps.routes.engine, apps.routes.location); which
activity types are school visits and which statuses are done or no longer
live work (apps.core.activity_types, apps.activities.completion_columns,
apps.planning.visit_gate); a closed school and each school type's words; and which roles may open the planner (My Plan's
door) and a school's profile. A change to any of them must be exported
again; apps/routes/test_route_rules_export.py fails until it is.

    python manage.py export_route_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/routeplan/rules.json")

#: The planner lives under My Plan: whoever opens My Plan opens it.
PLANNER_DOOR = "/my-plan"


def rules() -> dict:
    from apps.activities import completion_columns
    from apps.core import activity_types
    from apps.core.enums import SchoolType
    from apps.core.permissions import can_open_url
    from apps.core.rbac import EdifyRole
    from apps.planning import visit_gate as gate
    from apps.routes import engine, location
    from apps.schools.lifecycle_models import CLOSED_STATUSES

    def roles_opening(path: str) -> list[str]:
        return sorted(
            r.value for r in EdifyRole if can_open_url(_role_user(r.value), path)
        )

    return {
        "day": {
            "start": "08:00",
            "work_minutes": engine.WORK_MINUTES,
            "lunch_minutes": engine.LUNCH_MINUTES,
            "available_minutes": engine.AVAILABLE_MINUTES,
            "visit_minutes": engine.VISIT_MINUTES_PER_SCHOOL,
            "buffer_minutes": engine.BUFFER_MINUTES,
        },
        "nearby_radius_km": engine.COORD_RADIUS_KM,
        "planning_speed_kmh": location.AVG_SPEED_KMH,
        "visit_types": sorted(activity_types.VISIT_TYPES),
        "completed_statuses": sorted(completion_columns.OFFICER_COMPLETED_STATUSES),
        "not_live_statuses": sorted(
            {*gate.DEAD_STATUSES, *gate.NOT_YET_PLANNED_STATUSES}
        ),
        "closed_statuses": sorted(str(x) for x in CLOSED_STATUSES),
        "school_types": {str(k): str(v) for k, v in SchoolType.choices},
        "planner_roles": roles_opening(PLANNER_DOOR),
        "school_profile_roles": roles_opening("/schools/0"),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Smart Route Planner's rules for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
