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

from apps.analytics import oversight_analysis as analysis
from apps.analytics import profile_intelligence as engine

summarise = analysis.summarise


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

    def scope_of(partner):
        scope = engine.partner_scope(partner)
        if team_q is None:
            return scope
        return analysis.narrowed(
            scope,
            held.filter(partner=partner).values("school_id"),
            "Assigned portfolio in your team",
        )

    return analysis.read(
        (
            (p.id, p.name, f"/partners/{p.id}?tab=overview", scope_of(p))
            for p in partners
        ),
        fy=fy,
        period=period,
    )
