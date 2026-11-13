"""Write the Work Plan page's rules for the Go gateway.

Go reads the Work Plan (/work-plan, apps.frontend.views.work_plan_page and
its templates) for the app (M4: "Read: My Plan, Work Plan, calendar"). It
builds the page from the vocabularies this command writes to
platform/backend/internal/workplan/rules.json: who may open the page and
follow each of its links, the statuses, types and labels each column and
figure reads, the strip's labels, and the national holiday calendar the
day-off marks read. A change to any of them must be exported again;
apps/frontend/test_work_plan_rules_export.py fails until it is, so the two
can never drift.

The doors are not restated: each role's answer is computed here by the gates
the page itself asks (require_page_permission("work_plan"), can_open_url,
has_permission, holds_operational_admin, build_workspace).

    python manage.py export_work_plan_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/workplan/rules.json")

#: The strip's figures, in the page's order (build_work_plan_context).
STRIP_KEYS = (
    "work_plan_activities_planned",
    "work_plan_activities_this_month",
    "work_plan_plan_derived_budget",
    "work_plan_pending_approval",
    "work_plan_cost_setup_required",
    "work_plan_activities_at_risk",
)

#: The links a row or the page may show, each asked of can_open_url with a
#: stand-in id (no gate reads the id).
LINKS = {
    "school_profile": "/schools/0",
    "record": "/my-plan/0",
    "reschedule": "/my-plan/0/reschedule-drawer",
    "message": "/messages/new?context_type=activity&context_id=0&to=0",
    "complete": "/activities/0/complete",
    "start": "/activities/0/start",
    "evidence": "/activities/0/evidence",
    "salesforce_id": "/activities/0/salesforce-id",
    "submit": "/activities/0/submit",
    "partner_evidence": "/partner/activities/0/evidence",
    "visit_requests": "/planning/visit-requests",
    "reimbursement_receipt": "/my-plan/0/confirm-reimbursement-receipt",
    "accountability": "/my-plan/0/accountability",
}

#: The years the national holiday calendar is written out for.
HOLIDAY_YEARS = range(2015, 2046)


def _workspace(user) -> dict | None:
    from apps.core.navigation import build_workspace

    workspace = build_workspace(user, "/work-plan")
    if workspace is None:
        return None
    return {
        "key": workspace["key"],
        "label": workspace["label"],
        "sections": [
            {
                "label": section["label"],
                "url": section["url"],
                "active": bool(section["active"]),
                "starts_cluster": bool(section.get("starts_cluster")),
            }
            for section in workspace["sections"]
        ],
    }


def doors() -> dict:
    """What each role may open and do on the Work Plan, by the page's gates."""
    from apps.core.permissions import (
        RolePermissionService,
        can_open_url,
        has_permission,
    )
    from apps.core.rbac import EdifyRole, Permission, holds_operational_admin
    from apps.frontend.views.work_plan_page import _NO_ACTION_ROLES

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            # require_page_permission("work_plan") and the feed's can_open_url.
            "page": RolePermissionService.can_view_page(user, "work_plan")
            and bool(can_open_url(user, "/work-plan")),
            "add_activity": has_permission(
                user, Permission.MANUAL_ACTIVITY_CREATE.value
            ),
            "export": has_permission(user, Permission.EXPORT.value),
            "operational_admin": holds_operational_admin(user),
            "actions_enabled": role.value not in _NO_ACTION_ROLES,
            "opens": {key: bool(can_open_url(user, url)) for key, url in LINKS.items()},
            "workspace": _workspace(user),
        }
    return out


def _holidays() -> list[dict]:
    from apps.core.public_holidays import national_holidays

    return [
        {
            "date": holiday.date.isoformat(),
            "name": holiday.name,
            "label": holiday.label,
            "expected": holiday.expected,
        }
        for year in HOLIDAY_YEARS
        for holiday in national_holidays(year)
        if holiday.is_public
    ]


def rules() -> dict:
    from apps.activities import day_off, pair_costing
    from apps.activities.models import Activity
    from apps.activities.online_training import (
        ONLINE,
        ONLINE_FREE_NOTE,
        ONLINE_TRAINING_TYPES,
    )
    from apps.activities.training_names import ONLINE_TRAINING_LABEL
    from apps.core import public_holidays
    from apps.core.activity_types import (
        CLUSTER_MEETING_TYPES,
        COMPLETED_WORK_STATUSES,
        TRAINING_TYPES,
        VISIT_TYPES,
    )
    from apps.core.enums import ActivityStatus, ActivityType, DeliveryType
    from apps.core.metrics.registry import get_metric
    from apps.frontend import work_plan_tables as tables
    from apps.frontend.views import work_plan_page as page
    from apps.monthly_work_plan.models import CountryAnnualBudgetStatus
    from apps.monthly_work_plan.services import _rvp_country_scope
    from apps.my_plan import services as my_plan
    from apps.partners.purposes import _LABELS as visit_purposes
    from apps.planning import work_plan_approval as approval
    from apps.planning.fy_policy import default_country
    from apps.ssa.plan_alignment import SsaAlignment
    from apps.mobile_feed.views import NOT_PASSED

    def choices(field: str) -> list[list[str]]:
        return [
            [str(value), str(label)]
            for value, label in Activity._meta.get_field(field).choices
        ]

    def metric(key: str) -> dict:
        spec = get_metric(key)
        return {"key": key, "label": spec.label, "unit": spec.unit.value}

    return {
        "doors": doors(),
        "query_keys_not_passed": sorted(NOT_PASSED),
        "hidden_terminal_statuses": list(page.HIDDEN_TERMINAL_STATUSES),
        "at_risk_open_statuses": list(page.AT_RISK_OPEN_STATUSES),
        "pending_approval_wfr_statuses": list(page.PENDING_APPROVAL_WFR_STATUSES),
        "wfr_labels": dict(page._WFR_LABELS),
        "flag_labels": dict(page.FLAG_LABELS),
        "view_tab_labels": dict(page.VIEW_TAB_LABELS),
        "scope_tab_labels": [list(pair) for pair in page.SCOPE_TAB_LABELS],
        "scope_labels": dict(page.SCOPE_LABELS),
        "team_scope_label": page.TEAM_SCOPE_LABEL,
        "own_scope_label": page.OWN_SCOPE_LABEL,
        "school_group_label": page.SCHOOL_GROUP_LABEL,
        "non_school_group_label": page.NON_SCHOOL_GROUP_LABEL,
        "pair_bucket_suffix": dict(page._PAIR_BUCKET_SUFFIX),
        "completed_work_statuses": list(COMPLETED_WORK_STATUSES),
        "visit_types": [str(t) for t in VISIT_TYPES],
        "training_types": [str(t) for t in TRAINING_TYPES],
        "cluster_meeting_types": [str(t) for t in CLUSTER_MEETING_TYPES],
        "statuses": [[str(v), str(label)] for v, label in ActivityStatus.choices],
        "activity_types": [[str(v), str(label)] for v, label in ActivityType.choices],
        "delivery_types": [[str(v), str(label)] for v, label in DeliveryType.choices],
        "field_choices": {
            field: choices(field)
            for field in (
                "activity_type",
                "status",
                "delivery_type",
                "focus_intervention",
                "programme_activity_type",
                "programme_delivery_mode",
            )
        },
        "visit_purpose_labels": dict(visit_purposes),
        "ssa_alignment_labels": [
            [str(v), str(label)] for v, label in SsaAlignment.choices
        ],
        "table": {
            "not_recorded": tables.NOT_RECORDED,
            "in_school_training": tables.IN_SCHOOL_TRAINING,
            "group_training": tables.GROUP_TRAINING,
            "cluster_meeting": tables.CLUSTER_MEETING,
            "school_visit": tables.SCHOOL_VISIT,
            "companion_visit_purpose": tables.COMPANION_VISIT_PURPOSE,
            "general": tables.GENERAL,
            "detail_page_param": tables.DETAIL_PAGE_PARAM,
            "open_to_its_owner": list(tables._OPEN_TO_ITS_OWNER),
            "online_training_label": ONLINE_TRAINING_LABEL,
            "detail_cluster_types": [
                *[str(t) for t in CLUSTER_MEETING_TYPES],
                "cluster_training",
                "cluster_training_ssa_collection",
            ],
        },
        "pairs": {
            "companion_gone_statuses": list(pair_costing.COMPANION_GONE_STATUSES),
            "captured_in_visit_note": pair_costing.CAPTURED_IN_VISIT_NOTE,
            "captured_in_training_note": pair_costing.CAPTURED_IN_TRAINING_NOTE,
            "online_free_note": ONLINE_FREE_NOTE,
            "online_training_types": [str(t) for t in ONLINE_TRAINING_TYPES],
            "online_mode": ONLINE,
        },
        "next_action": {
            "worked_statuses": list(my_plan._WORKED_STATUSES),
            "submit_needs_participants_types": list(
                my_plan.SUBMIT_NEEDS_PARTICIPANTS_TYPES
            ),
        },
        "day_off": {
            "awaiting_delivery": list(day_off.AWAITING_DELIVERY),
            "eid_reach_days": public_holidays._EID_REACH,
            "national_country": public_holidays.NATIONAL_COUNTRY,
            "eid_al_fitr": public_holidays.EID_AL_FITR,
            "eid_al_adha": public_holidays.EID_AL_ADHA,
            "holiday_years": [HOLIDAY_YEARS.start, HOLIDAY_YEARS.stop - 1],
            "holidays": _holidays(),
        },
        "approval": {
            "excluded_statuses": list(approval.EXCLUDED_STATUSES),
            "country": _rvp_country_scope(),
            "issues": {
                "no_activity": approval.NO_ACTIVITY_ISSUE,
                "undated": approval.UNDATED_ISSUE,
                "unassigned": approval.UNASSIGNED_ISSUE,
                "cost_missing": approval.COST_MISSING_ISSUE,
            },
            "statuses": [
                [str(v), str(label)] for v, label in CountryAnnualBudgetStatus.choices
            ],
        },
        "planning_country": default_country(),
        "strip": [metric(key) for key in STRIP_KEYS],
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write the Work Plan page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
