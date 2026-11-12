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
        # The feed is a REST framework view: a ?format= no renderer answers
        # is "not found" before the page is asked.
        "api_formats": api_formats(),
        "plan": plan(),
        "rows": plan_rows(),
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
        "awaiting_ssa_label": visit_scores.AWAITING_SSA_LABEL,
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
