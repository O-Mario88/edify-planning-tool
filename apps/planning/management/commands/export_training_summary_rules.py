"""Write the Training Summary's rules for the Go gateway.

Go builds the Training Summary lens of Team Oversight
(/team-planning-oversight/?view=trainings: oversight_views.
team_planning_oversight_view, _training_summary_context,
apps.planning.training_summary and apps.planning.training_ceilings) from the
vocabularies this command writes to
platform/backend/internal/trainingsummary/rules.json: who opens the page and
the lens, the lens strip each role is drawn, the activity types, statuses and
delivery values each figure counts, the modes of delivery, and the tones a
figure is drawn in. A change to any of them must be exported again;
apps/planning/test_training_summary_rules_export.py fails until it is, so the
two can never drift.

    python manage.py export_training_summary_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/trainingsummary/rules.json")


def _tabs(available, country: bool) -> list[dict]:
    from apps.frontend.views.oversight_views import TEAM_OVERSIGHT_PATH, _lens_tabs

    return [
        {"label": tab["label"], "href": tab["href"], "active": tab["is_active"]}
        for tab in _lens_tabs(
            TEAM_OVERSIGHT_PATH, "trainings", available, country=country
        )
    ]


def doors() -> dict:
    """What each role reaches, by the page's own gates: the page
    (require_any_page_permission and the feed's can_open_url), the lens, the
    strip drawn above it (for a reader of the country and for a team), and
    what the summary lets the role read and set."""
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.frontend.views.oversight_views import (
        TEAM_OVERSIGHT_PATH,
        is_country_reader,
        team_available_lenses,
        team_oversight_lenses,
    )
    from apps.planning import training_ceilings, training_summary

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        lenses = team_oversight_lenses(user)
        available = team_available_lenses(lenses)
        out[role.value] = {
            "page": any(
                RolePermissionService.can_view_page(user, page)
                for page in ("team_planning_oversight", "team_targets")
            ),
            "feed_opens": bool(can_open_url(user, TEAM_OVERSIGHT_PATH)),
            "trainings": lenses["trainings"],
            "country_reader": bool(is_country_reader(user)),
            "lens_tabs_country": _tabs(available, True),
            "lens_tabs_team": _tabs(available, False),
            "reads_country": training_summary.may_read_country(user),
            "sets_country_ceiling": training_ceilings.may_set_country_ceiling(user),
            # The staff_link tag's _may_open: a name links to the profile.
            "opens_staff_profile": bool(can_open_url(user, "/staff/0")),
        }
    return out


def tones() -> dict:
    """The tone of a staff cell and of the country's Total Covered, by where
    the figure stands (training_summary.Cell.tone, Row.country_tone)."""
    from apps.planning.training_summary import Cell, Row

    cells = {
        "unset": Cell(staff_id="", schools=1, limit=None),
        "above": Cell(staff_id="", schools=2, limit=1),
        "reached": Cell(staff_id="", schools=1, limit=1),
        "below": Cell(staff_id="", schools=0, limit=1),
    }
    rows = {
        "unset": Row(kind="training", key="", name="", mode="", planned=1),
        "above": Row(
            kind="training", key="", name="", mode="", planned=2, country_ceiling=1
        ),
        "reached": Row(
            kind="training", key="", name="", mode="", planned=1, country_ceiling=1
        ),
        "below": Row(
            kind="training", key="", name="", mode="", planned=0, country_ceiling=1
        ),
    }
    if any(cell.state != state for state, cell in cells.items()) or any(
        row.country_state != state for state, row in rows.items()
    ):
        raise CommandError("A figure's states changed; the tones need reading again.")
    return {
        "cell": {state: cell.tone for state, cell in cells.items()},
        "country": {state: row.country_tone for state, row in rows.items()},
    }


def summary_flag_tones() -> dict:
    """The By staff tab's Status tone, by where a row stands
    (training_ceilings.SummaryRow.flag_tone)."""
    from apps.planning.training_ceilings import SummaryRow

    def row(ceiling, group):
        return SummaryRow(
            staff_id="",
            staff_name="",
            training_id="",
            training_name="",
            intervention="",
            ceiling_id="",
            ceiling=ceiling,
            group=group,
            in_school=0,
        )

    rows = {
        "unset": row(None, 1),
        "above": row(1, 2),
        "available": row(2, 1),
        "reached": row(1, 1),
    }
    if any(r.state != state for state, r in rows.items()):
        raise CommandError("A summary row's states changed; read the tones again.")
    return {state: r.flag_tone for state, r in rows.items()}


def coverage() -> dict:
    """The Schools tab's words and statuses (apps.planning.training_coverage):
    each route's label, each status's label, order and tone, what the Show
    filter offers, the activity statuses a commitment is in progress or
    completed at, and which schools take a training (``uncovered``)."""
    from apps.core.activity_types import (
        COMPLETED_WORK_STATUSES,
        UNDER_WAY_ACTIVITY_STATUSES,
    )
    from apps.core.pagination import TABLE_PAGE_SIZE
    from apps.planning import training_coverage as tcov
    from apps.planning.country_oversight import policy
    from apps.planning.country_oversight import rules as oversight
    from apps.schools.lifecycle_service import OPERATING_STATUSES

    return {
        "route_labels": dict(tcov.ROUTE_LABELS),
        "status_labels": dict(tcov.STATUS_LABELS),
        "status_order": list(tcov.STATUS_ORDER),
        "status_tones": dict(tcov.STATUS_TONES),
        "show_options": [[key, label] for key, label in tcov.SHOW_OPTIONS],
        "figures": list(tcov.FIGURES),
        "completed_statuses": list(COMPLETED_WORK_STATUSES),
        "under_way_statuses": list(UNDER_WAY_ACTIVITY_STATUSES),
        "trained_types": list(oversight.TRAINED_TYPES),
        "excluded_duplicate_statuses": list(policy.EXCLUDED_DUPLICATE_STATUSES),
        "operating_statuses": [str(getattr(s, "value", s)) for s in OPERATING_STATUSES],
        "table_page_size": TABLE_PAGE_SIZE,
        "summary_flag_tones": summary_flag_tones(),
    }


def rules() -> dict:
    from apps.activity_catalogue.models import CatalogueActivityType, DeliveryMethod
    from apps.core.enums import ExecutorType
    from apps.core.rbac import EdifyRole
    from apps.mobile_feed import views as feed
    from apps.partners.models import PartnerAssignment
    from apps.planning import training_ceilings as tc
    from apps.planning import training_summary as ts
    from apps.planning.country_oversight import policy
    from apps.planning.country_oversight import rules as oversight
    from apps.planning.fy_policy import default_country
    from apps.planning.training_ceilings import GROUP, IN_SCHOOL
    from apps.projects.models import LIVE_PROJECT_STATUSES

    # The value partner_delivery_q filters on, read from the filter itself.
    ((field, partner_delivery),) = oversight.partner_delivery_q().children
    if field != "delivery_type":
        raise CommandError("partner_delivery_q no longer filters on delivery_type.")
    return {
        "doors": doors(),
        "tones": tones(),
        "coverage": coverage(),
        "training_types": list(tc._TRAINING_TYPES),
        "meeting_types": list(tc._MEETING_TYPES),
        "meeting_kind_training": str(tc.MeetingKind.TRAINING.value),
        "released_statuses": list(tc.RELEASED_STATUSES),
        "planned_states": sorted(policy.PLANNED_STATES),
        "partner_delivery_type": partner_delivery,
        "dated_by_partner": oversight.DATED_BY_PARTNER,
        "certified_partner_agency": ExecutorType.CERTIFIED_PARTNER_AGENCY.value,
        "unscheduled_handover_statuses": list(PartnerAssignment.UNSCHEDULED_STATUSES),
        "live_project_statuses": sorted(str(s.value) for s in LIVE_PROJECT_STATUSES),
        "catalogue_training_type": str(CatalogueActivityType.TRAINING.value),
        "mode_group": tc.DELIVERY_LABELS[GROUP],
        "mode_in_school": tc.DELIVERY_LABELS[IN_SCHOOL],
        "mode_partner_in_school": ts.PARTNER_IN_SCHOOL,
        # A project training's Mode of delivery, by its catalogue entry's
        # delivery method (_CATALOGUE_MODES, else the method's label).
        "catalogue_modes": {
            str(value): ts._CATALOGUE_MODES.get(str(value), str(label))
            for value, label in DeliveryMethod.choices
        },
        "country_reader_roles": sorted(ts.COUNTRY_READER_ROLES),
        "program_lead_role": EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        "cceo_role": EdifyRole.CCEO.value,
        "default_country": default_country(),
        # How the feed passes a page its query (apps.mobile_feed.views).
        "query_key_pattern": feed.QUERY_KEY.pattern,
        "query_keys_not_passed": sorted(feed.NOT_PASSED),
        "max_query_value": feed.MAX_QUERY_VALUE,
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True) + "\n"


class Command(BaseCommand):
    help = "Write the Training Summary's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
