"""The six tabs of the Team Performance page, each from the same read.

Owner, 2026-10-20: the FY27 Weekly Report workbook's Executive Summary (the
first tab and the default), Weekly Report – Country, Strategic Milestones &
Trackers, the CCEO Performance & Milestone Dashboard (the workbook's
Revised Performance Template, per CCEO), the {Month} {Year} Summary and Core
Visit & Training. Every figure is a `Ledger` count against a `TargetBook`
target over a `ReportPeriod` window (docs/team-performance-report.md).

The period filter (a week, a month or a quarter) applies where a tab reads a
period: the Executive Summary, the Weekly Report, Strategic Milestones and the
CCEO dashboard. The summary tab reads its month; Core Visits & Training is
the package to date.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from . import measures
from .ledger import Ledger
from .periods import ReportPeriod
from .roster import NO_LEAD, Roster
from .targets import ELIGIBLE, NOT_SET, Scope, Target, TargetBook

#: (key, label, the filter it reads: "period", "month" or "").
TABS = (
    ("summary", "Executive Summary", "period"),
    ("weekly", "Detailed Country Report", "month"),
    ("milestones", "Strategic Milestones", "period"),
    ("dashboard", "CCEO Officer Performance & Milestones", "month"),
    ("month", "{month} Summary", "month"),
    ("core", "Core Visits & Training", ""),
)

ACHIEVED, ON_TRACK, PROGRESSING, ATTENTION = (
    "Achieved",
    "On Track",
    "Progressing",
    "Needs Attention",
)
STATUS_TONES = {
    ACHIEVED: "success",
    ON_TRACK: "success",
    PROGRESSING: "info",
    ATTENTION: "warning",
}


def status(share: float | None, *, running: bool = False) -> str:
    """The workbook's rule: 100% Achieved (On Track while running), 75%
    Progressing, below that Needs Attention."""
    if share is None:
        return ""
    if share >= 100:
        return ON_TRACK if running else ACHIEVED
    if share >= 75:
        return PROGRESSING
    return ATTENTION


def pct(achieved, target) -> float | None:
    if achieved is None or not target:
        return None
    return round(100.0 * achieved / target, 1)


def _var(achieved, target):
    if achieved is None or target is None:
        return None
    return achieved - target


@dataclass(frozen=True)
class Cell:
    target: float | None
    achieved: int | None
    #: The work planned for the same window; None where nothing is planned.
    planned: int | None = None

    @property
    def variance(self):
        return _var(self.achieved, self.target)

    @property
    def pct(self):
        return pct(self.achieved, self.target)


class Report:
    """One reader's report for one period: the reads every tab shares."""

    def __init__(
        self, ledger: Ledger, book: TargetBook, roster: Roster, period: ReportPeriod
    ):
        self.ledger = ledger
        self.book = book
        self.roster = roster
        self.period = period

    @classmethod
    def build(cls, user, period: ReportPeriod) -> Report:
        from . import roster as roster_module

        ledger = Ledger.load(period.fy, owners=roster_module.visible_staff(user))
        return cls(
            ledger,
            TargetBook.load(period.fy),
            roster_module.build(user, ledger),
            period,
        )

    # ── Scopes ──────────────────────────────────────────────────────────────
    def owners(self, scope: Scope):
        """The officers whose schools a scope counts; None is everyone."""
        if scope.kind == "country":
            if self.roster.narrowed:
                return {o.staff_id for o in self.roster.officers}
            return None
        return set(scope.staff)

    def home(self) -> Scope:
        """The reader's widest scope: the country; a Programme Lead's own
        team, whose targets are its approved allocations; a CCEO's own row."""
        if self.roster.own and self.roster.officers:
            return Scope.officer(self.roster.officers[0].staff_id)
        if self.roster.lead:
            team = self.roster.region(self.roster.lead)
            return Scope.region(self.roster.lead, team.staff_ids if team else set())
        return Scope.country()

    def team_scope(self, region) -> Scope:
        """A team's row: the team, or, for a CCEO reading their own, just
        them — so a team's target is never set against one officer's work."""
        if self.roster.own and region.officers:
            return Scope.officer(region.officers[0].staff_id)
        return Scope.region(region.key, region.staff_ids)

    def scopes(self) -> list[tuple[str, str, Scope]]:
        """(key, label, scope) for the scope picker: the country, each region,
        each officer — or just the reader, for a CCEO."""
        if self.roster.own:
            return [
                (o.staff_id, o.name, Scope.officer(o.staff_id))
                for o in self.roster.officers
            ]
        if self.roster.narrowed:
            out = []
        else:
            out = [("country", "Country", Scope.country())]
        for region in self.roster.regions:
            out.append(
                (
                    f"region:{region.key}",
                    f"{region.label} region",
                    Scope.region(region.key, region.staff_ids),
                )
            )
        for officer in self.roster.officers:
            out.append(
                (officer.staff_id, officer.name, Scope.officer(officer.staff_id))
            )
        return out

    def scope(self, key: str | None) -> tuple[str, str, Scope]:
        options = self.scopes()
        if not options:
            return ("country", "Country", Scope.country())
        return next((o for o in options if o[0] == key), options[0])

    # ── One figure ──────────────────────────────────────────────────────────
    def count(self, key: str, scope: Scope, window) -> int | None:
        return self.ledger.count(key, self.owners(scope), *window)

    def planned(self, key: str, scope: Scope, window) -> int | None:
        return self.ledger.planned(key, self.owners(scope), *window)

    def eligible(self, measure: measures.Measure, scope: Scope) -> int | None:
        if not measure.basis:
            return None
        return self.ledger.portfolio(self.owners(scope), measure.basis)

    def target(self, measure, scope: Scope) -> Target:
        return self.book.target(measure, scope, eligible=self.eligible(measure, scope))

    def row(self, measure: measures.Measure, scope: Scope) -> dict:
        """One Detailed Country Report row, in the workbook's columns: the
        chosen month, each quarter cumulative from October, and the year to
        date against the annual target. Planned is the work in the plans for
        the same window — the whole year's for the annual band."""
        period = self.period
        key = measure.key
        target = self.target(measure, scope)
        level = target.source == ELIGIBLE  # a coverage level, not phased
        month = Cell(
            None if level else target.month(period.month),
            self.count(key, scope, period.month_span),
            self.planned(key, scope, period.month_span),
        )
        quarters = []
        for q in (1, 2, 3, 4):
            window = period.through(q * 3)
            if not period.quarter_started(q):
                # Not begun: nothing achieved yet, but work may be booked.
                planned = self.planned(key, scope, window)
                quarters.append({"q": q, "future": True, "planned": planned})
                continue
            q_target = target.annual if level else target.through(q * 3)
            cell = Cell(
                q_target,
                self.count(key, scope, window),
                self.planned(key, scope, window),
            )
            quarters.append({"q": q, "future": False, "cell": cell})
        year = Cell(
            target.annual,
            self.count(key, scope, period.now),
            self.planned(key, scope, (period.fy_start, period.fy_end)),
        )
        return {
            "measure": measure,
            "target": target,
            "month": month,
            "quarters": quarters,
            "year": year,
            "status": status(year.pct, running=period.today < period.fy_end),
            "phased": target.months is not None,
        }

    # ── Executive Summary ───────────────────────────────────────────────────
    def areas(self) -> list[measures.Measure]:
        """The Executive Summary's target areas: every tracked row with a
        target — a plan milestone or its eligible schools — in the report's
        section order (owner, 2026-10-21: "Add training target, core school
        visits, School visits, ....all targets that are tracked"). Data
        collected is left out: its only target would be the portfolio."""
        rows = [
            m
            for m in measures.MEASURES
            if m.tracked and (m.milestone or m.basis) and m.key != "dc_data"
        ]
        order = {section: n for n, section in enumerate(measures.SECTIONS)}
        return sorted(rows, key=lambda m: order[m.section])

    @staticmethod
    def area_label(measure, all_areas) -> str:
        """A row's label, with "– Core" or "– Client" where a Core and a
        client row share it."""
        shared = sum(1 for m in all_areas if m.label == measure.label) > 1
        if shared and measure.slice:
            return f"{measure.label} – {measure.slice.title()}"
        return measure.label

    def summary_figures(self, scope: Scope, window) -> dict:
        owners = self.owners(scope)
        led = self.ledger
        figures = {
            "portfolio": led.portfolio(owners, as_of=window[1]),
            "active": led.portfolio(owners, "active", as_of=window[1]),
            "dc_data": self.count("dc_data", scope, window),
            "dc": self.count("dc_clubs", scope, window),
        }
        for measure in self.areas():
            key = measure.key
            target = self.target(measure, scope).annual
            achieved = self.count(key, scope, window)
            figures[key] = achieved
            figures[f"{key}_target"] = target
            figures[f"{key}_pct"] = pct(achieved, target)
        figures["inactive"] = figures["portfolio"] - figures["active"]
        figures["active_pct"] = pct(figures["active"], figures["portfolio"])
        figures["dc_pct"] = pct(figures["dc"], figures["dc_data"])
        return figures

    def executive_summary(self) -> dict:
        """The summary's tiles and its table of every target area. The charts
        load a section at a time (`section_charts`), as the reader reaches
        them: drawn all at once they would pass the platform's page-size
        budget."""
        period = self.period
        home = self.home()
        now = self.summary_figures(home, period.to_date)
        before = self.summary_figures(home, period.before)
        regions = self._team_figures()
        all_areas = self.areas()
        counted = ["portfolio", "active", "dc_data", "dc"]
        counted += [m.key for m in all_areas]
        change = {
            key: now[key] - before[key]
            for key in counted
            if isinstance(now[key], int) and isinstance(before[key], int)
        }
        sections: dict[str, list[dict]] = {}
        for measure in all_areas:
            area = self._area(measure, all_areas, now, regions)
            area["change"] = change.get(measure.key)
            sections.setdefault(measure.section, []).append(area)
        return {
            "now": now,
            "before": before,
            "change": change,
            "regions": regions,
            "sections": list(sections.items()),
            # The table's columns: the area, the country's four, three a team.
            "width": 5 + 3 * len(regions),
            "milestones": self.delivery_milestones(home),
        }

    def section_charts(self, section: str) -> list[dict] | None:
        """One section's target areas, each charted by region and by
        Programme Lead side by side (owner, 2026-10-21); None for a section
        the report does not have."""
        all_areas = self.areas()
        rows = [m for m in all_areas if m.section == section]
        if not rows:
            return None
        now = self.summary_figures(self.home(), self.period.to_date)
        regions = self._team_figures()
        charts = []
        for measure in rows:
            area = self._area(measure, all_areas, now, regions)
            area["regions"] = self.region_bars(measure.key)
            area["leads"] = self.lead_bars(regions, measure.key)
            charts.append(area)
        return charts

    def _team_figures(self) -> list[dict]:
        return [
            {
                "label": region.label,
                "lead": region.lead_name,
                "region": region,
                "figures": self.summary_figures(
                    self.team_scope(region), self.period.to_date
                ),
            }
            for region in self.roster.regions
        ]

    def _area(self, measure, all_areas, now: dict, regions: list[dict]) -> dict:
        key = measure.key
        share = now[f"{key}_pct"]
        return {
            "key": key,
            "label": self.area_label(measure, all_areas),
            "measure": measure,
            "target": now[f"{key}_target"],
            "achieved": now[key],
            "pct": share,
            "status": status(share, running=True),
            "teams": [
                {
                    "label": r["label"],
                    "target": r["figures"][f"{key}_target"],
                    "achieved": r["figures"][key],
                    "pct": r["figures"][f"{key}_pct"],
                }
                for r in regions
            ],
        }

    def lead_bars(self, regions: list[dict], key: str) -> list[dict]:
        """An area by Programme Lead, a chart of its own (owner, 2026-10-21:
        "the pl graph should be seperate"): each team's target against what
        it achieved."""
        return _bars(
            [
                {
                    "label": r["lead"] or r["label"],
                    # Its region beneath, when the team is named by one.
                    "place": r["label"] if r["lead"] not in ("", r["label"]) else "",
                    "target": r["figures"][f"{key}_target"],
                    "achieved": r["figures"][key],
                }
                for r in regions
            ]
        )

    def region_bars(self, measure_key: str) -> list[dict]:
        """An area by region, every region listed (owner, 2026-10-21: "needs
        to have all regions", "use region in stead"). What was achieved counts
        where its school is — a session where most of the schools it reached
        are, participants summed. Targets are set per CCEO, not per region, so
        each CCEO's target is shared across the regions their eligible schools
        are in, in whole numbers ("Split each CCEO's target"); a target whose
        holder holds no school, or a country target nobody holds, is "Not
        placed", so the bars add up to the country's target."""
        measure = measures.get(measure_key)
        led = self.ledger
        home = self.home()
        owners = self.owners(home)
        target = dict.fromkeys(led.regions, 0)
        achieved = dict.fromkeys(led.regions, 0)
        participants = measure.key in measures.PARTICIPANT_KEYS
        window = self.period.to_date
        if measure.source in PORTFOLIO_SOURCES:
            # A state of the portfolio, not dated records: the schools as
            # they stand at the end of the window.
            kind = PORTFOLIO_SOURCES[measure.source]
            counted = dict.fromkeys(
                led.portfolio_schools(owners, kind, as_of=window[1]), 1
            )
        else:
            counted = led.units(measure.key, owners, *window)
        for unit, qty in counted.items():
            place = led.region_of(unit) or NOT_PLACED
            achieved[place] = achieved.get(place, 0) + (qty if participants else 1)
        placed = 0
        family = _family(measure)
        for staff in self._holders(measure, owners):
            annual = self.target(measure, Scope.officer(staff)).annual
            if not annual:
                continue
            share = round(annual)
            placed += share
            for place, part in _spread(share, self._where(staff, family)).items():
                target[place] = target.get(place, 0) + part
        country = self.target(measure, home).annual
        if country and round(country) > placed:
            target[NOT_PLACED] = target.get(NOT_PLACED, 0) + round(country) - placed
        places = list(led.regions)
        if target.get(NOT_PLACED) or achieved.get(NOT_PLACED):
            places.append(NOT_PLACED)
        return _bars(
            [
                {
                    "label": place,
                    "place": "",
                    "target": target.get(place, 0),
                    "achieved": achieved.get(place, 0),
                }
                for place in places
            ]
        )

    def _holders(self, measure, owners) -> list[str]:
        """Who holds a target for this area: the CCEOs and leads allocated its
        milestone; for an area the plan has no milestone for, each officer,
        whose target is their eligible schools."""
        if measure.milestone:
            holders = self.book.holders(measure.milestone)
        else:
            holders = [o.staff_id for o in self.roster.officers]
        if owners is not None:
            holders = [h for h in holders if h in owners]
        return holders

    def _where(self, staff_id: str, family: str) -> dict[str, int]:
        """The regions an officer's schools of a family (client, Core or all)
        are in, by how many — all their schools when they hold none of it.
        Read once a page for every officer."""
        spreads = getattr(self, "_spreads", None)
        if spreads is None:
            spreads = defaultdict(lambda: defaultdict(Counter))
            for school in self.ledger.schools.values():
                if school.owner is None:
                    continue
                place = school.region or NOT_PLACED
                spreads[school.owner]["all"][place] += 1
                spreads[school.owner]["core" if school.core else "client"][place] += 1
            self._spreads = spreads
        held = spreads.get(staff_id, {})
        return dict(held.get(family) or held.get("all") or {})

    DELIVERY = (
        ("Non-Core School Visits (FY)", "client_visit_total", False),
        ("Partner School Visits (FY)", "client_visit_partner", False),
        ("Core School Recruitment (FY)", "core_recruitment", True),
        ("Client School SSA to Date", "ssa_client", True),
        ("MSC Data Collection", "msc", True),
        ("Discipleship Club Formation", "dc_clubs", True),
    )

    def delivery_milestones(self, scope: Scope) -> list[dict]:
        rows = []
        for label, key, closes in self.DELIVERY:
            measure = measures.get(key)
            target = self.target(measure, scope)
            cell = Cell(target.annual, self.count(key, scope, self.period.to_date))
            verdict = status(cell.pct, running=not closes)
            rows.append(
                {
                    "label": label,
                    "measure": measure,
                    "target": target,
                    "cell": cell,
                    "status": verdict,
                    "tone": STATUS_TONES.get(verdict, ""),
                }
            )
        return rows

    # ── Weekly Report ───────────────────────────────────────────────────────
    def weekly(self, scope: Scope) -> list[tuple[str, list[dict]]]:
        return [
            (section, [self.row(m, scope) for m in rows])
            for section, rows in measures.weekly_sections()
        ]

    # ── Strategic Milestones ────────────────────────────────────────────────
    def milestones(self) -> dict:
        """The sheet's 54 rows (`strategic.ROWS`): achieved from the records,
        targets from the plan milestone each row names."""
        from . import strategic

        scope = self.home()
        domains: dict[str, list[dict]] = {}
        to_date_target = to_date = tracked = 0
        for spec in strategic.ROWS:
            row = self._strategic_row(spec, scope)
            domains.setdefault(spec.domain, []).append(row)
            tracked += spec.kind != strategic.UNTRACKED
            cell = row["to_date"]
            if (
                spec.kind == strategic.COUNT
                and cell.target
                and cell.achieved is not None
            ):
                to_date_target += cell.target
                to_date += cell.achieved
        return {
            "domains": list(domains.items()),
            "count": len(strategic.ROWS),
            "domain_count": len(domains),
            "tracked": tracked,
            "to_date_target": to_date_target,
            "pacing": pct(to_date, to_date_target),
        }

    def _strategic_row(self, spec, scope: Scope) -> dict:
        from . import strategic

        period = self.period
        owners = self.owners(scope)
        eligible = self.ledger.portfolio(owners, spec.basis) if spec.basis else None

        def achieved(window):
            values = [self.count(key, scope, window) for key in spec.measures]
            if not values or any(v is None for v in values):
                return None
            total = sum(values)
            if spec.kind == strategic.RATE:
                return pct(total, eligible)
            return total

        target = None
        # A row with a basis and no plan milestone takes its eligible schools,
        # as its Detailed Country Report row does.
        if spec.plan or spec.basis or spec.key in self.book.country:
            target = self.book.for_code(
                spec.plan,
                scope,
                slice=spec.slice,
                basis=spec.basis if spec.kind == strategic.COUNT else "",
                eligible=eligible,
                key=spec.key,
            )
        if spec.kind == strategic.UNTRACKED:
            in_period = to_date = year = Cell(None, None)
            annual = target.annual if target else None
            year = Cell(annual, None)
        elif spec.kind == strategic.SCORE:
            score = self.ledger.ssa_average(owners, core=False)
            in_period = to_date = Cell(None, None)
            year = Cell(None, score)
        elif spec.kind == strategic.RATE:
            rate = target.rate if target else None
            if target is not None and rate is None and spec.key in self.book.country:
                rate = target.annual  # IA or Admin set it as a percentage
            in_period = Cell(None, None)
            to_date = Cell(rate, achieved(period.to_date))
            year = Cell(rate, to_date.achieved)
        else:
            phased = target and target.months is not None
            in_period = Cell(
                target.over(period.months) if phased else None,
                achieved(period.span),
            )
            to_date = Cell(
                target.through(period.last_month) if phased else None,
                achieved(period.to_date),
            )
            year = Cell(target.annual if target else None, to_date.achieved)
        if spec.kind == strategic.UNTRACKED:
            verdict = "Not tracked"
        elif year.pct is not None and year.pct >= 100:
            verdict = ACHIEVED
        elif to_date.pct is not None:
            verdict = status(to_date.pct, running=True)
        elif year.achieved:
            verdict = "In Progress"
        else:
            verdict = "Not Started"
        return {
            "spec": spec,
            "kind": spec.kind,
            "target": target,
            "period": in_period,
            "to_date": to_date,
            "year": year,
            "status": verdict,
            "tone": STATUS_TONES.get(
                verdict, "neutral" if verdict == "Not tracked" else "info"
            ),
            "tracker": _tracker([measures.get(k) for k in spec.measures])
            if spec.measures
            else ("", ""),
            "unit": measures.get(spec.measures[0]).unit if spec.measures else "",
        }

    # ── CCEO Officer Performance & Milestones Dashboard ─────────────────────
    # The live sheet's dashboard (owner, 2026-10-20): officer cards, an
    # officer deep-dive, the milestones, regional roll-ups and a master grid,
    # every figure "derived directly from" the month's summary — the year to
    # the end of the chosen month.
    SORTS = {
        "name": "Name",
        "portfolio": "Portfolio",
        "visits": "School Visits",
        "trainings": "Trainings",
        "recruitment": "Recruitment",
        "ssa": "SSA Reviews",
    }

    def officer_figures(self, scope: Scope) -> dict:
        """One officer's (or a group's) dashboard figures."""
        window = self.period.month_to_date
        owners = self.owners(scope)
        led = self.ledger

        def count(key, span=window):
            return self.count(key, scope, span) or 0

        f = {
            "portfolio": led.portfolio(owners, as_of=window[1]),
            "active": led.portfolio(owners, "active", as_of=window[1]),
            "core_schools": led.portfolio(owners, "core"),
            "client_schools": led.portfolio(owners, "client"),
        }
        f["inactive"] = f["portfolio"] - f["active"]
        f["active_pct"] = pct(f["active"], f["portfolio"])
        # Core visits and trainings: the schools at each package step, as the
        # summary's "1 / 2 / 3 / 4 visits" columns, added up.
        f["core_visit_steps"] = [count(f"core_visit_{n}") for n in (1, 2, 3, 4)]
        f["core_training_steps"] = [count(f"core_training_{n}") for n in (1, 2, 3, 4)]
        f["visits_core"] = sum(f["core_visit_steps"])
        f["visits_noncore"] = count("client_visit_total")
        f["visits_noncore_month_staff"] = count(
            "client_visit_staff", self.period.month_span
        )
        f["visits_noncore_partner"] = count("client_visit_partner")
        f["visits"] = f["visits_core"] + f["visits_noncore"]
        f["trainings_core"] = sum(f["core_training_steps"])
        f["trainings_client"] = count("client_trained")
        f["trainings_online"] = count("online_schools")
        f["trainings_tam"] = count("tam_bi_online_schools")
        f["trainings_ece"] = count("ece")
        f["trainings_other"] = (
            f["trainings_client"]
            + f["trainings_online"]
            + f["trainings_tam"]
            + f["trainings_ece"]
        )
        f["trainings"] = f["trainings_core"] + f["trainings_other"]
        f["recruit"] = count("core_recruitment")
        f["recruit_target"] = self.target(
            measures.get("core_recruitment"), scope
        ).annual
        f["recruit_var"] = _var(f["recruit"], f["recruit_target"])
        f["baseline_ssa"] = count("ssa_core_baseline")
        f["ssa_cohort"] = count("ssa_core_followup")
        f["ssa_cohort_target"] = led.portfolio(owners, "core_continuing")
        f["ssa_cohort_var"] = f["ssa_cohort"] - f["ssa_cohort_target"]
        f["ssa_client"] = count("ssa_client")
        f["ssa_client_target"] = f["client_schools"]
        f["ssa"] = f["ssa_cohort"] + f["ssa_client"]
        f["dc_data"] = count("dc_data")
        f["dc"] = count("dc_clubs")
        f["dc_pct"] = pct(f["dc"], f["dc_data"])
        f["enrol_pct"] = pct(count("enrolment"), f["portfolio"])
        f["metrics_pct"] = pct(count("schools_with_metrics"), f["portfolio"])
        return f

    def cceo_board(self, *, region: str = "", sort: str = "name") -> dict:
        """The dashboard's officer cards, regional roll-ups and master grid,
        narrowed to one region when a region chip is chosen."""
        regions = [r for r in self.roster.regions if not region or r.label == region]
        cards = []
        for r in regions:
            for officer in r.officers:
                cards.append(
                    {
                        "officer": officer,
                        "region": r.label,
                        "f": self.officer_figures(Scope.officer(officer.staff_id)),
                    }
                )
        keys = {
            "portfolio": lambda c: -c["f"]["portfolio"],
            "visits": lambda c: -c["f"]["visits"],
            "trainings": lambda c: -c["f"]["trainings"],
            "recruitment": lambda c: -c["f"]["recruit"],
            "ssa": lambda c: -c["f"]["ssa"],
        }
        cards.sort(
            key=lambda c: (keys.get(sort, lambda _c: 0)(c), c["officer"].name.lower())
        )
        rollups = [
            {
                "region": r,
                "officers": len(r.officers),
                "f": self.officer_figures(self.team_scope(r)),
            }
            for r in regions
        ]
        if region:
            ids = {c["officer"].staff_id for c in cards}
            total = self.officer_figures(Scope("region", "", frozenset(ids)))
        else:
            total = self.officer_figures(self.home())
        return {
            "cards": cards,
            "rollups": rollups,
            "total": total,
            "officers": len(cards),
            "regions": [(r.label, len(r.officers)) for r in self.roster.regions],
        }

    def deep_dive(self, officer) -> dict:
        region = self.roster.region_of(officer.staff_id)
        return {
            "officer": officer,
            "region": region.label if region else "",
            "f": self.officer_figures(Scope.officer(officer.staff_id)),
        }

    # ── {Month} {Year} Summary ──────────────────────────────────────────────
    def month_summary(self) -> dict:
        period = self.period
        window = period.month_to_date
        groups = []
        for region in self.roster.regions:
            lines = [
                {
                    "label": o.name,
                    "officer": o,
                    "cols": self.summary_columns(Scope.officer(o.staff_id), window),
                }
                for o in region.officers
            ]
            total = self.summary_columns(self.team_scope(region), window)
            groups.append({"region": region, "lines": lines, "total": total})
        home = self.home()
        unlisted = None
        if not self.roster.narrowed:
            listed = {o.staff_id for o in self.roster.officers}
            unlisted = (
                self.ledger.portfolio(None) - self.ledger.portfolio(listed)
            ) or None
        return {
            "groups": groups,
            "national": self.summary_columns(home, window),
            "last_month": self.summary_columns(home, period.month_before),
            "unlisted": unlisted,
            "label": period.month_label,
        }

    SUMMARY_GROUPS = (
        # (heading, [(column key, label)])
        (
            "Portfolio",
            [
                ("portfolio", "Total"),
                ("active", "Active"),
                ("inactive", "Inactive"),
                ("active_p", "% Active"),
            ],
        ),
        (
            "Core Recruited This FY",
            [
                ("recruit_t", "Target"),
                ("recruit_a", "Achieved"),
                ("recruit_ssa", "Baseline SSA"),
                ("recruit_v", "Var"),
                ("recruit_p", "%"),
            ],
        ),
        (
            "Core SSA (Yr 1–3)",
            [("cohort_t", "Target"), ("cohort_a", "Achieved"), ("cohort_v", "Var")],
        ),
        (
            "Client SSA to Date",
            [
                ("ssa_t", "Target"),
                ("ssa_a", "Achieved"),
                ("ssa_v", "Var"),
                ("ssa_p", "%"),
            ],
        ),
        ("New Schools This Month", [("new_m_t", "Target"), ("new_m_a", "Achieved")]),
        (
            "Enrolment",
            [
                ("enrol_base", "Schools"),
                ("enrol_with", "With"),
                ("enrol_without", "Without"),
                ("enrol_p", "%"),
            ],
        ),
        (
            "Metrics",
            [
                ("metrics_base", "Schools"),
                ("metrics_with", "With"),
                ("metrics_without", "Without"),
                ("metrics_p", "%"),
            ],
        ),
        (
            "New Schools This FY",
            [
                ("new_t", "Target"),
                ("new_a", "Achieved"),
                ("new_v", "Var"),
                ("new_p", "%"),
            ],
        ),
        *(
            (
                f"Core Visit {n}{'+' if n == 4 else ''}",
                [
                    (f"cv{n}_t", "Target"),
                    (f"cv{n}_a", "Achieved"),
                    (f"cv{n}_v", "Var"),
                    (f"cv{n}_p", "%"),
                ],
            )
            for n in (1, 2, 3, 4)
        ),
        (
            "Non-Core Visited FY – Staff or Partner",
            [("nc_t", "Target"), ("nc_a", "Visited"), ("nc_v", "Var"), ("nc_p", "%")],
        ),
        (
            "Non-Core Visited This Month – Staff",
            [("ncm_t", "Schools"), ("ncm_a", "Visited"), ("ncm_p", "%")],
        ),
        (
            "Non-Core Visited FY – Partner",
            [
                ("ncp_t", "Target"),
                ("ncp_a", "Visited"),
                ("ncp_v", "Var"),
                ("ncp_p", "%"),
            ],
        ),
        (
            "Pending Schools",
            [
                ("pend_base", "Non-Core"),
                ("pend_a", "Visited"),
                ("pend_left", "Not Visited"),
                ("pend_p", "%"),
            ],
        ),
        *(
            (
                f"Core Training {n}",
                [
                    (f"ct{n}_t", "Target"),
                    (f"ct{n}_a", "Achieved"),
                    (f"ct{n}_v", "Var"),
                    (f"ct{n}_p", "%"),
                ],
            )
            for n in (1, 2, 3, 4)
        ),
        (
            "Client School Trainings",
            [
                ("cst_t", "Target"),
                ("cst_a", "Achieved"),
                ("cst_v", "Var"),
                ("cst_p", "%"),
            ],
        ),
        ("Online Trainings", [("onl_a", "Schools"), ("onl_s", "Sessions")]),
        ("TAM / BI Online", [("tam_a", "Schools"), ("tam_s", "Sessions")]),
        ("ECE", [("ece_a", "Schools")]),
        ("MSC", [("msc_t", "Target"), ("msc_a", "Achieved"), ("msc_p", "%")]),
        (
            "DC Club",
            [
                ("dc_t", "Data Collected"),
                ("dc_a", "With DC"),
                ("dc_none", "No DC"),
                ("dc_p", "%"),
            ],
        ),
    )

    def summary_columns(self, scope: Scope, window) -> dict:
        owners = self.owners(scope)
        led = self.ledger
        period = self.period

        def count(key, span=window):
            return self.count(key, scope, span)

        def target(key):
            return self.target(measures.get(key), scope).annual

        c: dict = {}

        def block(prefix, goal, achieved, *, ratio=True):
            c[f"{prefix}_t"] = goal
            c[f"{prefix}_a"] = achieved
            c[f"{prefix}_v"] = _var(achieved, goal)
            if ratio:
                c[f"{prefix}_p"] = pct(achieved, goal)

        c["portfolio"] = led.portfolio(owners, as_of=window[1])
        c["active"] = led.portfolio(owners, "active", as_of=window[1])
        c["inactive"] = c["portfolio"] - c["active"]
        c["active_p"] = pct(c["active"], c["portfolio"])
        block("recruit", target("core_recruitment"), count("core_recruitment"))
        c["recruit_ssa"] = count("ssa_core_baseline")
        block(
            "cohort",
            led.portfolio(owners, "core_continuing"),
            count("ssa_core_followup"),
            ratio=False,
        )
        block("ssa", target("ssa_client"), count("ssa_client"))
        c["new_m_t"] = self.target(measures.get("new_schools"), scope).month(
            period.month
        )
        c["new_m_a"] = count("new_schools", period.month_span)
        base = c["portfolio"]
        for prefix, key in (
            ("enrol", "enrolment"),
            ("metrics", "schools_with_metrics"),
        ):
            have = count(key)
            c[f"{prefix}_base"], c[f"{prefix}_with"] = base, have
            c[f"{prefix}_without"] = base - (have or 0)
            c[f"{prefix}_p"] = pct(have, base)
        block("new", target("new_schools"), count("new_schools"))
        core = led.portfolio(owners, "core")
        client = led.portfolio(owners, "client")
        for n in (1, 2, 3, 4):
            block(f"cv{n}", core, count(f"core_visit_{n}"))
            block(f"ct{n}", core, count(f"core_training_{n}"))
        block("nc", client, count("client_visit_total"))
        c["ncm_t"] = client
        c["ncm_a"] = count("client_visit_staff", period.month_span)
        c["ncm_p"] = pct(c["ncm_a"], client)
        block("ncp", client, count("client_visit_partner"))
        c["pend_base"], c["pend_a"] = client, c["nc_a"]
        c["pend_left"] = client - (c["nc_a"] or 0)
        c["pend_p"] = c["nc_p"]
        block("cst", client, count("client_trained"))
        c["onl_a"], c["onl_s"] = count("online_schools"), count("online_sessions")
        c["tam_a"], c["tam_s"] = (
            count("tam_bi_online_schools"),
            count("tam_bi_online_sessions"),
        )
        c["ece_a"] = count("ece")
        block("msc", target("msc"), count("msc"))
        c["dc_t"], c["dc_a"] = count("dc_data"), count("dc_clubs")
        c["dc_none"] = _var(c["dc_t"], c["dc_a"])
        c["dc_p"] = pct(c["dc_a"], c["dc_t"])
        return c

    # ── Core Visits & Training ──────────────────────────────────────────────
    def core_package(self) -> dict:
        lines = []
        for region in self.roster.regions:
            for officer in region.officers:
                lines.append(
                    {
                        "officer": officer,
                        "region": region.label,
                        **self.package_figures(Scope.officer(officer.staff_id)),
                    }
                )
        lines.sort(key=lambda r: r["officer"].name.lower())
        return {"lines": lines, "total": self.package_figures(self.home())}

    def package_figures(self, scope: Scope) -> dict:
        window = self.period.now
        core = self.ledger.portfolio(self.owners(scope), "core")
        out: dict = {"core": core}
        for kind in ("visit", "training"):
            at_least = [
                self.count(f"core_{kind}_{n}", scope, window) or 0 for n in (1, 2, 3, 4)
            ]
            exactly = [
                at_least[i] - (at_least[i + 1] if i < 3 else 0) for i in range(4)
            ]
            done = sum(at_least)
            out[kind] = {
                "one": exactly[0],
                "two": exactly[1],
                "three": exactly[2],
                "four": exactly[3],
                "expected": core * 4,
                "done": done,
                "pct": pct(done, core * 4),
                "three_plus": at_least[2],
                "three_pct": pct(at_least[2], core),
            }
        return out


#: Where the records behind a measure are kept, for the tracker column.
TRACKERS = {
    "ssa": ("/cluster-oversight/ssa", "SSA Records"),
    "msc": ("/my-targets", "MSC Stories"),
    "evidence": ("/ia/school-evidence/", "School Evidence"),
    "loans": ("/loans", "Loan Register"),
    "core": ("/core-schools-oversight/", "Core School Oversight"),
    "schools": ("/schools", "School Registry"),
    "work": ("/country-planning-oversight/", "Planning Oversight"),
}
EVIDENCE_SOURCES = (
    "dc_clubs",
    "dc_clubs_core",
    "dc_clubs_client",
    "dc_data",
    "onetest",
    "core_exam_scores",
    "metrics",
)


NOT_PLACED = "Not placed"
#: Figures that are a state of the portfolio, by the `Ledger.portfolio` kind.
PORTFOLIO_SOURCES = {"active": "active", "in_clusters": "clustered"}


def _family(measure) -> str:
    """The schools an area's target is spread by: its basis or slice, or the
    family its key names (client_…, core_…); a recruit was a client school."""
    if measure.key in ("core_recruitment", "ssa_core_baseline"):
        return "client"
    for family in (measure.basis, measure.slice):
        if family in (measures.CLIENT, measures.SSA_CLIENT):
            return "client"
        if family in (measures.CORE, measures.CORE_CONTINUING, measures.SSA_CORE):
            return "core"
    if measure.key.startswith("client_"):
        return "client"
    if measure.key.startswith("core_"):
        return "core"
    return "all"


def _spread(total: int, weights: dict[str, int]) -> dict[str, int]:
    """A whole number shared by weight, largest remainder first, so the parts
    add up to it; with nothing to share by, it is not placed."""
    whole = sum(weights.values())
    if not whole:
        return {NOT_PLACED: total}
    exact = {k: total * w / whole for k, w in weights.items()}
    parts = {k: int(v) for k, v in exact.items()}
    left = total - sum(parts.values())
    for k in sorted(exact, key=lambda k: exact[k] - parts[k], reverse=True)[:left]:
        parts[k] += 1
    return parts


def _bars(rows: list[dict]) -> list[dict]:
    """A target-vs-achieved bar chart: each bar a share of the tallest, with
    its variance and share of target for the table beneath it."""
    tallest = max(
        [r["target"] or 0 for r in rows] + [r["achieved"] or 0 for r in rows] + [1]
    )
    return [
        {
            **r,
            "variance": _var(r["achieved"], r["target"]),
            "pct": pct(r["achieved"], r["target"]),
            "target_h": round(100 * (r["target"] or 0) / tallest, 1),
            "achieved_h": round(100 * (r["achieved"] or 0) / tallest, 1),
        }
        for r in rows
    ]


def _tracker(rows) -> tuple[str, str]:
    if not rows:
        return ("/target-distribution", "Target Distribution")
    source = rows[0].source
    if source.startswith("ssa"):
        return TRACKERS["ssa"]
    if source == "msc":
        return TRACKERS["msc"]
    if source in EVIDENCE_SOURCES:
        return TRACKERS["evidence"]
    if source in ("loans", "edtech_loans", "development_loans"):
        return TRACKERS["loans"]
    if source.startswith("core_"):
        return TRACKERS["core"]
    if source in ("active", "in_clusters", "new_schools", "enrolment"):
        return TRACKERS["schools"]
    return TRACKERS["work"]


__all__ = ["NO_LEAD", "NOT_SET", "Report", "TABS", "status"]
