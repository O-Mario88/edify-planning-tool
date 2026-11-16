"""Write the Planning Monitor's rules for the Go gateway.

Go builds the Planning Monitor (apps.planning.planning_monitor, the figures
apps.planning.readiness folds from it, and the tables the Programme Lead
reads on their dashboard) from the vocabularies this command writes to
platform/backend/internal/planningmonitor/rules.json: the school types it
counts and what each takes in a year, which visits count and which kind each
is, the states a plan, a delivery and a Partner's hand-over are in, the
roles and their targets, the gaps and lists a figure opens, and the ledger's
lines. A change to any of them must be exported again;
apps/planning/test_planning_monitor_rules_export.py fails until it is, so
the two can never drift.

    python manage.py export_planning_monitor_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

EXPORT_PATH = Path("platform/backend/internal/planningmonitor/rules.json")


def _values(items) -> list[str]:
    return [str(getattr(item, "value", item)) for item in items]


def rules() -> dict:
    from apps.activities.cluster_attendance import SCHOOL_TRAINING_TYPES
    from apps.activities.completion_columns import (
        APPROVED_STATUSES,
        OFFICER_COMPLETED_STATUSES,
    )
    from apps.core.activity_types import CLUSTER_MEETING_TYPES, TRAINING_TYPES
    from apps.core.enums import ExecutorType
    from apps.frontend.views import oversight_views
    from apps.partners.models import PartnerAssignment
    from apps.planning import monitor_roster as roster
    from apps.planning import planning_monitor as monitor
    from apps.planning import portfolio_service as portfolio
    from apps.planning import readiness
    from apps.planning.country_oversight import policy
    from apps.planning.country_oversight import rules as book
    from apps.projects.models import OPEN_PROJECT_STATUSES
    from apps.schools.lifecycle_models import OPERATING_STATUSES
    from apps.ssa.current_year import CURRENT_SSA_STATUSES

    return {
        "rules_version": book.RULES_VERSION,
        "program_lead_role": book.PROGRAM_LEAD_ROLE,
        "cceo_role": book.CCEO_ROLE,
        "role_codes": {
            book.PROGRAM_LEAD_ROLE: roster.ROLE_PL,
            book.CCEO_ROLE: roster.ROLE_CCEO,
        },
        "visit_targets": dict(roster.VISITS_TARGET_BY_ROLE),
        "role_labels": {roster.ROLE_PL: "Programme Lead", roster.ROLE_CCEO: "CCEO"},
        "no_lead": [roster.NO_LEAD_KEY, roster.NO_LEAD_LABEL],
        "unassigned": [portfolio.UNASSIGNED_KEY, portfolio.UNASSIGNED_LABEL],
        "core_types": list(monitor.CORE_TYPES),
        "client_types": list(monitor.CLIENT_TYPES),
        "core_staff_visits": monitor.CORE_STAFF_VISITS_PER_SCHOOL,
        "core_partner": monitor.CORE_PARTNER_PER_SCHOOL,
        "type_order": list(book.TYPE_ORDER),
        "type_labels": dict(book.TYPE_LABELS),
        "requirements": {
            key: {
                "staff_visits": need.staff_visits,
                "partner_visits": need.partner_visits,
                "either_visits": need.either_visits,
                "staff_trainings": need.staff_trainings,
                "partner_trainings": need.partner_trainings,
                "either_trainings": need.either_trainings,
            }
            for key, need in book.REQUIREMENTS.items()
        },
        "trained_types": list(book.TRAINED_TYPES),
        # Which visits count, and which kind each is (rules.visit_kind).
        "visit_shape_types": list(book.VISIT_SHAPE_TYPES),
        "companion_purpose": book.COMPANION_PURPOSE,
        "outreach_purposes": list(book.OUTREACH_PURPOSES),
        "outreach_types": list(book.OUTREACH_TYPES),
        "data_collection_purposes": list(book.DATA_COLLECTION_PURPOSES),
        "data_collection_types": list(book.DATA_COLLECTION_TYPES),
        "purpose_kinds": dict(book._PURPOSE_KIND),
        "type_kinds": dict(book._TYPE_KIND),
        "kind_ssa": book.KIND_SSA,
        # The states a plan, a delivery and a Partner's work are in.
        "planned_states": sorted(_values(policy.PLANNED_STATES)),
        "assigned_to_partner": str(policy.S.ASSIGNED_TO_PARTNER),
        "dated_by_partner": book.DATED_BY_PARTNER,
        "certified_partner_agency": ExecutorType.CERTIFIED_PARTNER_AGENCY.value,
        "delivered_statuses": sorted(APPROVED_STATUSES),
        "officer_completed_statuses": sorted(OFFICER_COMPLETED_STATUSES),
        "unscheduled_handover_statuses": list(PartnerAssignment.UNSCHEDULED_STATUSES),
        "school_training_types": _values(SCHOOL_TRAINING_TYPES),
        "training_types": _values(TRAINING_TYPES),
        "cluster_meeting_types": _values(CLUSTER_MEETING_TYPES),
        "open_project_statuses": sorted(_values(OPEN_PROJECT_STATUSES)),
        "current_ssa_statuses": list(CURRENT_SSA_STATUSES),
        "operating_statuses": _values(OPERATING_STATUSES),
        # What a figure opens, and the ledger's lines.
        "gaps": [list(gap) for gap in monitor.GAPS],
        "lists": [list(item) for item in monitor.LISTS],
        "gap_columns": [list(column) for column in monitor.GAP_COLUMNS],
        "gap_figures": dict(monitor.GAP_FIGURES),
        "ledger": [list(line) for line in readiness.LEDGER],
        "pillar_labels": dict(readiness.PILLAR_LABELS),
        # The monitor's figures' names (oversight_views._monitor_kpis), as
        # the metric registry gives them.
        "kpi_labels": kpi_labels(),
        "monitor_tabs": [list(tab) for tab in oversight_views.MONITOR_TABS],
    }


#: The monitor's figures: the three read as shares, the four as counts.
KPI_SHARES = (
    "monitor_visits_planned_share",
    "monitor_schools_with_visit",
    "monitor_schools_with_training",
)
KPI_COUNTS = (
    "monitor_schools_unplanned",
    "monitor_schools_not_clustered",
    "monitor_partner_share",
    "monitor_schools_in_projects",
)


def kpi_labels() -> dict:
    from apps.core.metrics import MetricValue, render_kpi_item

    labels = {
        key: render_kpi_item(key, MetricValue.ratio(1, 1), helper="")["label"]
        for key in KPI_SHARES
    }
    labels |= {
        key: render_kpi_item(key, MetricValue.measured(1), helper="")["label"]
        for key in KPI_COUNTS
    }
    return labels


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write the Planning Monitor's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
