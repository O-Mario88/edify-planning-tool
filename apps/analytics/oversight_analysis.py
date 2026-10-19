"""An oversight page's Analysis rows: each subject read by the profile engine.

Owner, 2026-10-18: "make sure the existing analytics are integrated into the
profiles and oversights ... oversights (Partner monitoring, cluster, Core,
project monitoring, .....) and apply the detailed analytics you built
yesterday to all that apply". An oversight page lists its subjects — the
Partners it monitors, the projects it watches, the team members or the
Programme Leads it oversees — and its Analysis reads each one with
`profile_intelligence.build`, the read the subject's own profile makes, so
the two never give different answers. Where the page's own lens shows the
reader only part of a subject (a Programme Lead's share of a Partner), the
subject's scope is narrowed to that part (`narrowed`).

A missing figure reads 0, as on every profile (owner, 2026-10-18: "Leave
missing values as 0 for now"). The engine's read is a fixed number of
queries per subject, whatever the number of schools.
"""

from __future__ import annotations

from dataclasses import replace

from apps.analytics import profile_intelligence as engine

#: The four hand-over figures, in the order a hand-over moves through them
#: (the brief: "Assigned ≠ Scheduled ≠ Completed").
HANDOVER_KEYS = ("assigned", "awaiting", "scheduled", "completed")
#: The work figures a row carries for visits and for trainings.
WORK_KEYS = ("planned", "completed", "overdue")


def narrowed(scope: engine.Scope, school_ids, covers: str) -> engine.Scope:
    """``scope`` over only the schools in ``school_ids`` (a values queryset
    or a list), saying so in ``covers``."""
    return replace(
        scope, schools=scope.schools.filter(id__in=school_ids), covers=covers
    )


def row(subject_id: str, name: str, href: str, profile: dict) -> dict:
    """One subject's figures, read off its built profile."""
    portfolio = profile["portfolio"]
    execution = profile["execution"]
    ssa = profile["ssa"]
    return {
        "id": subject_id,
        "name": name,
        "href": href,
        "schools": portfolio["schools"],
        "districts": portfolio["districts"],
        "handovers": {key: portfolio["handovers"][key] for key in HANDOVER_KEYS},
        "visits": {key: execution["visits"][key] for key in WORK_KEYS},
        "trainings": {key: execution["trainings"][key] for key in WORK_KEYS},
        "ssa_now": ssa["current"],
        "ssa_change": ssa["overall"]["change"],
        "assessed": portfolio["assessed"],
        "assessable": portfolio["assessable"],
        "improved": portfolio["improved"],
        "declined": portfolio["declined"],
        # What the profile says needs attention, each with its count.
        "attention": [item for item in profile["attention"] if item],
    }


def read(
    subjects, *, fy, period: str = engine.PERIOD_YEAR, keep_empty: bool = False
) -> list[dict]:
    """``subjects`` are ``(id, name, href, scope)``: a row for each, in the
    order given. A subject whose scope holds no school is left out unless
    ``keep_empty``: a Partner or a project is listed because it holds schools
    in the reader's view, while a person holding none is what an oversight
    reader looks for, and reads 0."""
    rows = []
    for subject_id, name, href, scope in subjects:
        profile = engine.build(scope, fy, period)
        if keep_empty or profile["portfolio"]["schools"]:
            rows.append(row(subject_id, name, href, profile))
    return rows


def summarise(rows) -> dict:
    """The rows added up: every figure is its rows' total."""
    rows = list(rows)

    def total(key, inner=None):
        return sum(r[key][inner] if inner else r[key] for r in rows)

    return {
        "subjects": len(rows),
        "schools": total("schools"),
        "handovers": {key: total("handovers", key) for key in HANDOVER_KEYS},
        "visits": {key: total("visits", key) for key in WORK_KEYS},
        "trainings": {key: total("trainings", key) for key in WORK_KEYS},
        "assessed": total("assessed"),
        "assessable": total("assessable"),
        "improved": total("improved"),
        "declined": total("declined"),
        "needing_attention": sum(1 for r in rows if r["attention"]),
    }


def period_context(request) -> dict:
    """The year and the part of it an Analysis view reads, from the request,
    with the choices its filter offers: the profiles' own."""
    from apps.frontend.views.profile_views import fy_choices

    options = fy_choices()
    fy = request.GET.get("fy", "")
    if fy not in {option["value"] for option in options}:
        fy = options[0]["value"]
    period = request.GET.get("period", "")
    if period not in dict(engine.period_options()):
        period = engine.PERIOD_YEAR
    return {
        "fy": fy,
        "fy_label": next(o["label"] for o in options if o["value"] == fy),
        "fy_options": options,
        "period": period,
        "period_options": engine.period_options(),
        "period_label": engine.period_window(fy, period)[2],
    }
