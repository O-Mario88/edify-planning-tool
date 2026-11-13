"""Write the Team Performance page's rules for the Go gateway.

Go builds the Team Performance page (/team-performance/,
apps.frontend.views.team_performance_views and apps.team_performance) from
the vocabularies this command writes to
platform/backend/internal/teamperformance/rules.json: who may open the page
and how far each role reads, the statuses each figure counts, the activity
types, the report's measures (with the work each one matches), the Strategic
Milestones rows, the tabs, the dashboard's views and sorts, the summary's
columns and the delivery milestones. A change to any of them must be exported
again; apps/team_performance/test_team_performance_rules_export.py fails until
it is, so the two can never drift.

The doors are not restated: each role's answer is computed here by the gates
the page itself asks (require_page_permission("team_performance"), the
feed's can_open_url, roster.reach_of and country_targets.may_set).

    python manage.py export_team_performance_rules
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.schools.management.commands.export_school_directory_rules import (
    _role_user,
)

EXPORT_PATH = Path("platform/backend/internal/teamperformance/rules.json")


def doors() -> dict:
    from apps.core.permissions import RolePermissionService, can_open_url
    from apps.core.rbac import EdifyRole
    from apps.team_performance import country_targets, roster

    out = {}
    for role in EdifyRole:
        user = _role_user(role.value)
        out[role.value] = {
            "view_page": RolePermissionService.can_view_page(user, "team_performance"),
            "open_url": bool(can_open_url(user, "/team-performance/")),
            "reach": roster.reach_of(user),
            "set_targets": country_targets.may_set(user),
        }
    return out


def _plain(value):
    if isinstance(value, (frozenset, set)):
        return sorted(str(v) for v in value)
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return value


def _match(measure) -> dict | None:
    """The work a measure counts, read from its predicate's own closure: the
    predicate maker (``_training``, ``_visit``, ``_meeting``, ``_topics``) and
    the values it was made with. A bare lambda is named by its code, so any
    change to it changes the export."""
    match = measure.match
    if match is None:
        return None
    cells = dict(
        zip(
            match.__code__.co_freevars,
            [cell.cell_contents for cell in (match.__closure__ or ())],
        )
    )
    maker = match.__qualname__.split(".")[0]
    out = {"maker": maker, **{k: _plain(v) for k, v in cells.items()}}
    if maker == "<lambda>":
        out["names"] = list(match.__code__.co_names)
        out["consts"] = [str(c) for c in match.__code__.co_consts]
    return out


def measures_rules() -> list[dict]:
    from apps.team_performance import measures

    return [
        {
            "key": m.key,
            "label": m.label,
            "section": m.section,
            "unit": m.unit,
            "source": m.source,
            "milestone": m.milestone,
            "slice": m.slice,
            "basis": m.basis,
            "tracked": m.tracked,
            "weekly": m.weekly,
            "note": m.note,
            "people": m.people,
            "match": _match(m),
        }
        for m in measures.MEASURES
    ]


def strategic_rules() -> list[dict]:
    from apps.team_performance import strategic

    return [
        {
            "domain": r.domain,
            "title": r.title,
            "mode": r.mode,
            "kind": r.kind,
            "measures": list(r.measures),
            "plan": r.plan,
            "slice": r.slice,
            "basis": r.basis,
            "key": r.key,
            "lead": r.lead,
        }
        for r in strategic.ROWS
    ]


def rules() -> dict:
    from apps.activities.cluster_attendance import CLUSTER_TRAINING_TYPES
    from apps.core.activity_types import (
        CLUSTER_MEETING_TYPES,
        PROGRAMME_EVENT_TYPES,
        TRAINING_TYPES,
        VISIT_TYPES,
    )
    from apps.core.rbac import EdifyRole
    from apps.core_schools.package_year import DONE_STATUSES
    from apps.frontend.views import team_performance_views as views
    from apps.hr.target_distribution import CORE_FAMILY
    from apps.mobile_feed.views import NOT_PASSED
    from apps.team_performance import (
        breakdown,
        country_targets,
        ledger,
        measures,
        periods,
        report,
        roster,
        strategic,
        targets,
    )

    return {
        "doors": doors(),
        "roles": {"cceo": roster.CCEO, "lead": roster.LEAD},
        "statuses": {
            "achieved": _plain(ledger.ACHIEVED_STATUSES),
            "planned": _plain(ledger.PLANNED_STATUSES),
            "uploaded": _plain(ledger.UPLOADED_STATUSES),
            "active_school": _plain(ledger.ACTIVE_STATUSES),
            "disbursed_loan": _plain(ledger.DISBURSED_LOAN_STATUSES),
            "core_slot_done": _plain(DONE_STATUSES),
        },
        "activity_types": {
            "visit": _plain(VISIT_TYPES),
            "training": _plain(TRAINING_TYPES),
            "cluster_meeting": _plain(CLUSTER_MEETING_TYPES),
            "programme_event": _plain(PROGRAMME_EVENT_TYPES),
            "cluster_training": _plain(CLUSTER_TRAINING_TYPES),
        },
        "core_family": _plain(CORE_FAMILY),
        "measures": measures_rules(),
        "sections": list(measures.SECTIONS),
        "strategic": strategic_rules(),
        "strategic_kinds": {
            "count": strategic.COUNT,
            "rate": strategic.RATE,
            "score": strategic.SCORE,
            "untracked": strategic.UNTRACKED,
        },
        "tabs": [list(t) for t in report.TABS],
        "kinds": [list(k) for k in periods.KINDS],
        "kept": list(views.KEPT),
        "summary_kept": list(views.SUMMARY_KEPT),
        "dashboard_views": [list(v) for v in views.DASHBOARD_VIEWS],
        "sorts": [[k, v] for k, v in report.Report.SORTS.items()],
        "summary_groups": [
            [heading, [list(c) for c in cols]]
            for heading, cols in report.Report.SUMMARY_GROUPS
        ],
        "delivery": [list(d) for d in report.Report.DELIVERY],
        "status_words": {
            "achieved": report.ACHIEVED,
            "on_track": report.ON_TRACK,
            "progressing": report.PROGRESSING,
            "attention": report.ATTENTION,
        },
        "status_tones": dict(report.STATUS_TONES),
        "trackers": {k: list(v) for k, v in report.TRACKERS.items()},
        "evidence_sources": list(report.EVIDENCE_SOURCES),
        "not_placed": report.NOT_PLACED,
        "portfolio_sources": dict(report.PORTFOLIO_SOURCES),
        "breakdown_labels": dict(breakdown.LABELS),
        "region_order": list(roster.REGION_ORDER),
        "no_lead": roster.NO_LEAD,
        "rate_measurements": _plain(targets.RATE_MEASUREMENTS),
        "country_id": targets.COUNTRY_ID,
        "not_set": targets.NOT_SET,
        "eligible": targets.ELIGIBLE,
        "setters": dict(country_targets.SETTERS),
        "all_roles": [role.value for role in EdifyRole],
        # The keys the feed never hands a page (apps.mobile_feed.views).
        "not_passed_query_keys": sorted(NOT_PASSED),
    }


def rendered() -> str:
    return json.dumps(rules(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


class Command(BaseCommand):
    help = "Write the Team Performance page's rules for the Go gateway."

    def handle(self, *args, **options):
        EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        EXPORT_PATH.write_text(rendered(), encoding="utf-8")
        self.stdout.write(f"Wrote {EXPORT_PATH}")
