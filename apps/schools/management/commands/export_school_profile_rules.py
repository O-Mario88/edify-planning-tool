"""Write the School Profile's rules for the Go gateway.

Go owns School Profiles (owner brief, 2026-11-11: "School Directory and
School Profiles"). It reads the vocabularies a profile is built from — the
labels of a school's type, readiness and SSA statuses, which activities hold
a school's support visit of the year, the visit lock's words, who may use
each of the header's doors — from
platform/backend/internal/schoolprofile/rules.json, which this command writes
from the modules that define them. A change to any of them must be exported
again; apps/schools/test_school_profile_rules_export.py fails until it is, so
the two can never drift.

The doors are not restated: each role's answer is computed here by the
existing gates (RolePermissionService, has_permission, may_transfer_school,
the SSA entry roles).

    python manage.py export_school_profile_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/schoolprofile/rules.json")


def doors() -> dict:
    """What each role may do from a school's profile, by the existing gates."""
    from apps.core.navigation import get_user_role_slug
    from apps.core.permissions import (
        RolePermissionService,
        can_open_url,
        has_permission,
    )
    from apps.core.rbac import EdifyRole
    from apps.schools import data_gaps
    from apps.schools.ownership_transfer import may_transfer_school
    from apps.ssa.creation import may_enter_role

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            "profile": RolePermissionService.can_view_page(user, "school_profile"),
            "schedule": RolePermissionService.can_open_schedule_drawer(user),
            "assign_partner": RolePermissionService.can_assign_to_partner(user),
            "transfer_owner": may_transfer_school(user),
            "assign_project": has_permission(user, "project.assignSchool"),
            "enter_ssa": may_enter_role(user),
            "delete_school": get_user_role_slug(user) == "ADMIN",
            # data_gaps.may_take also asks for a staff profile; Go asks that
            # of the principal.
            "take": role.value in data_gaps.FIELD_ROLES,
            # Whether a cluster's or a district's name opens its profile
            # (school_links._may_open).
            "open_cluster": bool(can_open_url(user, "/clusters/0")),
            "open_district": bool(can_open_url(user, "/districts/0")),
            # Whether a person's name opens their profile, and a project's
            # its monitoring page (profile_views.profile_context).
            "open_staff": RolePermissionService.can_view_page(user, "staff"),
            "open_projects": RolePermissionService.can_view_page(
                user, "project_monitoring"
            ),
            # The Overview's loans strip shows to a reader of the register.
            "loans": RolePermissionService.can_view_page(user, "loans"),
        }
    return out


def rules() -> dict:
    from apps.activities.services import CLIENT_VISIT_LEGACY_TYPES
    from apps.core.enums import PlanningReadiness, SchoolType, SsaIntervention
    from apps.core_schools.lifecycle import CORE_LIFECYCLE_TYPES
    from apps.partners.models import PartnerAssignment
    from apps.planning import visit_gate as gate
    from apps.planning.country_oversight.rules import (
        DATA_COLLECTION_PURPOSES,
        DATA_COLLECTION_TYPES,
    )
    from apps.projects.models import GENERAL_INTERVENTION
    from apps.schools.lifecycle_models import CLOSED_STATUSES
    from apps.schools.lifecycle_service import CLOSED_SCHOOL_MESSAGE
    from apps.ssa import creation
    from apps.ssa import services as ssa_services
    from apps.ssa.current_year import CURRENT_SSA_STATUSES
    from apps.ssa.models import SsaRecord

    return {
        "doors": doors(),
        "school_types": dict(SchoolType.choices),
        "readiness": dict(PlanningReadiness.choices),
        "ssa_statuses": dict(SsaRecord._meta.get_field("verification_status").choices),
        "ssa_interventions": dict(SsaIntervention.choices),
        "ssa_holding_statuses": list(creation.HOLDING_STATUSES),
        "ssa_current_statuses": list(CURRENT_SSA_STATUSES),
        # creation.source_label, by the record's own verification_source.
        "ssa_sources": {
            source: creation.source_label(SsaRecord(verification_source=source))
            for source in (
                ssa_services.SOURCE_STAFF_KEYED,
                ssa_services.SOURCE_IA_KEYED,
                ssa_services.SOURCE_FILE_IMPORT,
                ssa_services.SOURCE_PARTNER,
            )
        },
        "ssa_source_staff_keyed": ssa_services.SOURCE_STAFF_KEYED,
        "ssa_source_on_visit": creation.source_label(
            SsaRecord(
                verification_source=ssa_services.SOURCE_STAFF_KEYED,
                source_activity_id="x",
            )
        ),
        "ssa_source_other": creation.source_label(SsaRecord()),
        # The school types whose profile has a Core School tab.
        "core_lifecycle_types": list(CORE_LIFECYCLE_TYPES),
        "closed_statuses": list(CLOSED_STATUSES),
        "closed_school_message": CLOSED_SCHOOL_MESSAGE,
        "engine": engine_rules(),
        "gate": {
            "client_rule_types": list(gate.CLIENT_RULE_SCHOOL_TYPES),
            "core_rule_types": list(gate.CORE_RULE_SCHOOL_TYPES),
            "one_commitment_types": list(gate.ONE_COMMITMENT_SCHOOL_TYPES),
            "outreach_only_types": list(gate.OUTREACH_ONLY_SCHOOL_TYPES),
            "staff_visit_cap": gate.CLIENT_STAFF_VISIT_CAP,
            "not_live_statuses": [
                *gate.DEAD_STATUSES,
                *gate.NOT_YET_PLANNED_STATUSES,
            ],
            "companion_purpose": gate.COMPANION_VISIT_PURPOSE,
            "follow_up_visit_types": list(gate.FOLLOW_UP_VISIT_TYPES),
            "ssa_support_visit_types": list(gate.SSA_SUPPORT_VISIT_TYPES),
            "in_school_support_types": list(gate.IN_SCHOOL_SUPPORT_TYPES),
            "client_visit_legacy_types": list(CLIENT_VISIT_LEGACY_TYPES),
            "unscheduled_handover_statuses": list(
                PartnerAssignment.UNSCHEDULED_STATUSES
            ),
            "data_collection_types": list(DATA_COLLECTION_TYPES),
            "data_collection_purposes": list(DATA_COLLECTION_PURPOSES),
            "general_intervention": GENERAL_INTERVENTION,
            "lock_labels": dict(gate.LOCK_LABELS),
        },
    }


def engine_rules() -> dict:
    """What the profile engine (apps.analytics.profile_intelligence and
    profile_records) reads: the statuses it counts work and hand-overs by,
    the words and tones of an SSA change, the story statuses, and the
    intervention abbreviations a strip's figures use."""
    from apps.analytics import ia_workflow
    from apps.analytics import profile_intelligence as engine
    from apps.core.enums import SchoolType, SsaIntervention
    from apps.core.interventions import INTERVENTION_ABBREVIATIONS
    from apps.planning.country_oversight import rules
    from apps.core.metrics.payload import HELPER_FIGURE_CHARS
    from apps.partners.models import PartnerAssignment
    from apps.ssa import change_rules
    from apps.targets.models import MSCSStatus

    return {
        "completed_work_statuses": list(engine.COMPLETED_WORK_STATUSES),
        "not_in_plan_statuses": list(engine.NOT_IN_PLAN_ACTIVITY_STATUSES),
        "not_started_statuses": list(engine.NOT_STARTED_ACTIVITY_STATUSES),
        "change_labels": dict(engine._CHANGE_LABELS),
        "change_tones": dict(engine._CHANGE_TONES),
        "fallback_rule_label": change_rules.FALLBACK_LABEL,
        "min_interval_days": change_rules.MIN_INTERVAL_DAYS,
        "strong_score": change_rules.STRONG_SCORE,
        "handover_released_statuses": list(PartnerAssignment.RELEASED_STATUSES),
        "handover_completed_status": PartnerAssignment.STATUS_COMPLETED,
        "story_statuses": {
            "draft": MSCSStatus.DRAFT.value,
            "approved": MSCSStatus.APPROVED.value,
            "waiting": [MSCSStatus.SUBMITTED.value, MSCSStatus.RETURNED.value],
        },
        "intervention_abbreviations": dict(INTERVENTION_ABBREVIATIONS),
        "intervention_order": [value for value, _label in SsaIntervention.choices],
        "helper_figure_chars": HELPER_FIGURE_CHARS,
        "visit_types": list(engine._VISITS),
        "training_types": list(engine._TRAININGS),
        "meeting_types": list(engine._MEETINGS),
        "intervention_method": engine.INTERVENTION_METHOD,
        # The SSA tab (ia_workflow.school_progress and the matrix).
        "ssa_target": engine.SSA_TARGET,
        "rule_sentence": change_rules.RULE_SENTENCE,
        "state_tones": dict(ia_workflow.STATE_TONES),
        "verified_activity_statuses": list(ia_workflow.VERIFIED_ACTIVITY_STATUSES),
        "school_pairs_shown": ia_workflow.SCHOOL_PAIRS_SHOWN,
        # What each school type is due in a year, and whether it is assessed
        # (planning.country_oversight.rules); "" is a school with no type.
        "requirements": {
            school_type: {
                "visits": rules.requirement_for(school_type).visits,
                "trainings": rules.requirement_for(school_type).trainings,
                "takes_ssa": rules.takes_ssa(school_type),
            }
            for school_type in ["", *(value for value, _ in SchoolType.choices)]
        },
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write the School Profile's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
