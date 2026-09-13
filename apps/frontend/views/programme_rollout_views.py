"""Programme Rollout, the Programme Lead's page (owner, 2026-09-13).

"Coordinate the rollout of training programs, school self-assessments (SSA),
and spiritual transformation interventions" — one of the five
responsibilities in the Programme Lead's role description, and until now the
only one with no page of its own. The page is a rail of three tabs
(?view=trainings|ssa|spiritual) under one header and filter bar, in the grammar
of the role dashboards: a tab swaps only its panel, carries the year, and is a
real URL other pages link to (/programme-rollout?view=ssa).

Every figure, the team and the refusals come from
apps.analytics.programme_rollout_service; this module renders them. The page is
a read: the only controls are links to the record that answers a row (the
activity, the school, Team Oversight for an officer) and read-only school
lists, so a Programme Lead supervises the team's rollout without a write
control on a supervised record (SEC-01). KPI tiles go through the reconciled
registry (apps/core/metrics/programme_rollout_metrics.py).
"""

from __future__ import annotations

from urllib.parse import urlencode

from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from apps.analytics import programme_rollout_service as rollout
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.fy import fy_options
from apps.core.interventions import intervention_abbr
from apps.core.metrics import render_precomputed_metric_for_source
from apps.core.permissions import require_page_permission
from apps.frontend.views.dashboard_view_state import dashboard_view_tabs

METRIC_SOURCE = "apps.frontend.views.programme_rollout_views:_metric"
PANEL_ID = "programme-rollout-view"
SCHOOLS_URL = f"{rollout.PAGE_URL}/schools"

TABS = [
    (
        "trainings",
        "Trainings",
        "Training programmes planned, delivered and observed across your team",
    ),
    (
        "ssa",
        # The rail's tabs are equal 9.5rem chips (platform.css); the full name
        # is the tab's description.
        "Self-Assessments",
        "School Self-Assessments: which portfolio schools have a confirmed SSA this year, and which still need one",
    ),
    (
        "spiritual",
        "Spiritual Formation",
        "Spiritual transformation — Christlike Behaviour and the Word of God: scores, responses and programmes",
    ),
]


def _metric(label: str, value, helper: str, tone="info", hx_get=None) -> dict:
    presentation = {"helper": helper, "tone": tone}
    if hx_get:
        presentation["hx_get"] = hx_get
    return render_precomputed_metric_for_source(
        METRIC_SOURCE, label, value, **presentation
    )


def _plural(count, word: str, plural: str | None = None) -> str:
    return f"{count} {word if count == 1 else (plural or word + 's')}"


# ── Tiles ────────────────────────────────────────────────────────────────────
def _training_metrics(data: dict, query: str) -> list[dict]:
    summary = data["summary"]
    portfolio = summary["portfolio"]
    untrained = portfolio - summary["schools_trained"]
    return [
        _metric(
            "Trainings Delivered",
            summary["delivered"],
            f"of {summary['planned']} planned · {summary['in_review']} held, in review",
            "success" if summary["delivered"] else "info",
        ),
        _metric(
            "Portfolio Schools Trained",
            summary["schools_trained"] if portfolio else "—",
            f"of {portfolio} · {untrained} not yet trained"
            if portfolio
            else "No schools in the portfolio",
            "warning" if untrained else "success",
            hx_get=f"{SCHOOLS_URL}?kind=not_trained&{query}" if untrained else None,
        ),
        _metric(
            "Teachers and Leaders Trained",
            summary["teachers"] + summary["leaders"],
            f"{summary['teachers']} teachers · {summary['leaders']} leaders",
        ),
        _metric(
            "Trainings Due in 30 Days",
            summary["upcoming"],
            "scheduled across the team",
        ),
        _metric(
            "Open Training Recommendations",
            summary["open_recommendations"],
            "strengthen or replace, not yet answered",
            "warning" if summary["open_recommendations"] else "info",
        ),
    ]


def _ssa_metrics(data: dict, query: str) -> list[dict]:
    summary = data["summary"]
    coverage = summary["coverage"]

    def drawer(state, count):
        return f"{SCHOOLS_URL}?kind=ssa_{state}&{query}" if count else None

    return [
        _metric(
            "Schools With a Confirmed SSA",
            summary["confirmed"] if summary["portfolio"] else "—",
            f"of {summary['portfolio']} portfolio schools"
            + (f" · {coverage}%" if coverage is not None else ""),
            "success" if coverage and coverage >= 80 else "warning",
            hx_get=drawer(rollout.SSA_CONFIRMED, summary["confirmed"]),
        ),
        _metric(
            "SSAs Awaiting IA Verification",
            summary["awaiting"],
            "collected, not yet confirmed",
            hx_get=drawer(rollout.SSA_AWAITING, summary["awaiting"]),
        ),
        _metric(
            "SSA Collections Scheduled",
            summary["scheduled"],
            "planned, or handed to a partner",
            hx_get=drawer(rollout.SSA_SCHEDULED, summary["scheduled"]),
        ),
        _metric(
            "Schools With No SSA Planned",
            summary["not_planned"],
            "no collection planned this year",
            "danger" if summary["not_planned"] else "success",
            hx_get=drawer(rollout.SSA_NOT_PLANNED, summary["not_planned"]),
        ),
    ]


def _spiritual_metrics(data: dict, query: str) -> list[dict]:
    summary = data["summary"]
    previous = summary["prev_fy"]
    tiles = []
    for score in data["scores"]:
        if score["delta"] is not None:
            helper = f"{score['delta']:+.1f} vs FY {previous}"
        elif score["score"] is not None:
            helper = "no earlier cycle to compare"
        else:
            helper = "no confirmed SSA yet"
        tiles.append(
            _metric(
                f"Team {score['abbr']} Average",
                f"{score['score']:.1f}" if score["score"] is not None else "—",
                helper,
                score["tone"] if score["score"] is not None else "info",
            )
        )
    cb, wog = (intervention_abbr(code) for code in rollout.SPIRITUAL_INTERVENTIONS)
    biblical = summary["biblical"]
    tiles += [
        _metric(
            f"Schools Weak in {cb} or {wog} Without a Plan",
            summary["weak_without_plan"],
            f"of {summary['weak_schools']} with {cb} or {wog} among the three weakest",
            "danger" if summary["weak_without_plan"] else "success",
        ),
        _metric(
            "Spiritual Programmes Delivered",
            summary["programmes_delivered"],
            f"Christian Transformation, CC-SEL and camps · "
            f"{summary['programmes_to_deliver']} still to deliver",
        ),
        _metric(
            "Biblical Integration Rating",
            f"{biblical} / 4" if biblical is not None else "—",
            f"across {_plural(summary['observed'], 'Regional Lead observation')}",
            "success" if biblical and biblical >= 3 else "info",
        ),
    ]
    return tiles


METRIC_BUILDERS = {
    "trainings": _training_metrics,
    "ssa": _ssa_metrics,
    "spiritual": _spiritual_metrics,
}


def _notice(scope: dict) -> dict | None:
    if scope["support_view"]:
        if not scope["has_lead"]:
            return {
                "tone": "info",
                "text": "No Programme Lead is set up yet, so there is no team to show.",
            }
        return {
            "tone": "info",
            "text": (
                f"You are reading {scope['lead_name']}'s team as they see it. "
                "Choose another Programme Lead in the filters."
            ),
        }
    if not scope["officer_count"]:
        return {
            "tone": "warning",
            "text": (
                "No officers are assigned to you yet, so this page shows your own "
                "portfolio only. HR records who you supervise on the staff profile."
            ),
        }
    return None


# ── Pages ────────────────────────────────────────────────────────────────────
@require_page_permission("programme_rollout")
@require_http_methods(["GET"])
def programme_rollout_view(request):
    """The team's rollout of trainings, SSAs and spiritual transformation."""
    user = request.user
    is_admin = user.active_role == rollout.ADMIN
    view = rollout.clean_view(request.GET.get("view"))
    fy = rollout.clean_fy(request.GET.get("fy"))
    requested_lead = (request.GET.get("lead") or "").strip() if is_admin else ""
    data = rollout.get_rollout(user, view=view, fy=fy, lead=requested_lead)
    scope = data["scope"]
    lead = scope["lead_staff_id"] if is_admin else ""
    carried = {"fy": fy, **({"lead": lead} if lead else {})}
    query = urlencode(carried)
    body = data[view]
    context = {
        "view": view,
        "dashboard_view": view,
        "fy": fy,
        "fy_options": fy_options(),
        "lead": lead,
        "lead_options": scope["leads"] if is_admin else [],
        "scope": scope,
        "rollout": body,
        "metrics": METRIC_BUILDERS[view](body, query),
        "carry_query": query,
        "schools_url": SCHOOLS_URL,
        "notice": _notice(scope),
        "dashboard_tabs": dashboard_view_tabs(
            request,
            active=view,
            panel_id=PANEL_ID,
            view_template="partials/programme_rollout/view.html",
            tabs=TABS,
            base_url=rollout.PAGE_URL,
            keep=("fy", "lead"),
            values=carried,
        ),
    }
    if request.headers.get("HX-Target") == f"{PANEL_ID}-shell":
        return render(
            request,
            "partials/dashboards/_view_tabs.html",
            {**context, "dashboard_tabs_inner": True},
        )
    return render(request, "pages/programme_rollout/index.html", context)


@require_page_permission("programme_rollout")
@require_http_methods(["GET"])
def school_list_drawer(request):
    """The schools behind a figure, read-only. An officer or cluster outside
    the lead's team is refused with the reason, never an empty list."""
    template = "partials/programme_rollout/school_list_drawer.html"
    try:
        result = rollout.school_list(
            request.user,
            kind=(request.GET.get("kind") or "").strip(),
            fy=request.GET.get("fy"),
            member=request.GET.get("member"),
            cluster=request.GET.get("cluster"),
            lead=(request.GET.get("lead") or "").strip() or None,
        )
    except (BadRequest, Forbidden, NotFoundError) as exc:
        return render(
            request,
            template,
            {
                "title": "Schools",
                "subtitle": "Programme Rollout",
                "refusal": str(getattr(exc, "detail", exc)),
            },
        )
    return render(request, template, result)
