"""Team and Country Planning Oversight's Analysis lens.

Owner, 2026-10-18: "make sure the existing analytics are integrated into the
profiles and oversights ... CCEO, PL, CD ... and apply the detailed analytics
you built yesterday to all that apply". Each row is a person's profile read
(apps.analytics.oversight_analysis), so a row and its profile never differ:

* Team Oversight: each member of one team over the schools they hold
  (`staff_scope`). The Programme Lead's own row is the schools they hold
  themselves — their profile reads the whole team, which is the rows added
  up — so the team's total counts no school twice. A Programme Lead reads
  their own team (or, acting, the team they act for); a country reader
  chooses the team.
* Country Planning Oversight: each Programme Lead over their whole team
  (`program_lead_scope`), the read their profile makes.
"""

from __future__ import annotations

from dataclasses import replace

from apps.analytics import oversight_analysis as analysis
from apps.analytics import profile_intelligence as engine

summarise = analysis.summarise


def _href(profile) -> str:
    return f"/staff/{profile.user_id}?tab=overview"


def _name(profile) -> str:
    return profile.user.name or profile.user.email


def leads() -> list[dict]:
    """Every Programme Lead, by name: the teams a country reader chooses
    from (`oversight_service.system_program_leads`)."""
    from apps.planning.oversight_service import system_program_leads

    return system_program_leads()


def team_lead_id(principal, program_lead_id: str | None = None) -> str | None:
    """Whose team the reader reads: their own, or a country reader's choice
    (the first Programme Lead when none is chosen)."""
    from apps.core.acting import team_lead_user_id
    from apps.frontend.views.oversight_views import is_country_reader

    if not is_country_reader(principal):
        return team_lead_user_id(principal)
    choices = leads()
    ids = {str(i) for lead in choices for i in lead["ids"]}
    if program_lead_id and str(program_lead_id) in ids:
        return str(program_lead_id)
    return str(choices[0]["id"]) if choices else None


def team_rows(
    principal,
    *,
    fy,
    period: str = engine.PERIOD_YEAR,
    program_lead_id: str | None = None,
) -> list[dict]:
    """One row per member of the team the reader reads, the Lead first."""
    from apps.accounts.models import StaffProfile
    from apps.planning.oversight_service import program_lead_members

    lead_id = team_lead_id(principal, program_lead_id)
    roster = program_lead_members(lead_id) if lead_id else []
    profiles = {
        p.id: p
        for p in StaffProfile.objects.filter(
            id__in=[member["id"] for member in roster]
        ).select_related("user")
    }

    def subjects():
        for index, member in enumerate(roster):
            profile = profiles.get(member["id"])
            if profile is None:
                continue
            scope = engine.staff_scope(profile)
            name = _name(profile)
            if index == 0:
                scope = replace(scope, covers="Own schools")
                name = f"{name} (own schools)"
            yield profile.id, name, _href(profile), scope

    return analysis.read(subjects(), fy=fy, period=period, keep_empty=True)


def lead_rows(principal, *, fy, period: str = engine.PERIOD_YEAR) -> list[dict]:
    """One row per Programme Lead over their whole team, by name."""
    from apps.accounts.models import StaffProfile

    profiles = StaffProfile.objects.filter(
        id__in=[lead["id"] for lead in leads()]
    ).select_related("user")
    ordered = sorted(profiles, key=lambda p: _name(p).lower())
    return analysis.read(
        ((p.id, _name(p), _href(p), engine.program_lead_scope(p)) for p in ordered),
        fy=fy,
        period=period,
        keep_empty=True,
    )
