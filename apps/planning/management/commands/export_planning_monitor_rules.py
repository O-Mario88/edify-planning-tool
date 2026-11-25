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


def _page() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.core.scoping import COUNTRY_ROLES
    from apps.frontend.views import dashboard_embed, oversight_views
    from apps.planning.oversight_service import _lens_roles as lens_roles
    from apps.schools.management.commands.export_school_directory_rules import (
        _role_user,
    )

    return {
        "roles": sorted(
            role.value
            for role in EdifyRole
            if RolePermissionService.can_view_page(
                _role_user(role.value), "planning_monitor"
            )
            and can_open_url(_role_user(role.value), "/planning-monitor/")
        ),
        "country_roles": sorted(COUNTRY_ROLES),
        # The roles whose oversight lens is the whole country
        # (resolve_oversight_scope): a country reader's page, called the
        # country's only for COUNTRY_ROLES (is_country_reader).
        "country_lens_roles": sorted(lens_roles()[0]),
        # The roles whose lens is their region's: the Programme Leads the
        # region's schools are held under (monitor_roster lead_ids_hint).
        "region_lens_roles": sorted(lens_roles()[1]),
        "dashboard_role": dashboard_embed.PROGRAM_LEAD,
        "oversight_roles": sorted(oversight_views.MONITORS_ON_OVERSIGHT_ROLES),
        # Where a reader who keeps the monitors as Planning Oversight tabs is
        # sent (_to_planning_monitor).
        "oversight_path": oversight_views.TEAM_OVERSIGHT_PATH,
    }


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
        # /planning-monitor/ on its own: who opens it, who reads it as the
        # country (or a superuser), and the roles it sends elsewhere.
        "page": _page(),
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
        "execution": _execution(),
        "country_oversight": _country_oversight(),
    }


#: The Execution & Completion tab's figures (oversight_views._execution_kpis).
EXECUTION_SHARES = (
    "execution_visits_delivered_target",
    "execution_due_delivered",
    "execution_complete_share",
    "execution_partner_delivered",
)
EXECUTION_COUNTS = ("execution_overdue", "execution_awaiting_pl")


def _execution() -> dict:
    """The Execution & Completion tab (apps.planning.execution_monitor): the
    statuses it reads work by, the follow-up lists and columns, and its
    figures' names."""
    from apps.core.metrics import MetricValue, render_kpi_item
    from apps.planning import execution_monitor as execution
    from apps.planning.oversight_service import LIVE_ACTIVITY_STATUSES

    labels = {
        key: render_kpi_item(key, MetricValue.ratio(1, 1), helper="")["label"]
        for key in EXECUTION_SHARES
    }
    labels |= {
        key: render_kpi_item(key, MetricValue.measured(1), helper="")["label"]
        for key in EXECUTION_COUNTS
    }
    return {
        "live_statuses": sorted(_values(LIVE_ACTIVITY_STATUSES)),
        "returned_statuses": sorted(execution.RETURNED_STATUSES),
        "awaiting_pl_statuses": sorted(execution.AWAITING_PL_STATUSES),
        "lists": [list(item) for item in execution.LISTS],
        "list_columns": [list(column) for column in execution.LIST_COLUMNS],
        "kpi_labels": labels,
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


def _country_oversight() -> dict:
    """Country Planning Oversight's own vocabulary (apps.planning.country_oversight
    .policy, coverage and requirements): the school groups and their slots,
    the states its figures count, the staff ceilings, the phasing a quarter or
    a month reads, and the hand-over and Core package rules the dataset reads.
    The rulebook's own words are the Planning Monitor's, above."""
    from apps.activities.completion_columns import _ATTENDANCE_TYPES
    from apps.core_schools import package_credit
    from apps.hr.performance_engine import DEFAULT_PHASING
    from apps.partners.models import PartnerAssignment
    from apps.planning.country_oversight import hierarchy, policy, requirements, rules
    from apps.schools.lifecycle_models import CLOSED_STATUSES

    return {
        "policy_version": policy.POLICY_VERSION,
        "families": dict(sorted(policy.SCHOOL_TYPE_FAMILY.items())),
        "family_labels": dict(sorted(policy.FAMILY_LABELS.items())),
        "unmapped_family": policy.UNMAPPED_FAMILY,
        "core_family": policy.CORE_FAMILY,
        "client_family": policy.CLIENT_FAMILY,
        "family_slots": {
            family: {
                "staff": need.staff_visit_slots,
                "partner": need.partner_visit_slots,
                "flexible": need.flexible_visit_slots,
            }
            for family, need in sorted(policy.REQUIREMENTS.items())
        },
        "staff_ceilings": dict(sorted(policy.STAFF_CEILINGS.items())),
        "planned_states": sorted(policy.PLANNED_STATES),
        "verified_states": sorted(policy.VERIFIED_STATES),
        "excluded_duplicate_statuses": list(policy.EXCLUDED_DUPLICATE_STATUSES),
        "closed_statuses": sorted(str(s) for s in CLOSED_STATUSES),
        "phasing": {str(q): share for q, share in sorted(DEFAULT_PHASING.items())},
        "attendance_types": sorted(_ATTENDANCE_TYPES),
        "unscheduled_handover_statuses": list(PartnerAssignment.UNSCHEDULED_STATUSES),
        "returned_to_staff": PartnerAssignment.STATUS_RETURNED_TO_STAFF,
        "closed_handover_statuses": list(rules.CLOSED_HANDOVER_STATUSES),
        "package_training_types": sorted(package_credit.PACKAGE_TRAINING_TYPES),
        "package_visit_types": sorted(package_credit.PACKAGE_VISIT_TYPES),
        "non_package_visit_purposes": sorted(package_credit.NON_PACKAGE_VISIT_PURPOSES),
        "purpose_activity_types": dict(
            sorted(package_credit.PURPOSE_ACTIVITY_TYPES.items())
        ),
        "no_owner": [requirements.NO_OWNER_KEY, requirements.NO_OWNER_LABEL],
        # The figures a school, a person and every row carry, in order.
        "fields": list(hierarchy.FIELDS),
        "people_fields": list(hierarchy.PEOPLE_FIELDS),
        "phased_fields": list(hierarchy.PHASED_FIELDS),
        "type_fields": dict(sorted(hierarchy.TYPE_FIELDS.items())),
        "page": _country_oversight_page(),
        "no_lead": [requirements.NO_LEAD_KEY, requirements.NO_LEAD_LABEL],
    }


def _country_oversight_page() -> dict:
    """The planning-coverage dashboard's own words: each card's label and the
    table it opens, the tabs, the people table's columns and the filters'
    choices (apps.planning.country_oversight.service, oversight_views)."""
    from apps.core.enums import ActivityStatus, ActivityType, SsaIntervention
    from apps.core.metrics import MetricValue, render_metric
    from apps.core.permissions import RolePermissionService
    from apps.core.rbac import EdifyRole
    from apps.frontend.views.oversight_views import country_lens_tabs
    from apps.planning.country_execution.followups import EXEC_ISSUES
    from apps.planning.country_oversight import followups as fu
    from apps.planning.country_oversight import rules as book
    from apps.planning.country_oversight import service, tables
    from apps.planning.followup_models import OPEN_FOLLOW_UP_STATES, FollowUpStatus
    from apps.schools.management.commands.export_school_directory_rules import (
        _role_user,
    )

    return {
        "kpi_tables": dict(service.KPI_TABLES),
        "kpi_labels": {
            key: render_metric(key, MetricValue.ratio(1, 1)).as_dict()["label"]
            for key in service.KPI_TABLES
        },
        "type_views": [list(v) for v in service.TYPE_VIEWS],
        "table_views": [list(v) for v in service.TABLE_VIEWS],
        "table_columns": [list(c) for c in service.TABLE_COLUMNS],
        "type_options": [list(o) for o in service.TYPE_OPTIONS],
        "channel_options": [list(o) for o in service.CHANNEL_OPTIONS],
        "cluster_options": [list(o) for o in service.CLUSTER_OPTIONS],
        "status_options": [list(o) for o in service.STATUS_OPTIONS],
        "lens_tabs": [
            [t["key"], t["label"], t["short"], t["href"]]
            for t in country_lens_tabs("coverage")
        ],
        # The Open Follow-ups panel (country_oversight_views._followup_card).
        "followup_open_states": sorted(str(s) for s in OPEN_FOLLOW_UP_STATES),
        "followup_status_labels": {str(k): str(v) for k, v in FollowUpStatus.choices},
        "followup_issue_labels": {
            key: issue.label for key, issue in {**EXEC_ISSUES, **fu.ISSUES}.items()
        },
        # The consolidated tables behind the figures (tables.SPECS), in the
        # order the table page offers them.
        "tables": [
            {
                "key": spec.key,
                "title": spec.title,
                "short": spec.short,
                "unit": spec.unit,
                "description": spec.description,
                "columns": [
                    {
                        "key": c.key,
                        "label": c.label,
                        "numeric": c.numeric,
                        "is_date": c.is_date,
                        "is_school": c.is_school,
                        "blank": c.blank,
                        "quiet": c.quiet,
                        "kind": c.kind,
                    }
                    for c in spec.columns
                ],
                "export_only": list(spec.export_only),
            }
            for spec in tables.SPECS.values()
        ],
        "table_tabs": list(tables.TAB_ORDER),
        "table_labels": {
            "nobody": tables.NOBODY,
            "unclustered": tables.UNCLUSTERED,
            "no_lead": service.NO_LEAD_LABEL,
            "no_owner": service.NO_OWNER_LABEL,
            "partner_planned": tables.PARTNER_PLANNED,
            "awaiting_partner": tables.AWAITING_PARTNER,
            "assigned": tables.ASSIGNED,
            "data_collection": tables.DATA_COLLECTION,
        },
        # The words the activity tables print (tables._Book).
        "table_words": {
            "statuses": {str(k): str(v) for k, v in ActivityStatus.choices},
            "types": {str(k): str(v) for k, v in ActivityType.choices},
            "interventions": {str(k): str(v) for k, v in SsaIntervention.choices},
            "kinds": {str(k): str(v) for k, v in book.KIND_LABELS.items()},
            "waiting_states": sorted(tables._WAITING_STATES),
            "duplicate_labels": dict(book.DUPLICATE_LABELS),
        },
        # may_export: the drill-down's Export (can_export).
        "export_roles": sorted(
            role.value
            for role in EdifyRole
            if RolePermissionService.can_export(
                _role_user(role.value), "/country-planning-oversight/coverage-export"
            )
        ),
    }


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
