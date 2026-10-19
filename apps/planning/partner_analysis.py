"""Partner Monitoring's Analysis: each Partner the reader monitors, analysed.

Owner, 2026-10-18: "make sure the existing analytics are integrated into the
profiles and oversights ... oversights (Partner monitoring, ...) and apply the
detailed analytics you built yesterday to all that apply".

A Partner's row is `profile_intelligence.build` over its assigned portfolio —
the read its own profile makes, so the two never give different answers —
narrowed to the hand-overs the reader's monitoring page shows
(`partner_oversight_service._assignment_team_q`). The country therefore reads
each Partner's profile figures, and a Programme Lead or CCEO the same figures
over their own part of it. Assigned, awaiting the Partner's date, scheduled
and completed stay four figures (the brief: "Assigned ≠ Scheduled ≠
Completed"); a missing figure reads 0, as on every profile (owner,
2026-10-18: "Leave missing values as 0 for now").

The engine's read is a fixed number of queries per Partner, whatever the
number of schools.
"""

from __future__ import annotations

from dataclasses import replace

from apps.analytics import profile_intelligence as engine

#: The four hand-over figures, in the order a hand-over moves through them.
HANDOVER_KEYS = ("assigned", "awaiting", "scheduled", "completed")
#: The work figures a row carries for visits and for trainings.
WORK_KEYS = ("planned", "completed", "overdue")


def partner_rows(principal, *, fy, period: str = engine.PERIOD_YEAR) -> list[dict]:
    """One row per Partner holding a school in the reader's lens, by name."""
    from apps.partners.models import Partner, PartnerAssignment
    from apps.planning.partner_oversight_service import (
        _assignment_team_q,
        _resolve_scope,
    )

    lens = _resolve_scope(principal)
    if lens["kind"] == "team" and not lens["staff_ids"]:
        return []
    team_q = _assignment_team_q(lens)
    held = PartnerAssignment.objects.filter(school__isnull=False).exclude(
        status__in=PartnerAssignment.RELEASED_STATUSES
    )
    if team_q is not None:
        held = held.filter(team_q)
    partners = Partner.objects.filter(
        id__in=held.values("partner_id"), deleted_at__isnull=True
    ).order_by("name")
    rows = []
    for partner in partners:
        scope = engine.partner_scope(partner)
        if team_q is not None:
            scope = replace(
                scope,
                schools=scope.schools.filter(
                    id__in=held.filter(partner=partner).values("school_id")
                ),
                covers="Assigned portfolio in your team",
            )
        profile = engine.build(scope, fy, period)
        if profile["portfolio"]["schools"]:
            rows.append(_row(partner, profile))
    return rows


def _row(partner, profile: dict) -> dict:
    portfolio = profile["portfolio"]
    execution = profile["execution"]
    ssa = profile["ssa"]
    return {
        "id": partner.id,
        "name": partner.name,
        "href": f"/partners/{partner.id}?tab=overview",
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


def summarise(rows) -> dict:
    """The rows added up: every figure is its rows' total."""
    rows = list(rows)

    def total(key, inner=None):
        return sum(r[key][inner] if inner else r[key] for r in rows)

    return {
        "partners": len(rows),
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
