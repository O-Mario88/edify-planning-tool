"""Write Core Schools Planning's page rules for Go.

Go builds /core-schools (apps.frontend.views.core_schools_views
.core_schools_view, its three lazily drawn tabs, the right-hand panel and the
programme tables) from what this command writes to
platform/backend/internal/coreschools/rules.json: which roles open the page
and the doors each is given (assign to a partner, schedule, add to a project,
open a cluster, open Core School Oversight); the page sizes; the SSA
interventions, school types and programme types and their names; the
Assessment cell's ranking and words; the partner hand-over states; the plan
states that end a package; the slot, activity and session states each figure
counts; the visit and training activity types with their names and every
activity state's name; the ordinals of the package's slots; and the roles
that may plan at any school. A change to any of them must be exported again;
apps/core_schools/test_core_schools_rules_export.py fails until it is.

    python manage.py export_core_schools_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

EXPORT_PATH = Path("platform/backend/internal/coreschools/rules.json")
PAGE_KEY = "core_schools"


def rules() -> dict:
    from apps.activities.models import Activity
    from apps.core.activity_types import TRAINING_TYPES, VISIT_TYPES
    from apps.core.enums import SchoolType, SsaIntervention
    from apps.core.permissions import (
        RolePermissionService,
        can_open_url,
        has_permission,
    )
    from apps.core.rbac import EdifyRole
    from apps.core.scoping import COUNTRY_SCHEDULING_ROLES
    from apps.core_schools import package_year
    from apps.core_schools.core_planning_services import (
        CORE_SLOT_ORDINALS,
        IMPACT_ACTIVE_STATUSES,
        IMPACT_COMPLETED_STATUSES,
        RECOMMENDATION_DONE_STATUSES,
    )
    from apps.core_schools.lifecycle import WORK_EXCLUDED_STATUSES
    from apps.core_schools.services import (
        CORE_PLAN_CLOSED_STATUSES,
        CORE_SLOT_DONE_WITH_LEGACY,
    )
    from apps.frontend.views.core_schools_views import (
        CORE_PAGE_SIZE_DEFAULT,
        CORE_PAGE_SIZES,
    )
    from apps.partners.models import PartnerAssignment
    from apps.planning.visit_gate import (
        OUTREACH_ONLY_SCHOOL_TYPES,
        PROGRAMME_SCHOOL_TYPES,
    )
    from apps.schools.management.commands.export_school_directory_rules import (
        _role_user,
    )
    from apps.schools.programme_schools import type_options
    from apps.ssa import pl_confirmation

    roles = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        if not RolePermissionService.can_view_page(user, PAGE_KEY):
            continue
        roles[role.value] = {
            "assign_partner": RolePermissionService.can_assign_to_partner(user),
            "bulk_schedule": RolePermissionService.can_schedule_activity(user),
            "assign_project": has_permission(user, "project.assignSchool"),
            "open_clusters": bool(can_open_url(user, "/clusters/0")),
            "open_oversight": bool(can_open_url(user, "/core-schools-oversight/")),
        }
    activity = Activity._meta
    return {
        "roles": roles,
        "page_sizes": list(CORE_PAGE_SIZES),
        "page_size_default": CORE_PAGE_SIZE_DEFAULT,
        "interventions": [list(c) for c in SsaIntervention.choices],
        "school_types": [list(c) for c in SchoolType.choices],
        "programme_types": [list(t) for t in type_options()],
        "programme_school_types": list(PROGRAMME_SCHOOL_TYPES),
        "outreach_only_types": list(OUTREACH_ONLY_SCHOOL_TYPES),
        # core_assessment_cells: the year's records ranked, each state's word.
        "assessment_rank": sorted(
            pl_confirmation._RANK, key=lambda k: pl_confirmation._RANK[k]
        ),
        "assessment_words": {
            status: cell[0] for status, cell in pl_confirmation._CELLS.items()
        },
        "assessment_missing": pl_confirmation._MISSING[0],
        "partner_returned_to_staff": PartnerAssignment.STATUS_RETURNED_TO_STAFF,
        "partner_released": list(PartnerAssignment.RELEASED_STATUSES),
        "partner_unscheduled": list(PartnerAssignment.UNSCHEDULED_STATUSES),
        "slot_done_with_legacy": sorted(CORE_SLOT_DONE_WITH_LEGACY),
        # The page's own read heals packages: a plan of these states does not
        # carry a school's package forward.
        "plan_closed_statuses": sorted(CORE_PLAN_CLOSED_STATUSES),
        "recommendation_done": sorted(RECOMMENDATION_DONE_STATUSES),
        "impact_active": list(IMPACT_ACTIVE_STATUSES),
        "impact_completed": list(IMPACT_COMPLETED_STATUSES),
        "work_excluded": list(WORK_EXCLUDED_STATUSES),
        "cluster_training_types": sorted(package_year.CLUSTER_TRAINING_TYPES),
        "session_live_statuses": sorted(package_year.SESSION_LIVE_STATUSES),
        "visit_types": list(VISIT_TYPES),
        "training_types": list(TRAINING_TYPES),
        "activity_type_labels": dict(activity.get_field("activity_type").choices),
        "activity_status_labels": dict(activity.get_field("status").choices),
        "slot_ordinals": {str(k): v for k, v in CORE_SLOT_ORDINALS.items()},
        # may_plan_school: the roles that may plan at any school.
        "country_scheduling_roles": sorted(COUNTRY_SCHEDULING_ROLES),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write Core Schools Planning's page rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"wrote {EXPORT_PATH}")
