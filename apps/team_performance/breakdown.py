"""How the Executive Summary breaks the reader's total down.

Owner, 2026-10-24: "The Executive summary tab should have PL and his team
members instead of other PLs and Region. Instead of saying By Region, use By
CCEO for PL and for CCEO it should be by District ... for IA, CD, RPL, RVP,
HR should by region, By PL and By CCEO ... so that those can start by
viewing the higher level summary which can then be expanded into more
details."

So each reader has their own levels (`levels`):

  • a CCEO — their portfolio by District;
  • a Programme Lead — their team, member by member (By CCEO);
  • everyone else who reads the country — By Region first; a region opens
    the Programme Leads whose teams work there, and a Lead opens their CCEOs.

A region or district column counts what was achieved where its school is and
shares each officer's target across the places their schools are in
(`Report.place_split`), as the region charts always have; a Lead's or a
CCEO's column is their own figures (`Report.summary_figures`), so a team's
target is its approved allocation and a CCEO's their own.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .targets import Scope

REGION, LEAD, CCEO, DISTRICT = "region", "lead", "cceo", "district"

LABELS = {
    REGION: "Region",
    LEAD: "Programme Lead",
    CCEO: "CCEO",
    DISTRICT: "District",
}

#: The leadership levels, top first: each opens the one after it.
LEADERSHIP_LEVELS = (REGION, LEAD, CCEO)


def levels(roster) -> tuple[str, ...]:
    """The levels a reader breaks their total down by, top first."""
    if roster.own:
        return (DISTRICT,)
    if roster.narrowed:
        return (CCEO,)
    return LEADERSHIP_LEVELS


@dataclass
class Column:
    key: str
    label: str
    #: A second line: a team's region, a CCEO's team.
    sub: str = ""
    #: The query that opens what is under this column; None at the bottom.
    drill: dict | None = None
    #: measure key -> (target, achieved).
    cells: dict = field(default_factory=dict)

    def cell(self, key: str) -> dict:
        from .report import pct

        target, achieved = self.cells.get(key, (None, None))
        return {
            "label": self.label,
            "target": target,
            "achieved": achieved,
            "pct": pct(achieved, target),
        }


@dataclass
class Breakdown:
    level: str
    levels: tuple[str, ...]
    columns: list[Column]
    in_region: str = ""
    in_lead: str = ""
    in_lead_label: str = ""

    @property
    def label(self) -> str:
        return LABELS[self.level]

    @property
    def choices(self) -> list[tuple[str, str]]:
        return [(level, LABELS[level]) for level in self.levels]

    @property
    def narrowed_to(self) -> str:
        """What the columns are narrowed to, for the trail back up."""
        return self.in_lead_label or self.in_region

    def below(self) -> str | None:
        """The level under this one, or None at the bottom."""
        at = self.levels.index(self.level)
        return self.levels[at + 1] if at + 1 < len(self.levels) else None

    def bars(self, key: str) -> list[dict]:
        from .report import _bars

        return _bars(
            [
                {"label": c.label, "place": "", **_pair(c.cells.get(key))}
                for c in self.columns
            ]
        )


def _pair(cell) -> dict:
    target, achieved = cell or (None, None)
    return {"target": target, "achieved": achieved}


def resolve(report, by=None, *, in_region: str = "", in_lead: str = "") -> Breakdown:
    """The reader's breakdown at the level asked for, narrowed as asked;
    anything the reader may not ask for falls back to their top level and
    no narrowing."""
    allowed = levels(report.roster)
    level = by if by in allowed else allowed[0]
    teams = {r.key: r for r in report.roster.regions}
    narrowable = len(allowed) > 1
    in_lead = in_lead if narrowable and level == CCEO and in_lead in teams else ""
    in_region = (
        in_region
        if narrowable
        and not in_lead
        and level in (LEAD, CCEO)
        and in_region in report.ledger.regions
        else ""
    )
    cache = report.__dict__.setdefault("_breakdowns", {})
    wanted = (level, in_region, in_lead)
    if wanted not in cache:
        cache[wanted] = Breakdown(
            level=level,
            levels=allowed,
            columns=_columns(report, level, in_region, in_lead),
            in_region=in_region,
            in_lead=in_lead,
            in_lead_label=teams[in_lead].label if in_lead else "",
        )
    return cache[wanted]


def under(report, bd: Breakdown) -> Breakdown | None:
    """The level under ``bd``, narrowed alike: a region's Leads, a Lead's
    CCEOs; None at the bottom."""
    level = bd.below()
    if level is None:
        return None
    return resolve(report, level, in_region=bd.in_region, in_lead=bd.in_lead)


# ── Columns ─────────────────────────────────────────────────────────────────
def _columns(report, level, in_region, in_lead) -> list[Column]:
    if level in (REGION, DISTRICT):
        return _place_columns(report, level)
    if level == LEAD:
        return [
            _figures_column(
                report,
                team.key,
                team.label,
                report.team_scope(team),
                sub=team.place,
                drill={"by": CCEO, "in_lead": team.key},
            )
            for team in report.roster.regions
            if not in_region or in_region in _works_in(team)
        ]
    leadership = len(levels(report.roster)) > 1
    return [
        _figures_column(
            report,
            officer.staff_id,
            officer.name,
            Scope.officer(officer.staff_id),
            sub=team.label if leadership else officer.region,
        )
        for team in report.roster.regions
        if not in_lead or team.key == in_lead
        for officer in team.officers
        if not in_region or officer.region == in_region
    ]


def _works_in(team) -> set[str]:
    """The regions a team works in: where most of its schools are, and each
    of its officers' own region, so a team across two regions opens from
    both."""
    return ({team.place} | {officer.region for officer in team.officers}) - {""}


def _figures_column(report, key, label, scope, *, sub="", drill=None) -> Column:
    figures = report.summary_figures(scope, report.period.to_date)
    return Column(
        key=key,
        label=label,
        sub=sub,
        drill=drill,
        cells={
            m.key: (figures[f"{m.key}_target"], figures[m.key]) for m in report.areas()
        },
    )


def _place_columns(report, level) -> list[Column]:
    """One column a region (or district), every area split by where its
    schools are."""
    from .report import NOT_PLACED

    columns: dict[str, Column] = {}
    for measure in report.areas():
        places, target, achieved = report.place_split(measure.key, level)
        for place in places:
            column = columns.get(place)
            if column is None:
                drill = (
                    {"by": LEAD, "in_region": place}
                    if level == REGION and place != NOT_PLACED
                    else None
                )
                column = columns[place] = Column(key=place, label=place, drill=drill)
            column.cells[measure.key] = (target.get(place, 0), achieved.get(place, 0))
    # A place one area could not place keeps its spot after the others.
    return sorted(columns.values(), key=lambda c: c.key == NOT_PLACED)


__all__ = [
    "CCEO",
    "DISTRICT",
    "LABELS",
    "LEAD",
    "REGION",
    "Breakdown",
    "Column",
    "levels",
    "resolve",
    "under",
]
