"""Write the school-visit save's rules for the Go gateway.

Go makes the first save, scheduling a school visit (docs/migration/27), from
the vocabularies this command writes to
platform/backend/internal/activities/rules.json: who may open the Schedule
drawer and who only asks; the staff visit purposes, their labels and
activity types; the visit-gate, duplicate-visit and closed-school
vocabularies; the SSA plan-alignment and recommendation-engine constants; the
day batch's district and pooling vocabularies; and the calendar's refusal
switch. A change to any of them must be exported again;
apps/activities/test_schedule_visit_rules_export.py fails until it is.

The doors are not restated: each role's answer is computed here by the gates
the save itself asks.

    python manage.py export_schedule_visit_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/activities/rules.json")


def _values(items) -> list[str]:
    return sorted(str(getattr(item, "value", item)) for item in items)


def doors() -> dict:
    from apps.activities.services import ADMIN_IS_NOT_A_PLANNER_MESSAGE
    from apps.core.permissions import RolePermissionService
    from apps.core.rbac import EdifyRole
    from apps.planning.visit_requests import is_requester

    roles = [role.value for role in EdifyRole]
    return {
        "admin_role": EdifyRole.ADMIN.value,
        "admin_refusal": ADMIN_IS_NOT_A_PLANNER_MESSAGE,
        "drawer": sorted(
            role
            for role in roles
            if RolePermissionService.can_open_schedule_drawer(_role_user(role))
        ),
        "requesters": sorted(role for role in roles if is_requester(_role_user(role))),
    }


def rules() -> dict:
    from apps.activities.duplicate_visits import GONE_STATUSES
    from apps.activity_catalogue.models import MappingMode
    from apps.core.enums import ActivityType
    from apps.planning import training_entitlement
    from apps.activities.services import SALESFORCE_TRAINING_KINDS
    from apps.activity_catalogue.services import COSTED_AS
    from apps.core.activity_types import NON_FUNDABLE_ACTIVITY_STATUSES
    from apps.core.calendar_policy import CALENDAR_BLOCKS_REFUSE
    from apps.core.enums import SchoolType, SsaIntervention
    from apps.daily_visit_batches import districts
    from apps.daily_visit_batches.pricing import (
        DAILY_BATCH_ELIGIBLE_TYPES,
        DAY_POOL_EXTRA_TYPES,
    )
    from apps.partners import purposes
    from apps.planning import visit_gate
    from apps.planning.fy_policy import default_country
    from apps.schools.lifecycle_models import CLOSED_STATUSES, OPERATING_STATUSES
    from apps.schools.lifecycle_service import CLOSED_SCHOOL_MESSAGE
    from apps.ssa import plan_alignment, recommendation_engine
    from apps.targets.my_targets import AREA_SOURCES

    from apps.activities.day_off import DAY_OFF_EVENT
    from apps.core.htmx_saved import SAVED_MESSAGE
    from apps.my_plan.past_due_service import OVERDUE_REMINDER_EVENT
    from apps.fund_requests.models import MONEY_MOVED_ADVANCE_STATUSES

    return {
        "doors": doors(),
        "purposes": {
            "staff": [value for value, _label in purposes.STAFF_VISIT_PURPOSES],
            "retired": [value for value, _label in purposes.RETIRED_VISIT_PURPOSES],
            "labels": dict(purposes._LABELS),
            "activity_types": dict(purposes.PURPOSE_ACTIVITY_TYPES),
            "intervention_free": _values(purposes.INTERVENTION_FREE_PURPOSES),
        },
        "salesforce_training_kinds": _values(SALESFORCE_TRAINING_KINDS),
        "costed_as": dict(COSTED_AS),
        "gate": {
            "core_rule_types": list(visit_gate.CORE_RULE_SCHOOL_TYPES),
            "client_rule_types": list(visit_gate.CLIENT_RULE_SCHOOL_TYPES),
            "outreach_only_types": list(visit_gate.OUTREACH_ONLY_SCHOOL_TYPES),
            "outreach_activity_types": list(visit_gate.OUTREACH_ACTIVITY_TYPES),
            "follow_up_visit_types": list(visit_gate.FOLLOW_UP_VISIT_TYPES),
            "ssa_support_visit_types": list(visit_gate.SSA_SUPPORT_VISIT_TYPES),
            "in_school_support_types": list(visit_gate.IN_SCHOOL_SUPPORT_TYPES),
            "companion_purpose": visit_gate.COMPANION_VISIT_PURPOSE,
            "school_type_labels": {
                str(v): str(label) for v, label in SchoolType.choices
            },
        },
        "duplicate_gone_statuses": list(GONE_STATUSES),
        # Activity types some target area counts (ledger_sync._credited_activity_type).
        "ledger_credited_types": sorted(
            {
                str(t)
                for stype, types in AREA_SOURCES.values()
                if stype == "activity"
                for t in (types or ())
            }
        ),
        "closed_statuses": [str(s) for s in CLOSED_STATUSES],
        "operating_statuses": [str(s) for s in OPERATING_STATUSES],
        "closed_school_message": CLOSED_SCHOOL_MESSAGE,
        "calendar_blocks_refuse": bool(CALENDAR_BLOCKS_REFUSE),
        "default_country": default_country(),
        "alignment": {
            "engine_version": plan_alignment.ENGINE_VERSION,
            "priority_depth": plan_alignment.PRIORITY_DEPTH,
            "strong_score": plan_alignment.STRONG_SCORE,
            "critical_score": plan_alignment.CRITICAL_SCORE,
            "current_ssa_fys": plan_alignment.CURRENT_SSA_FYS,
            "collection_kinds": _values(plan_alignment.SSA_COLLECTION_KINDS),
            "not_school_improvement_kinds": _values(
                plan_alignment.NOT_SCHOOL_IMPROVEMENT_KINDS
            ),
        },
        "engine": {
            "weights": [[k, w] for k, w in recommendation_engine._WEIGHTS.items()],
            "min_peers": recommendation_engine.MIN_PEERS,
            "persistence_window": recommendation_engine.PERSISTENCE_WINDOW,
            "weakness_threshold": recommendation_engine.WEAKNESS_THRESHOLD,
            "interventions": [
                [str(v), str(label)] for v, label in SsaIntervention.choices
            ],
        },
        # The second save, moving a visit (docs/migration/29): the notices
        # the existing save settles after commit (a move meeting one is
        # handed on) and the toast saved_in_place() answers with.
        "move": {
            "overdue_event": OVERDUE_REMINDER_EVENT,
            "day_off_event": DAY_OFF_EVENT,
            "saved_message": SAVED_MESSAGE,
        },
        # The third save, cancelling a visit (docs/migration/30): the advance
        # statuses whose money has moved, which the cancel keeps
        # (gateway_money.withdraw_unmoved_advances names the same list).
        "cancel": {
            "money_moved_advance_statuses": [
                str(s) for s in MONEY_MOVED_ADVANCE_STATUSES
            ],
        },
        # The fifth save, an In-school Training and its school visit
        # (docs/migration/32, planning.services.schedule_in_school_training_pair):
        # the two purposes that plan the pair, the one whose visit collects
        # the SSA, the two workflow profiles it resolves, the training shapes
        # a universal course lifts out of the entitlement, and the mapping
        # modes Go takes a course with.
        "pair": {
            "training_purpose": purposes.IN_SCHOOL_TRAINING,
            "collects_ssa_purpose": purposes.IN_SCHOOL_TRAINING_SSA,
            "training_kind": str(ActivityType.IN_SCHOOL_TRAINING),
            "visit_kind": str(ActivityType.SCHOOL_VISIT),
            "training_shapes": sorted(training_entitlement.IN_SCHOOL_TRAINING_SHAPES),
            "fixed_mode": str(MappingMode.FIXED),
            "administrative_mode": str(MappingMode.ADMINISTRATIVE),
        },
        # The seventh save, a cluster Group Training (docs/migration/38,
        # schedule_action_view's cluster branch, planning.services
        # .schedule_cluster_activity, activities.services._create for a
        # cluster, cluster_attendance.set_invited_schools and the cluster
        # recommendation engine).
        "group_training": group_training(),
        "cluster_meeting": cluster_meeting(),
        "batch": {
            "field_roles": _values(districts.FIELD_ROLES),
            "field_role_aliases": _values(districts._FIELD_ROLE_ALIASES),
            "hq_zone": sorted(districts._HQ_ZONE),
            "eligible_types": _values(DAILY_BATCH_ELIGIBLE_TYPES),
            "pool_extra_types": _values(DAY_POOL_EXTRA_TYPES),
            "non_fundable_statuses": _values(NON_FUNDABLE_ACTIVITY_STATUSES),
        },
    }


def group_training() -> dict:
    from apps.activities.services import CLUSTER_PARTICIPANT_ACTIVITY_TYPES
    from apps.activity_catalogue.models import CatalogueActivityType, MappingMode
    from apps.activity_catalogue.services import (
        ACTIVE_SUPPORT_STATUSES,
        COMPLETED_SUPPORT_STATUSES,
    )
    from apps.core.activity_types import TRAINING_TYPES
    from apps.core.enums import ActivityType, ParticipantMode
    from apps.core.scoping import (
        COUNTRY_SCHEDULING_ROLES,
        SUMMARY_ONLY_ROLES,
        VISIT_ONLY_ROLES,
    )
    from apps.planning import visit_gate
    from apps.schools.lifecycle_models import OPERATING_STATUSES

    return {
        "activity_type": str(ActivityType.CLUSTER_TRAINING),
        "participant_types": _values(CLUSTER_PARTICIPANT_ACTIVITY_TYPES),
        "training_types": _values(TRAINING_TYPES),
        "per_school_mode": str(ParticipantMode.PER_SCHOOL),
        "champion_types": [str(t) for t in visit_gate.OWN_TABLE_SCHOOL_TYPES],
        "operating_statuses": [str(s) for s in OPERATING_STATUSES],
        "active_support_statuses": [str(s) for s in ACTIVE_SUPPORT_STATUSES],
        "completed_support_statuses": [str(s) for s in COMPLETED_SUPPORT_STATUSES],
        "admin_catalogue_type": str(CatalogueActivityType.ADMIN),
        "ranked_modes": [str(MappingMode.FIXED), str(MappingMode.MULTIPLE_ALLOWED)],
        "follow_up_mode": str(MappingMode.INHERIT_FROM_SOURCE_ACTIVITY),
        "ungated_modes": [
            str(MappingMode.ADMINISTRATIVE),
            str(MappingMode.SSA_COMPLETION_PREREQUISITE),
        ],
        "country_scheduling_roles": sorted(COUNTRY_SCHEDULING_ROLES),
        "visit_only_roles": sorted(VISIT_ONLY_ROLES),
        "summary_only_roles": sorted(SUMMARY_ONLY_ROLES),
    }


def cluster_meeting() -> dict:
    """The eighth save's vocabulary (docs/migration/49): a cluster meeting."""
    from apps.core.activity_types import CLUSTER_MEETING_TYPES
    from apps.core.enums import ActivityType, MeetingKind

    return {
        "activity_type": str(ActivityType.CLUSTER_MEETING),
        "meeting_types": [str(t) for t in CLUSTER_MEETING_TYPES],
        "meeting_kinds": [str(k) for k in MeetingKind.values],
        "training_kind": str(MeetingKind.TRAINING),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write the school-visit save's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
