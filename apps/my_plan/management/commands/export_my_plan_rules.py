"""Write My Plan's rules for the Go gateway.

Go owns Activity planning and scheduling (owner brief, 2026-11-11). It
builds My Plan (/my-plan, my_plan_views.my_plan_view,
apps.my_plan.services.get_frontend_context and the page's templates) from
the vocabularies this command writes to
platform/backend/internal/myplan/rules.json: who may open the page, the
period filters' choices, the strip's labels, the keys that turn the page
into an export, and the planning roles whose page carries their own Planned
and remaining. A change to any of them must be exported again;
apps/my_plan/test_my_plan_rules_export.py fails until it is, so the two can
never drift.

    python manage.py export_my_plan_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/myplan/rules.json")


def doors() -> dict:
    """Whether each role may open the page, by the page's own gates:
    require_page_permission("my_plan") and the feed's can_open_url."""
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            "page": RolePermissionService.can_view_page(user, "my_plan")
            and bool(can_open_url(user, "/my-plan")),
        }
    return out


def strip() -> dict:
    """The Plan progress strip as the metric registry labels it, and the
    words its completed share shows when nothing was planned."""
    from apps.core.metrics import MetricValue, render_metric, render_strip
    from apps.my_plan.services import MY_PLAN_TILES

    keys = [key for key, _icon, _variant in MY_PLAN_TILES]
    # As the page renders them with nothing planned: counts of 0 and the
    # completed share of nothing (get_frontend_context).
    values = [MetricValue.measured(0) for _key in keys[:-1]]
    values.append(MetricValue.ratio(0, 0))
    items = render_strip(
        [
            render_metric(key, value, drilldown_url="/my-plan")
            for key, value in zip(keys, values)
        ]
    )
    return {
        "keys": keys,
        "labels": [item["label"] for item in items],
        "drilldown": "/my-plan",
        "no_data": items[-1]["display_value"],
    }


def rules() -> dict:
    from django.conf import settings

    from apps.frontend.views.my_plan_views import EXPORT_PERIOD_KEYS
    from apps.mobile_feed.views import NOT_PASSED
    from apps.my_plan import services
    from apps.planning.country_oversight import rules as planning_rules

    return {
        "doors": doors(),
        "strip": strip(),
        "month_options": [[m["val"], m["label"]] for m in services.MONTH_OPTIONS],
        "quarter_options": list(services.QUARTER_OPTIONS),
        "quarter_first_month": dict(services.QUARTER_FIRST_MONTH),
        "unset_filter_values": sorted(services._UNSET_FILTER_VALUES),
        "export_period_keys": list(EXPORT_PERIOD_KEYS),
        "not_passed_query_keys": sorted(NOT_PASSED),
        # panel_views.plans_visits: a Programme Lead or a CCEO by the role
        # held has a Planned and remaining of their own, and a visit target.
        "program_lead_role": planning_rules.PROGRAM_LEAD_ROLE,
        "cceo_role": planning_rules.CCEO_ROLE,
        "visit_targets": dict(planning_rules.VISIT_TARGETS),
        # scoping.resolve_partner_ids: with the demo bridge on, every reader
        # is the first active partner.
        "partner_role_bridge": bool(getattr(settings, "PARTNER_ROLE_BRIDGE", False)),
        "cluster_status": cluster_status(),
        # The feed is a REST framework view: a ?format= no renderer answers
        # is "not found" before the page is asked.
        "api_formats": api_formats(),
        "plan": plan(),
        "rows": plan_rows(),
        "readiness": readiness(),
        "tables": plan_tables(),
        "past_due": past_due(),
        "week": week(),
        "detail": detail_drawer(),
    }


def detail_drawer() -> dict:
    """What an activity's detail drawer (/my-plan/<id>,
    my_plan_views.activity_detail_view) reads: the budget breakdown's words
    (apps.budget.breakdown), each line's funding status
    (ActivityScheduleCostLine.finance_status), the statuses Cancel is offered
    on (group_actions.may_tick) and the kinds of work whose drawer carries a
    training's or a facilitator's parts, which Go hands on."""
    from apps.activities import facilitation
    from apps.activities.group_actions import _CALLED_OFF_STATUSES, _FINISHED_STATUSES
    from apps.activities.models import ActivityStatus, ActivityType
    from apps.activities.editing import EXECUTED_STATUSES
    from apps.core.enums import MeetingKind
    from apps.fund_requests.models import MONEY_MOVED_ADVANCE_STATUSES
    from apps.partners.models import PartnerAssignment
    from apps.planning.country_oversight.rules import DATED_BY_STAFF
    from apps.activities.services import RETURNED_STATUSES
    from apps.budget import breakdown, costing_service
    from apps.budget.models import ActivityCostStatus
    from apps.budget.reference import RATE_UNITS
    from apps.core.activity_types import NON_FUNDABLE_ACTIVITY_STATUSES
    from apps.daily_visit_batches.pricing import (
        ACCOMMODATION_KEYS,
        KEY_LABELS,
        MIXED_TRANSPORT_LABEL,
    )
    from apps.planning import training_ceilings

    return {
        "rate_units": dict(RATE_UNITS),
        "key_labels": dict(KEY_LABELS),
        "mixed_transport_label": MIXED_TRANSPORT_LABEL,
        "period_suffix": breakdown._PERIOD_SUFFIX,
        # costing_service._missing_label: a missing rate by its name.
        "missing_labels": dict(costing_service._KEY_LABEL),
        "fee_line_type": facilitation.FEE_LINE_TYPE,
        "staff_facilitator_label": facilitation.STAFF_FACILITATOR_LABEL,
        "non_fundable_statuses": list(NON_FUNDABLE_ACTIVITY_STATUSES),
        "untickable_statuses": sorted(_FINISHED_STATUSES | _CALLED_OFF_STATUSES),
        "returned_statuses": list(RETURNED_STATUSES),
        "spent_cost_statuses": [
            ActivityCostStatus.ACCOUNTED,
            ActivityCostStatus.CLOSED,
        ],
        "status_labels": {value: str(label) for value, label in ActivityStatus.choices},
        "type_labels": {value: str(label) for value, label in ActivityType.choices},
        "accommodation_keys": sorted(ACCOMMODATION_KEYS),
        "training_types": sorted(training_ceilings._TRAINING_TYPES),
        "meeting_types": sorted(training_ceilings._MEETING_TYPES),
        "facilitator_types": sorted(facilitation.FACILITATOR_TRAINING_TYPES),
        # _training_profile_context: a meeting held as a training, and how a
        # training is delivered (by a school of its own or a cluster).
        # The Reschedule and Cancel drawers (reschedule_drawer_view,
        # cancel_activity_drawer_view): work already carried out, money that
        # has moved, and a partner's dated work whose school waits for it.
        "executed_statuses": sorted(EXECUTED_STATUSES),
        "money_moved_advance_statuses": [str(s) for s in MONEY_MOVED_ADVANCE_STATUSES],
        "partner_scheduled_assignment_statuses": list(
            PartnerAssignment.SCHEDULED_STATUSES
        ),
        "dated_by_staff": DATED_BY_STAFF,
        "training_meeting_kind": MeetingKind.TRAINING.value,
        "delivery_labels": {
            "school": training_ceilings.DELIVERY_LABELS[training_ceilings.IN_SCHOOL],
            "cluster": training_ceilings.DELIVERY_LABELS[training_ceilings.GROUP],
        },
    }


def week() -> dict:
    """What a field officer's This Week lists (apps.analytics.pl_week_service
    in its solo mode): the statuses each state reads, the three tables, the
    figures a link may list and how far the week arrows reach."""
    from apps.analytics import pl_week_service as w

    return {
        "released_statuses": list(w.RELEASED_STATUSES),
        "with_ia_statuses": list(w.WITH_IA_STATUSES),
        "awaiting_lead_statuses": list(w.AWAITING_LEAD_STATUSES),
        "not_submitted_statuses": list(w.NOT_SUBMITTED_STATUSES),
        "sf_missing_statuses": list(w.SF_MISSING_STATUSES),
        "started_statuses": list(w.STARTED_STATUSES),
        "returned_statuses": list(w.RETURNED_STATUSES),
        "own_awaiting_label": w.OWN_AWAITING_LABEL,
        "tables": [[key, title] for key, title in w.TABLES],
        "show_filters": sorted(w.SHOW_FILTERS),
        "week_reach": w.WEEK_REACH,
        "rows_per_page": w.ROWS_PER_PAGE,
    }


def past_due() -> dict:
    """What Home's "What needs you now" lists (apps.my_plan.past_due_service):
    the states that are no longer past due, the three tables' activity
    types, the statuses a row reads as Returned, and the page size each
    table pages by ({% paginate %})."""
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.my_plan import past_due_service as pd

    return {
        "terminal_statuses": sorted(pd.TERMINAL_OR_COMPLETED_STATUSES),
        "visit_types": sorted(pd.VISIT_TYPES),
        "training_types": sorted(pd.TRAINING_TYPES),
        "meeting_types": sorted(pd.MEETING_TYPES),
        "returned_statuses": list(pd.RETURNED_STATUSES),
        "page_size": TABLE_PAGE_SIZE,
    }


def readiness() -> dict:
    """What a planner's own Planned and remaining names its lists by: the
    schools behind each figure (planning_monitor.GAP_LABELS, which
    my_plan_views._readiness_list reads a ?list= key against)."""
    from apps.core.permissions import RolePermissionService
    from apps.core.rbac import EdifyRole
    from apps.partners.models import PartnerAssignment
    from apps.planning import list_actions
    from apps.planning.planning_monitor import GAP_LABELS

    doors = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        # What a listed school's Actions menu offers (list_actions.offer).
        doors[role.value] = {
            "schedule": bool(RolePermissionService.can_open_schedule_drawer(user)),
            "assign": bool(RolePermissionService.can_assign_to_partner(user)),
            "withdraw": bool(
                RolePermissionService.can_view_page(user, "partner_oversight")
            ),
            "move": bool(RolePermissionService.can_view_page(user, "my_plan")),
        }
    return {
        "gap_labels": dict(GAP_LABELS),
        "list_doors": doors,
        "open_staff_statuses": list(list_actions._OPEN_STAFF_STATUSES),
        "open_handover_statuses": [
            *PartnerAssignment.UNSCHEDULED_STATUSES,
            PartnerAssignment.STATUS_PARTNER_SCHEDULED,
            PartnerAssignment.STATUS_SCHEDULED,
        ],
    }


def plan_tables() -> dict:
    """What My Plan's own tables draw a row of finished work by: the row's
    tint (completion_columns.row_state), its tick box (group_actions.may_tick),
    its Actions menu (activity_row.html over compute_next_action), the cards
    that would list it (attention.html) and the outreach visits named beside
    the visit target."""
    from apps.activities import completion_columns as cc
    from apps.activities import day_off, facilitation, group_actions, return_notes
    from apps.activities.models import Activity
    from apps.my_plan import services
    from apps.core.enums import SchoolType
    from apps.partners.models import PartnerAssignment
    from apps.planning.country_oversight import rules as planning_rules
    from apps.planning.visit_gate import PROGRAMME_SCHOOL_TYPES

    return {
        "awaiting_delivery": list(day_off.AWAITING_DELIVERY),
        "never_overdue": sorted(cc._NEVER_OVERDUE),
        "untickable": sorted(
            group_actions._FINISHED_STATUSES | group_actions._CALLED_OFF_STATUSES
        ),
        "worked_statuses": list(services._WORKED_STATUSES),
        "handed_in_statuses": sorted(services.HANDED_IN_STATUSES),
        # An advance or claim waiting on somebody: compute_next_action's
        # "view_status", which puts the row on Waiting on Approval.
        "money_awaiting_statuses": sorted(services._MONEY_AWAITING_STATUSES),
        "submit_needs_participants_types": list(
            services.SUBMIT_NEEDS_PARTICIPANTS_TYPES
        ),
        "facilitator_types": sorted(facilitation.FACILITATOR_TRAINING_TYPES),
        "facilitator_editable_statuses": sorted(
            facilitation.FACILITATOR_EDITABLE_STATUSES
        ),
        "meeting_kind_labels": _choices(Activity, "meeting_kind"),
        "outreach_types": list(planning_rules.OUTREACH_TYPES),
        "outreach_purposes": list(planning_rules.OUTREACH_PURPOSES),
        "visit_shape_types": list(planning_rules.VISIT_SHAPE_TYPES),
        # training_ceilings._open_handovers: a hand-over the Partner has not
        # dated, which My Training Summary may count.
        "open_handover_statuses": list(PartnerAssignment.UNSCHEDULED_STATUSES),
        # programme_school_work's sections: each programme school type's
        # label (dict(SchoolType.choices)).
        "programme_school_labels": {
            kind: str(dict(SchoolType.choices)[kind]) for kind in PROGRAMME_SCHOOL_TYPES
        },
        # The attention cards (attention.html): compute_next_action's lists,
        # the loop's urgency sections and awaits_approval.
        "dated_and_open": list(services._DATED_AND_OPEN),
        "ssa_upload_types": list(services.SSA_UPLOAD_TYPES),
        "waiting_on_me_actions": list(services.WAITING_ON_ME_ACTIONS),
        "finance_pending_payment_statuses": list(
            services.FINANCE_PENDING_PAYMENT_STATUSES
        ),
        "returned_by": dict(return_notes.RETURNED_BY),
    }


def _choices(model, field: str) -> dict:
    from apps.core.choice_labels import label_for

    return {
        str(value): str(label_for(model, field, value))
        for value, _label in model._meta.get_field(field).flatchoices
    }


def plan_rows() -> dict:
    """What the plan's rows are drawn from (get_frontend_context's loop and
    the modules each column reads) and the two Core sheets Core School
    Oversight lists (table_export.core_school_plans): the labels, the
    statuses and types each rule reads, the cost keys and the words."""
    from apps.activities import completion_columns as cc
    from apps.activities import online_training, pair_costing, training_names
    from apps.activities.models import Activity
    from apps.activities.services import PARTNER_SSA_SUPPORT_ACTIVITY_TYPES
    from apps.budget import costing
    from django.conf import settings

    from apps.budget.models import RateCardKind, RateCardStatus
    from apps.budget.reference import (
        CANONICAL_RATE_KEYS,
        RATE_ALIASES,
        RETIRED_COST_SETTING_KEYS,
    )
    from apps.core import activity_types
    from apps.daily_visit_batches import districts, pricing
    from apps.my_plan import services, table_export
    from apps.partners.purposes import _LABELS as PURPOSE_LABELS
    from apps.pl_review.services import LEAD_VERIFIED_ROLES
    from apps.planning.country_oversight import rules as planning_rules
    from apps.planning.visit_gate import PROGRAMME_SCHOOL_TYPES
    from apps.schools.lifecycle_models import OPERATING_STATUSES
    from apps.ssa import visit_scores
    from apps.ssa.creation import HOLDING_STATUSES

    return {
        "activity_type_labels": _choices(Activity, "activity_type"),
        "focus_intervention_labels": _choices(Activity, "focus_intervention"),
        "purpose_labels": dict(PURPOSE_LABELS),
        "visit_types": list(activity_types.VISIT_TYPES),
        "training_types": [str(t) for t in activity_types.TRAINING_TYPES],
        "cluster_meeting_types": list(activity_types.CLUSTER_MEETING_TYPES),
        "programme_event_types": [str(t) for t in activity_types.PROGRAMME_EVENT_TYPES],
        "programme_school_types": list(PROGRAMME_SCHOOL_TYPES),
        "non_fundable_statuses": list(activity_types.NON_FUNDABLE_ACTIVITY_STATUSES),
        "operating_statuses": list(OPERATING_STATUSES),
        "approved_statuses": sorted(cc.APPROVED_STATUSES),
        "lead_verified_roles": list(LEAD_VERIFIED_ROLES),
        "partner_ssa_support_types": sorted(PARTNER_SSA_SUPPORT_ACTIVITY_TYPES),
        "ssa_holding_statuses": list(HOLDING_STATUSES),
        "not_assessed_types": list(planning_rules.NOT_ASSESSED_TYPES),
        "online_training_types": [
            str(t) for t in online_training.ONLINE_TRAINING_TYPES
        ],
        "online_mode": online_training.ONLINE,
        "online_free_note": online_training.ONLINE_FREE_NOTE,
        "online_training_label": training_names.ONLINE_TRAINING_LABEL,
        "mode_of_delivery": dict(training_names.MODE_OF_DELIVERY),
        "companion_gone_statuses": list(pair_costing.COMPANION_GONE_STATUSES),
        "captured_in_visit_note": pair_costing.CAPTURED_IN_VISIT_NOTE,
        "captured_in_training_note": pair_costing.CAPTURED_IN_TRAINING_NOTE,
        "retired_cost_setting_keys": sorted(RETIRED_COST_SETTING_KEYS),
        "rate_aliases": {key: list(old) for key, old in RATE_ALIASES.items()},
        "meals_rate_keys": list(costing.MEALS_RATE_KEYS),
        "group_training_meals_rate_key": costing.GROUP_TRAINING_MEALS_RATE_KEY,
        # costing_service.active_catalogue and _rate_card: the live card a
        # session not yet costed reads its meal rate from.
        "catalogue_country": getattr(settings, "COUNTRY", "Uganda"),
        "catalogue_kind": str(RateCardKind.OPERATIONAL),
        "catalogue_status": str(RateCardStatus.PUBLISHED),
        "canonical_rate_keys": sorted(CANONICAL_RATE_KEYS),
        "complete_label": services.COMPLETE_LABEL,
        "finished_early": cc.FINISHED_EARLY,
        "missing_sf": cc.MISSING_SF,
        "missing_evidence": cc.MISSING_EVIDENCE,
        "missing_both": cc.MISSING_BOTH,
        # completion_columns.expected_evidence: the form a partner's work is
        # completed with, attendance for these types and a visit form for
        # every other.
        "evidence_attendance_types": sorted(cc._ATTENDANCE_TYPES),
        "evidence_attendance_kind": cc.expected_evidence(
            next(iter(sorted(cc._ATTENDANCE_TYPES)))
        )[0],
        "evidence_visit_kind": cc.expected_evidence("school_visit")[0],
        "awaiting_ssa_label": visit_scores.AWAITING_SSA_LABEL,
        "enter_ssa_text": visit_scores.ENTER_SSA_TEXT,
        "field_roles": sorted(districts.FIELD_ROLES),
        "field_role_aliases": sorted(districts._FIELD_ROLE_ALIASES),
        "hq_primary_districts": list(districts.HQ_PRIMARY_DISTRICTS),
        "day_mark_labels": dict(pricing.DAY_MARK_LABELS),
        "core_visits": {
            "title": table_export.CORE_VISITS_TITLE,
            "headers": [h for h, _c in table_export.CORE_SCHOOL_VISITS.columns],
        },
        "core_trainings": {
            "title": table_export.CORE_TRAININGS_TITLE,
            "headers": [h for h, _c in table_export.CORE_TRAINING_PLAN_COLUMNS],
        },
    }


def plan() -> dict:
    """What the page counts and lists (get_frontend_context): whose work,
    which states each list leaves out, the Status filter's values, the tile
    counts' activity types, and the rules a counted visit is read by."""
    from apps.activities.completion_columns import OFFICER_COMPLETED_STATUSES
    from apps.activities.services import RETURNED_STATUSES
    from apps.core.activity_types import (
        COMPLETED_WORK_STATUSES,
        NOT_STARTED_ACTIVITY_STATUSES,
        UNDER_WAY_ACTIVITY_STATUSES,
    )
    from apps.core.metrics.payload import HELPER_FIGURE_CHARS
    from apps.my_plan import services
    from apps.planning import training_ceilings
    from apps.planning.management.commands.export_planning_page_rules import (
        counted_visits,
    )

    return {
        "excluded_statuses": list(services.ACTIVE_MY_PLAN_EXCLUDED_STATUSES),
        "partner_only_statuses": list(services.PARTNER_ONLY_STATUSES),
        "officer_completed_statuses": sorted(OFFICER_COMPLETED_STATUSES),
        "returned_statuses": list(RETURNED_STATUSES),
        "completed_work_statuses": list(COMPLETED_WORK_STATUSES),
        "not_started_statuses": list(NOT_STARTED_ACTIVITY_STATUSES),
        "under_way_statuses": list(UNDER_WAY_ACTIVITY_STATUSES),
        "plan_states": list(services.PLAN_STATES),
        "submitted_filter_statuses": list(services.SUBMITTED_FILTER_STATUSES),
        "returned_filter_statuses": list(services.RETURNED_FILTER_STATUSES),
        "visit_types": list(services.MY_PLAN_VISIT_TYPES),
        "training_types": list(services.MY_PLAN_TRAINING_TYPES),
        "meeting_types": list(services.MY_PLAN_MEETING_TYPES),
        "counted_visits": counted_visits(),
        # My Training Summary's trainings (training_ceilings._training_q).
        "summary_training_types": list(training_ceilings._TRAINING_TYPES),
        "summary_meeting_types": list(training_ceilings._MEETING_TYPES),
        "helper_figure_chars": HELPER_FIGURE_CHARS,
    }


def cluster_status() -> dict:
    """My Plan's Cluster Planning Status (apps.clusters.planning_status): the
    session types each column reads, the statuses that are planned and that
    are delivered, and the member schools counted."""
    from apps.clusters.planning_status import TRAINING_SESSION_TYPES
    from apps.core.activity_types import CLUSTER_MEETING_TYPES
    from apps.planning.school_planning_badges import (
        AWAITING_VERIFICATION_STATUSES,
        PLANNED_STATUSES,
        VERIFIED_STATUSES,
    )
    from apps.schools.lifecycle_models import OPERATING_STATUSES

    return {
        "training_types": list(TRAINING_SESSION_TYPES),
        "meeting_types": sorted(str(t) for t in CLUSTER_MEETING_TYPES),
        "planned_statuses": sorted(PLANNED_STATUSES),
        "delivered_statuses": sorted(
            AWAITING_VERIFICATION_STATUSES | VERIFIED_STATUSES
        ),
        "operating_statuses": list(OPERATING_STATUSES),
    }


def api_formats() -> list[str]:
    from rest_framework.settings import api_settings

    return sorted(renderer.format for renderer in api_settings.DEFAULT_RENDERER_CLASSES)


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write My Plan's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
