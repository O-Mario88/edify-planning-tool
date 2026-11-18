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
    from apps.core.rbac import EdifyRole, Permission
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
            # Whether the Participation tab's rows may offer Edit, Complete,
            # Reschedule and Cancel at all (profile_activities._decorate).
            "my_plan": RolePermissionService.can_view_page(user, "my_plan"),
            # A Core school's Schedule and Assign to Partner open the Core
            # Schools drawers for a reader of that page.
            "core_schools": RolePermissionService.can_view_page(user, "core_schools"),
            # Business Transformation on Details: a loan's figures, and the
            # Plan verification door.
            "bt_sensitive": has_permission(
                user, Permission.BUSINESS_TRANSFORMATION_SENSITIVE_VIEW.value
            ),
            "bt_manage": has_permission(
                user, Permission.BUSINESS_TRANSFORMATION_CASE_MANAGE.value
            ),
        }
    return out


def business_transformation_rules() -> dict:
    """What a school's Business Transformation panel and the Overview's loans
    strip read (business_transformation.services.school_profile_context,
    scoped_cases, scoped_loans, lending_impact.scoped_impact_loans,
    clusters.outcomes.loans_by_cluster): the role sets the loan register is
    scoped by, the case statuses that are open, and every label shown."""
    from apps.business_transformation import lending_impact
    from apps.business_transformation import models as bt
    from apps.business_transformation import services as bts
    from apps.clusters.outcomes import _FUNDED

    return {
        "uganda_wide_roles": sorted(bts.UGANDA_WIDE_ROLES),
        "mfi_roles": sorted(bts.MFI_ROLES),
        "impact_country_roles": sorted(lending_impact.COUNTRY_ROLES),
        "impact_country_bound_roles": sorted(lending_impact.COUNTRY_BOUND_ROLES),
        "open_case_statuses": [str(s) for s in bt.OPEN_CASE_STATUSES],
        "funded_loan_statuses": list(_FUNDED),
        "case_statuses": dict(bt.CaseStatus.choices),
        "recommendation_kinds": dict(bt.RecommendationKind.choices),
        "loan_statuses": dict(bt.LoanStatus.choices),
        "salesforce_statuses": dict(bt.SalesforceStatus.choices),
        "impact_statuses": dict(bt.LoanImpactStatus.choices),
        "requirement_statuses": dict(bt.VerificationRequirementStatus.choices),
        "validation_statuses": dict(bt.IAValidationStatus.choices),
        "compliance_statuses": dict(bt.ComplianceStatus.choices),
    }


def core_tab_rules() -> dict:
    """What the Core School tab reads (apps.core_schools.intelligence and
    champion_services, the SSA recommendations): its words, the statuses it
    counts by, and who may act on a school."""
    from apps.core.activity_types import TRAINING_TYPES
    from apps.core.scoping import COUNTRY_WRITE_ROLES
    from apps.core_schools import intelligence
    from apps.core_schools.services import (
        CORE_SLOT_DONE_STATUSES,
        PACKAGE_WORK_KINDS,
        PACKAGE_WORK_SLOTS,
    )
    from apps.partners.models import PartnerAssignment
    from apps.planning import school_planning_badges as badges
    from apps.ssa.recommendation_models import LIVE_STATES, RecommendationState

    return {
        "trajectory_labels": dict(intelligence.TRAJECTORY_LABELS),
        "champion": {
            "champion": intelligence.CHAMPION,
            "potential": intelligence.POTENTIAL,
            "progressing": intelligence.PROGRESSING,
            "not_yet": intelligence.NOT_YET,
            "insufficient": intelligence.INSUFFICIENT,
            "latest_avg": intelligence.CHAMPION_LATEST_AVG,
            "stored_champion": ["Champion", "Approved Champion"],
        },
        "slot_done_statuses": sorted(CORE_SLOT_DONE_STATUSES),
        "package_work_kinds": list(PACKAGE_WORK_KINDS),
        "package_work_slots": PACKAGE_WORK_SLOTS,
        "handover_unscheduled": list(PartnerAssignment.UNSCHEDULED_STATUSES),
        "handover_scheduled": [
            PartnerAssignment.STATUS_SCHEDULED,
            PartnerAssignment.STATUS_PARTNER_SCHEDULED,
        ],
        "handover_completed": PartnerAssignment.STATUS_COMPLETED,
        "delivered_statuses": sorted(
            badges.AWAITING_VERIFICATION_STATUSES | badges.VERIFIED_STATUSES
        ),
        "cluster_session_types": list(badges.CLUSTER_SESSION_TYPES),
        "training_types": [str(t) for t in TRAINING_TYPES],
        "country_write_roles": sorted(COUNTRY_WRITE_ROLES),
        "recommendation_states": dict(RecommendationState.choices),
        "recommendation_live_states": [str(s) for s in LIVE_STATES],
        "recommendation_shown_states": [
            *(str(s) for s in LIVE_STATES),
            str(RecommendationState.PLANNED),
        ],
    }


def participation_rules() -> dict:
    """What the Participation tab reads: the planned and completed
    activities' statuses and words (apps.activities.profile_activities and
    editing), who may run work (apps.activities.services), and a partner
    hand-over's next step (apps.planning.partner_oversight_service)."""
    from apps.activities import editing
    from apps.activities import profile_activities as acts
    from apps.core.enums import ActivityType, MeetingKind
    from apps.core.rbac import EdifyRole
    from apps.core.scoping import COUNTRY_SCHEDULING_ROLES
    from apps.partners.models import PartnerAssignment
    from apps.partners.support_responsibility import left_partner_q
    from apps.planning import partner_oversight_service as oversight
    from apps.planning import school_planning_badges as badges

    from django.db.models import Q

    # left_partner_q, exported as its two arms; a change to it stops the
    # export rather than drifting from Go.
    left_statuses = ("returned", "cancelled")
    returned = "returned_to_staff"
    expected = Q(status__in=left_statuses) | (
        Q(status=returned) & Q(resolved_at__isnull=False)
    )
    if left_partner_q() != expected:
        raise ValueError(
            "left_partner_q changed: update the Participation export and Go."
        )
    return {
        "open_statuses": sorted(acts.OPEN_STATUSES),
        "delivered_statuses": sorted(acts.DELIVERED_STATUSES),
        "planned_statuses": sorted(badges.PLANNED_STATUSES),
        "needs_replanning_statuses": sorted(badges.NEEDS_REPLANNING_STATUSES),
        "verified_statuses": sorted(badges.VERIFIED_STATUSES),
        "still_completing_statuses": sorted(acts._STILL_COMPLETING),
        "editable_statuses": sorted(editing.EDITABLE_STATUSES),
        "begun_statuses": sorted(editing.BEGUN_STATUSES),
        "executed_statuses": sorted(editing.EXECUTED_STATUSES),
        "page_size": acts.PAGE_SIZE,
        "activity_types": dict(ActivityType.choices),
        "meeting_kinds": dict(MeetingKind.choices),
        "country_scheduling_roles": sorted(COUNTRY_SCHEDULING_ROLES),
        "country_director": EdifyRole.COUNTRY_DIRECTOR.value,
        "handover_left_statuses": list(left_statuses),
        "handover_returned_status": returned,
        "handover_unscheduled_statuses": list(PartnerAssignment.UNSCHEDULED_STATUSES),
        "oversight_complete_statuses": list(oversight._COMPLETE_STATUSES),
        "oversight_awaiting_ia_statuses": list(oversight._AWAITING_IA_STATUSES),
        "oversight_evidence_review_statuses": list(oversight._EVIDENCE_REVIEW_STATUSES),
    }


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
    from apps.schools.lifecycle_models import (
        CLOSED_STATUSES,
        ClosureReason,
        SchoolOperationalStatus,
    )
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
        # A closed school's banner (pages/schools/detail.html).
        "operational_statuses": dict(SchoolOperationalStatus.choices),
        "closure_reasons": dict(ClosureReason.choices),
        "engine": engine_rules(),
        "participation": participation_rules(),
        "core_tab": core_tab_rules(),
        "business_transformation": business_transformation_rules(),
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
            "core": core_package_rules(),
        },
    }


def core_package_rules() -> dict:
    """What a Core school's 2 + 2 package split reads
    (apps.core_schools.package_split and package_credit) and the visit
    gate's words for it."""
    from apps.core_schools import core_planning_services as planning
    from apps.core_schools import package_credit as credit
    from apps.core_schools import package_year
    from apps.core_schools.services import CORE_PLAN_CLOSED_STATUSES
    from apps.partners.purposes import PURPOSE_ACTIVITY_TYPES
    from apps.planning import visit_gate as gate

    return {
        "side_cap": gate.CORE_STAFF_VISIT_CAP,
        "caps": {
            "staff_visits": gate.CORE_STAFF_VISIT_CAP,
            "partner_visits": gate.CORE_PARTNER_VISIT_CAP,
            "staff_trainings": gate.CORE_STAFF_TRAINING_CAP,
            "partner_trainings": gate.CORE_PARTNER_TRAINING_CAP,
        },
        "package_visit_types": sorted(credit.PACKAGE_VISIT_TYPES),
        "package_training_types": sorted(credit.PACKAGE_TRAINING_TYPES),
        "data_collection_visit_types": sorted(credit.DATA_COLLECTION_VISIT_TYPES),
        "data_collection_visit_purposes": sorted(credit.DATA_COLLECTION_VISIT_PURPOSES),
        "outreach_visit_types": sorted(credit.OUTREACH_VISIT_TYPES),
        "outreach_visit_purposes": sorted(credit.OUTREACH_VISIT_PURPOSES),
        "non_package_visit_purposes": sorted(credit.NON_PACKAGE_VISIT_PURPOSES),
        "uncredited_statuses": sorted(credit.UNCREDITED_STATUSES),
        "cluster_training_types": sorted(package_year.CLUSTER_TRAINING_TYPES),
        "plan_closed_statuses": sorted(CORE_PLAN_CLOSED_STATUSES),
        "purpose_activity_types": dict(PURPOSE_ACTIVITY_TYPES),
        "lock_package_complete": gate.LOCK_PACKAGE_COMPLETE,
        # A package slot's state (core_planning_services.slot_state): taken
        # once allocated or handed over, done once delivered.
        "slot_allocated_statuses": sorted(planning.CORE_ALLOCATED_SLOT_STATUSES),
        "slot_handed_over_status": "assigned",
        "slot_done_statuses": sorted(planning.CORE_SLOT_DONE_LOWER),
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
        # The profiles of a set of schools (a district, a sub-region, the
        # country, a cluster, a person, a partner): profile_views and the
        # engine's sections, levels, rankings and periods.
        "scope": scope_rules(),
    }


def scope_rules() -> dict:
    """What a profile of many schools reads (frontend.views.profile_views
    and apps.analytics.profile_intelligence beyond one school)."""
    from apps.analytics import profile_intelligence as engine
    from apps.analytics import profile_records
    from apps.core.enums import SchoolType
    from apps.frontend.views import profile_views
    from apps.schools.lifecycle_models import OPERATING_STATUSES

    return {
        "operating_statuses": [str(s.value) for s in OPERATING_STATUSES],
        "sections": [list(pair) for pair in profile_views.SECTIONS],
        "sections_of": {k: list(v) for k, v in profile_views.SECTIONS_OF.items()},
        "team_label": profile_views._TEAM_LABEL,
        "levels_of": {k: list(v) for k, v in engine.LEVELS_OF.items()},
        "level_labels": dict(engine._LEVEL_LABELS),
        "period_options": [list(pair) for pair in engine.period_options()],
        "show_labels": dict(engine.SHOW_LABELS),
        "show_order": list(engine.SHOW_LABELS),
        "ranked": engine.RANKED,
        "ranking_method": engine.RANKING_METHOD,
        "movers_method": engine.MOVERS_METHOD,
        "school_type_order": [value for value, _label in SchoolType.choices],
        "online_mode": profile_records.ONLINE,
        "fy_choices": 3,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write the School Profile's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
