"""Write Planning Oversight's and Country Oversight's doors for the Go gateway.

Go is to be the application's only backend (owner, 2026-11-11). It answers
the app's feed for Planning Oversight (/team-planning-oversight/,
apps.frontend.views.oversight_views.team_planning_oversight_view) and
Country Oversight (/country-planning-oversight/, country_planning_oversight_
view) from what this command writes to
platform/backend/internal/planningoversight/rules.json: whether the feed
opens each page, and who it opens it for. A change to any of them must be
exported again; apps/planning/test_planning_oversight_rules_export.py fails
until it is, so the two can never drift.

The doors are not restated: each role's answer is computed here by the gates
the feed and the pages themselves ask (the feed's can_open_url, the views'
require_any_page_permission / require_page_permission).

    python manage.py export_planning_oversight_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/planningoversight/rules.json")

#: Each page as the app's feed opens it: its path, its URL name, and the page
#: permissions its view's decorator accepts (any one of them).
PAGES = {
    "team": (
        "/team-planning-oversight/",
        "team_planning_oversight",
        ("team_planning_oversight", "team_targets"),
    ),
    "country": (
        "/country-planning-oversight/",
        "country_planning_oversight",
        ("country_planning_oversight",),
    ),
}


def doors() -> dict:
    """Whether each role reaches each page, by the feed's and the view's gates."""
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            key: {
                # apps.mobile_feed.views._run_page: a path the reader may not
                # open is "not available" before the view runs.
                "open": bool(can_open_url(user, path)),
                # The view's own decorator.
                "page": any(
                    RolePermissionService.can_view_page(user, name) for name in pages
                ),
            }
            for key, (path, _name, pages) in PAGES.items()
        }
    return out


def team_plan() -> dict:
    """What the Team Plan lens draws for a Programme Lead whose team has
    nothing planned in the period, from the view's own builders."""
    from apps.core.permissions import RolePermissionService
    from apps.core.rbac import EdifyRole
    from apps.frontend.views import oversight_views as views
    from apps.mobile_feed.views import NOT_PASSED
    from apps.planning import flagged_schools
    from apps.planning import oversight_service as oversight

    role = EdifyRole.COUNTRY_PROGRAM_LEAD.value
    user = _role_user(role)
    lenses = views.team_oversight_lenses(user)
    lens_tabs = views._lens_tabs(
        views.TEAM_OVERSIGHT_PATH,
        "planning",
        views.team_available_lenses(lenses),
        country=views.is_country_reader(user),
    )
    owner_tabs, _selected, _items = views._team_owner_tabs(
        oversight.OversightScope(kind="pl"), [], views.WHOLE_TEAM_TAB
    )
    kpis = views._kpi_items(oversight.summarize([]), country=False, region=False)
    return {
        "lead_role": role,
        "lens_tabs": [
            {"label": t["label"], "href": t["href"], "active": t["is_active"]}
            for t in lens_tabs
        ],
        "owner_tabs": [{"key": t["key"], "label": t["label"]} for t in owner_tabs],
        "activity_tabs": [
            {"key": t["key"], "label": t["label"]}
            for t in oversight.activity_tabs([], "all")
        ],
        "zero_kpis": [
            {
                "label": k["label"],
                "value": k["display_value"],
                "helper": k["helper"],
                "tone": k["tone"],
            }
            for k in kpis
        ],
        "evidence_link": RolePermissionService.can_view_page(user, "evidence_center"),
        "live_activity_statuses": list(oversight.LIVE_ACTIVITY_STATUSES),
        "not_planned_statuses": list(flagged_schools.NOT_PLANNED_STATUSES),
        "filter_keys": list(oversight.FILTER_KEYS),
        "query_keys_not_passed": sorted(NOT_PASSED),
        "items": team_items(),
        "flagged": flagged(),
        "coverage": coverage(),
        "readers": readers(),
        # The tiles' labels on the lenses that read many Programme Leads.
        "lens_kpi_labels": {
            lens: [
                k["label"]
                for k in views._kpi_items(
                    oversight.summarize([]),
                    country=lens == "country",
                    region=lens == "region",
                )
            ]
            for lens in ("country", "region")
        },
    }


def readers() -> dict:
    """What the Team Plan lens draws differently for each role its door
    opens for: the scope it reads (resolve_oversight_scope), the lens strip,
    whether the Send controls show (may_delegate), the Evidence Centre link,
    and which names link to their record (can_open_url, the link tags).

    The lens strip is drawn with COVERAGE_LENS_ROLES naming the Regional Vice
    President as it means to, as the portfolio lens is (owner, 2026-11-13:
    "Can you fix those from the go side"; intended.json go-fix-rvp-lens), so
    the RVP's Team Plan offers the lenses Go draws for it."""
    from unittest import mock

    from apps.frontend.views import oversight_views
    from apps.planning.management.commands.export_oversight_portfolio_rules import (
        _MEANT_ROLE,
        _MISSPELT_ROLE,
    )

    meant = frozenset(
        _MEANT_ROLE if role == _MISSPELT_ROLE else role
        for role in oversight_views.COVERAGE_LENS_ROLES
    )
    with (
        mock.patch.object(oversight_views, "COVERAGE_LENS_ROLES", meant),
        mock.patch.object(oversight_views, "PORTFOLIO_LENS_ROLES", meant),
    ):
        return _readers()


def _readers() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.frontend.views import oversight_views as views
    from apps.planning import oversight_service as oversight

    country_roles, region_roles = oversight._lens_roles()
    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        if not can_open_url(user, views.TEAM_OVERSIGHT_PATH):
            continue
        scope = (
            "country"
            if role.value in country_roles
            else ("region" if role.value in region_roles else "pl")
        )
        lenses = views.team_oversight_lenses(user)
        tabs = views._lens_tabs(
            views.TEAM_OVERSIGHT_PATH,
            "planning",
            views.team_available_lenses(lenses),
            country=views.is_country_reader(user),
        )
        out[role.value] = {
            "scope": scope,
            "planning": bool(lenses["planning"]),
            # Every lens the reader holds, which decides the lens a ?view=
            # it does not hold falls back to (team_planning_oversight_view).
            "lenses": {key: bool(value) for key, value in sorted(lenses.items())},
            "lens_tabs": [
                {"label": t["label"], "href": t["href"], "active": t["is_active"]}
                for t in tabs
            ],
            "may_delegate": views.may_delegate(
                user, country=scope == "country", region=scope == "region"
            ),
            "evidence_link": RolePermissionService.can_view_page(
                user, "evidence_center"
            ),
            "open_activity": role.value != EdifyRole.PROGRAM_ACCOUNTANT.value
            and bool(can_open_url(user, "/activities/0")),
            "open_school": bool(can_open_url(user, "/schools/0")),
            "open_district": bool(can_open_url(user, "/districts/0")),
            "open_cluster": bool(can_open_url(user, "/clusters/0")),
        }
    return out


def team_items() -> dict:
    """The vocabularies build_items, risk_service.annotate, the four tables
    (_partition_owner_groups_by_stream, _officer_panel_body.html) and the
    completion columns read, for the Team Plan lens with work in it."""
    from apps.activities import completion_columns as completion
    from apps.activities.online_training import ONLINE, ONLINE_TRAINING_TYPES
    from apps.activities.pair_costing import COMPANION_GONE_STATUSES
    from apps.budget.costing import (
        CLUSTER_MEALS_RATE_KEY,
        GROUP_TRAINING_MEALS_RATE_KEY,
    )
    from apps.core.activity_types import (
        CLUSTER_MEETING_TYPES,
        COMPLETED_WORK_STATUSES,
        TRAINING_TYPES,
        VISIT_TYPES,
    )
    from apps.partners.purposes import _LABELS as PURPOSE_LABELS
    from apps.planning import oversight_service as oversight
    from apps.planning import risk_service as risk
    from apps.planning.staff_plan import PARTNER_ONLY_STATUSES
    from apps.projects.models import GENERAL_INTERVENTION
    from apps.schools.lifecycle_models import OPERATING_STATUSES

    return {
        "visit_types": sorted(VISIT_TYPES),
        "training_types": sorted(TRAINING_TYPES),
        "cluster_meeting_types": sorted(CLUSTER_MEETING_TYPES),
        "families": [
            {"key": key, "types": sorted(types)}
            for key, _label, types in oversight.ACTIVITY_FAMILIES
        ],
        "partner_only_statuses": list(PARTNER_ONLY_STATUSES),
        "completed_work_statuses": sorted(COMPLETED_WORK_STATUSES),
        "officer_completed_statuses": sorted(completion.OFFICER_COMPLETED_STATUSES),
        "never_overdue": sorted(completion._NEVER_OVERDUE),
        "companion_gone_statuses": list(COMPANION_GONE_STATUSES),
        "purpose_labels": dict(sorted(PURPOSE_LABELS.items())),
        "general_intervention": GENERAL_INTERVENTION,
        "operating_statuses": list(OPERATING_STATUSES),
        "online_training_types": sorted(ONLINE_TRAINING_TYPES),
        "online": ONLINE,
        "cluster_meals_rate_key": CLUSTER_MEALS_RATE_KEY,
        "group_training_meals_rate_key": GROUP_TRAINING_MEALS_RATE_KEY,
        "words": {
            "not_in_sf": completion.NOT_IN_SF,
            "finished_early": completion.FINISHED_EARLY,
            "missing_sf": completion.MISSING_SF,
            "missing_evidence": completion.MISSING_EVIDENCE,
            "missing_both": completion.MISSING_BOTH,
        },
        "risk": {
            "post_field_statuses": list(risk._POST_FIELD_STATUSES),
            "evidence_expected_statuses": list(risk._EVIDENCE_EXPECTED_STATUSES),
            "salesforce_expected_statuses": list(risk._SALESFORCE_EXPECTED_STATUSES),
            "ia_settled_statuses": list(risk._IA_SETTLED_STATUSES),
            "payment_settled_statuses": list(risk._PAYMENT_SETTLED_STATUSES),
            "evidence_grace_days": risk.EVIDENCE_GRACE_DAYS,
            "reschedule_limit": risk.RESCHEDULE_LIMIT,
            "ia_verification_grace_days": risk.IA_VERIFICATION_GRACE_DAYS,
            "payment_grace_days": risk.PAYMENT_GRACE_DAYS,
            # The record drawer's unscheduled hand-over (_partner_not_scheduled).
            "partner_schedule_grace_days": risk.PARTNER_SCHEDULE_GRACE_DAYS,
        },
    }


def coverage() -> dict:
    """The Schools & Coverage lens (coverage_service, school_status,
    coverage_workspace.html)."""
    from apps.activities.cluster_attendance import SCHOOL_TRAINING_TYPES
    from apps.core.activity_types import CLUSTER_MEETING_TYPES, VISIT_TYPES
    from apps.partners.models import PartnerAssignment
    from apps.partners.support_responsibility import LEFT_PARTNER_STATUSES
    from apps.planning import coverage_service as cov
    from apps.planning import oversight_service as oversight
    from apps.planning.country_oversight.rules import TRAINED_TYPES
    from apps.schools import school_status as st
    from apps.schools.lifecycle_models import OPERATING_STATUSES

    return {
        "row_limit": cov.ROW_LIMIT,
        # The hand-overs a Partner has not dated (_unscheduled_assignments_
        # in_scope): these statuses, unless left_partner_q holds.
        "assignment_statuses": [
            *PartnerAssignment.UNSCHEDULED_STATUSES,
            oversight._RETURNED_ASSIGNMENT_STATUS,
        ],
        "left_partner_statuses": sorted(LEFT_PARTNER_STATUSES),
        "ia_status_labels": dict(sorted(cov.IA_STATUS_LABELS.items())),
        "budget": {
            "no_cost": cov.BUDGET_NO_COST,
            "created": cov.BUDGET_CREATED,
            "in_weekly_request": cov.BUDGET_IN_WEEKLY_REQUEST,
            "in_school_visit": cov.BUDGET_IN_SCHOOL_VISIT,
        },
        "dead_statuses": sorted(st.DEAD_STATUSES),
        "pending_approval_statuses": sorted(st.PENDING_APPROVAL_STATUSES),
        "cluster_session_types": sorted(st.CLUSTER_SESSION_TYPES),
        "cluster_meeting_types": sorted(str(t) for t in CLUSTER_MEETING_TYPES),
        "visit_types": sorted(str(t) for t in VISIT_TYPES),
        "school_training_types": [str(t) for t in SCHOOL_TRAINING_TYPES],
        "trained_types": list(TRAINED_TYPES),
        "operating_statuses": list(OPERATING_STATUSES),
        "visit_labels": dict(sorted(st.VISIT_LABELS.items())),
        "visit_tones": dict(sorted(st.VISIT_TONES.items())),
        "visit_states": dict(sorted(st._STATUS_STATE.items())),
        "visit_precedence": list(st._PRECEDENCE),
        "reasons": {
            "not_clustered": st.REASON_NOT_CLUSTERED,
            "canceled": st.REASON_CANCELED,
            "returned": st.REASON_RETURNED,
            "no_training": st.REASON_NO_TRAINING,
            "not_required": st.REASON_NOT_REQUIRED,
        },
    }


def flagged() -> dict:
    """What team_flagged_schools and urgent_attention's classifier read."""
    from apps.activities.cluster_attendance import (
        CLUSTER_CREDIT_STATUSES,
        CLUSTER_TRAINING_TYPES,
        SCHOOL_TRAINING_TYPES,
    )
    from apps.core.activity_types import COMPLETED_WORK_STATUSES
    from apps.planning import urgent_attention as urgent
    from apps.planning.action_models import ACTIVE_STATES
    from apps.planning.country_oversight.rules import TRAINED_TYPES
    from apps.targets.my_targets import IA_VERIFIED_STATUSES

    return {
        "precedence": dict(sorted(urgent._PRECEDENCE.items())),
        "visit_types": list(urgent._VISIT_TYPES),
        "training_types": list(urgent._TRAINING_TYPES),
        "ia_verified_statuses": list(IA_VERIFIED_STATUSES),
        "school_training_types": [str(t) for t in SCHOOL_TRAINING_TYPES],
        "school_training_done_statuses": sorted(COMPLETED_WORK_STATUSES),
        "cluster_training_types": [str(t) for t in CLUSTER_TRAINING_TYPES],
        "cluster_credit_statuses": list(CLUSTER_CREDIT_STATUSES),
        "trained_types": list(TRAINED_TYPES),
        "active_action_states": sorted(str(s) for s in ACTIVE_STATES),
    }


def rules() -> dict:
    from apps.mobile_feed.views import NATIVE_PAGES

    return {
        "pages": {
            key: {"path": path, "feed_opens_page": name in NATIVE_PAGES}
            for key, (path, name, _pages) in PAGES.items()
        },
        "doors": doors(),
        "team_plan": team_plan(),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write Planning Oversight's and Country Oversight's doors for Go."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
