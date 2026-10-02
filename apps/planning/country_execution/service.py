"""CountryExecutionOversightService — did the planned work happen, and is it closed?

Reads the classified activities of a window (``dataset``) through the page's
filters into the Country → Programme Lead → CCEO → Partner hierarchy, and
turns that one fold into every surface of the Execution & Completion tab: the
six figures, the funnel, the trend, the on-time and backlog charts, the
forecast, the tables and the lists. Required-slot completion ("Remaining
Slots") is read from the planning coverage service for the same window, so the
obligation the two tabs describe is one obligation.

Nothing here writes. Achievement, targets and performance are never computed:
verified work earns its credit in the canonical ledger, and this page only
counts which stage each record has reached.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field, fields
from datetime import date, datetime

from django.utils import timezone

from apps.planning.country_execution import dataset as ds
from apps.planning.country_execution import stages as st
from apps.planning.country_oversight.policy import CORE_FAMILY
from apps.planning.country_oversight.coverage import Window, fy_label, window_for
from apps.planning.country_oversight.requirements import (
    NO_LEAD_KEY,
    NO_LEAD_LABEL,
    NO_OWNER_KEY,
    NO_OWNER_LABEL,
)

logger = logging.getLogger(__name__)

PAGE_PATH = "/country-planning-oversight/"
EXECUTION_QUERY = "view=execution"
BASE_PATH = "/country-planning-oversight/execution"

PERIODS = ("week", "month", "quarter", "fy")
PERIOD_LABELS = {"week": "Week", "month": "Month", "quarter": "Quarter", "fy": "Annual"}
VIEW_BY = (
    ("lead", "Program Lead"),
    ("cceo", "CCEO"),
    ("partner", "Partner"),
    ("school", "School"),
    ("activity", "Activity"),
)
CHANNELS = (("staff", "Staff"), ("partner", "Partner"))

#: The forecast's line between "On Track" and "At Risk": the share of the
#: period's due work projected to be verified by its end. Decision support
#: only (spec §21) — it changes no target, plan, performance or reminder.
FORECAST_ON_TRACK = 0.9
FORECAST_MIN_DUE = 10


# ── Filters ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ExecFilters:
    fy: str
    period: str = "month"
    quarter: str = ""
    month: int | None = None
    week: str = ""
    region: str = ""
    program_lead: str = ""
    cceo: str = ""
    channel: str = ""
    partner: str = ""
    activity_type: str = ""

    CELL_FILTERS = (
        "region",
        "program_lead",
        "cceo",
        "channel",
        "partner",
        "activity_type",
    )

    @property
    def window(self) -> Window:
        week_start = None
        if self.period == "week" and self.week:
            try:
                week_start = datetime.strptime(f"{self.week}-1", "%G-W%V-%u").date()
            except ValueError:
                week_start = None
        return window_for(
            self.fy,
            self.period if (self.period != "week" or week_start) else "fy",
            quarter=self.quarter or None,
            month=self.month,
            week_start=week_start,
        )

    def key(self) -> str:
        parts = [f"{f.name}={getattr(self, f.name)}" for f in fields(self)]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:20]

    def params(self, **overrides) -> dict:
        values = {f.name: getattr(self, f.name) for f in fields(self)}
        values.update(overrides)
        out = {"view": "execution", "fy": values["fy"], "period": values["period"]}
        if values["period"] == "quarter" and values["quarter"]:
            out["quarter"] = values["quarter"]
        if values["period"] == "month" and values["month"]:
            out["month"] = values["month"]
        if values["period"] == "week" and values["week"]:
            out["week"] = values["week"]
        for name in self.CELL_FILTERS:
            if values.get(name):
                out[name] = values[name]
        return out

    def query(self, **overrides) -> str:
        from urllib.parse import urlencode

        return urlencode(self.params(**overrides))

    @property
    def active_filters(self) -> int:
        return sum(1 for name in self.CELL_FILTERS if getattr(self, name))

    def planning(self):
        """The same selection as planning filters, for required-slot completion.

        A week has no phased requirement, so its slots are read for the year.
        """
        from apps.planning.country_oversight.service import Filters

        period = "fy" if self.period == "week" else self.period
        return Filters(
            fy=self.fy,
            period=period,
            quarter=self.quarter if period == "quarter" else "",
            month=self.month if period == "month" else None,
            region=self.region,
            program_lead=self.program_lead,
            cceo=self.cceo,
            channel=self.channel,
            partner=self.partner,
        )


def read_filters(request) -> ExecFilters:
    """The tab's filters. It opens on this month (owner design, 2026-09-28)."""
    from apps.core.fy import get_operational_fy, get_quarter_for_date

    get = request.POST if request.method == "POST" and request.POST else request.GET
    operational = get_operational_fy()
    fy = (get.get("fy") or "").strip() or operational
    if not fy.isdigit():
        fy = operational
    today = date.today()
    period = (get.get("period") or "").strip().lower()
    raw_month = (get.get("month") or "").strip()
    month = (
        int(raw_month) if raw_month.isdigit() and 1 <= int(raw_month) <= 12 else None
    )
    quarter = (get.get("quarter") or "").strip().upper()
    quarter = quarter if quarter in ("Q1", "Q2", "Q3", "Q4") else ""
    week = (get.get("week") or "").strip()
    if period not in PERIODS:
        period = "month" if fy == operational else "fy"
    if period == "quarter" and not quarter:
        quarter = get_quarter_for_date(today) if fy == operational else "Q1"
    if period == "month" and not month:
        month = today.month if fy == operational else 10
    if period == "week" and not week:
        week = today.strftime("%G-W%V")

    def pick(name, allowed=None):
        value = (get.get(name) or "").strip()
        if allowed is not None and value not in allowed:
            return ""
        return value if value not in ("all", "All") else ""

    return ExecFilters(
        fy=fy,
        period=period,
        quarter=quarter if period == "quarter" else "",
        month=month if period == "month" else None,
        week=week if period == "week" else "",
        region=pick("region"),
        program_lead=pick("program_lead"),
        cceo=pick("cceo"),
        channel=pick("channel", {key for key, _ in CHANNELS}),
        partner=pick("partner"),
        activity_type=pick("activity_type"),
    )


# ── The dataset, cached ──────────────────────────────────────────────────────
def _timeout() -> int:
    from django.conf import settings

    return int(getattr(settings, "DASHBOARD_CACHE_SECONDS", 0) or 0)


def _key(universe: str, window: Window, today: date) -> str:
    # The day is in the key: overdue and ages are read against today.
    return f"cpx:data:v1:{universe}:{window.cache_part}:{today.isoformat()}"


#: The dataset this worker last read (see country_oversight.service._HELD).
_HELD: dict = {}


def dataset_for(user, window: Window, *, refresh: bool = False) -> ds.ExecutionDataset:
    from apps.core.cache_utils import forget_snapshot, stampede_safe_get_or_compute
    from apps.core.scoping import resolve_user_scope
    from apps.planning.country_oversight.service import (
        _read_stamp,
        _stamp_key,
        _write_stamp,
        universe_key,
    )

    scope = resolve_user_scope(user)
    universe = universe_key(scope)
    key = _key(universe, window, timezone.localdate())
    timeout = _timeout()
    if refresh:
        forget_snapshot(key)
        forget_snapshot(_stamp_key(key))
        _HELD.pop(key, None)
    elif timeout > 0:
        _note_window(universe, window)
        held = _HELD.get(key)
        if held is not None and held.stamp == _read_stamp(key):
            return held
    built: list = []

    def build():
        built.append(ds.build(scope, window, universe=universe))
        return built[0]

    dataset = stampede_safe_get_or_compute(key, build, timeout=timeout)
    if timeout > 0:
        _write_stamp(key, dataset.stamp, timeout=timeout, replace=bool(built))
        _HELD.clear()
        _HELD[key] = dataset
    return dataset


# ── Keeping the tab ready ────────────────────────────────────────────────────
#: Windows country readers opened lately, beyond the two warmed unasked.
_RECENT_KEY = "cpx:recent-windows:v1"


def _window_entry(universe: str, window: Window) -> tuple:
    week = window.start.strftime("%G-W%V") if window.period == "week" else ""
    return (
        universe,
        window.fy,
        window.period,
        window.quarter or "",
        window.month,
        week,
    )


def _note_window(universe: str, window: Window) -> None:
    """Remember a country reader's window, so the warmer keeps it ready (see
    country_oversight.service._note_window). The month the tab opens on and
    the year are warmed unasked."""
    from django.core.cache import cache

    from apps.planning.country_oversight.service import (
        WARM_EVERY_MINUTES,
        WARM_RECENT_SECONDS,
    )

    if not universe.startswith("country:") or window.period == "fy":
        return
    if window.period == "month" and window.month == timezone.localdate().month:
        return
    entry = _window_entry(universe, window)
    try:
        recent = cache.get(_RECENT_KEY) or {}
        now = timezone.now().timestamp()
        if now - recent.get(entry, 0) < WARM_EVERY_MINUTES * 60:
            return
        recent = {
            key: moment
            for key, moment in recent.items()
            if now - moment < WARM_RECENT_SECONDS
        }
        recent[entry] = now
        cache.set(_RECENT_KEY, recent, timeout=WARM_RECENT_SECONDS)
    except Exception:  # noqa: BLE001 - the warmer is an optimisation only
        logger.warning("Could not note the execution window", exc_info=True)


def warm_targets(today: date | None = None) -> list[tuple[str, ExecFilters]]:
    """(country, filters) the warmer rebuilds: each country the planning
    warmer keeps, for the month the tab opens on and the year, plus the
    windows country readers opened in the last hour."""
    from django.core.cache import cache

    from apps.core.fy import get_operational_fy
    from apps.planning.country_oversight.service import (
        WARM_RECENT_SECONDS,
        WARM_RECENT_WINDOWS,
    )
    from apps.planning.country_oversight.service import warm_targets as planning_targets

    today = today or timezone.localdate()
    fy = get_operational_fy(today)
    countries = sorted({country for country, _filters in planning_targets(today)})
    targets = []
    for country in countries:
        targets.append((country, ExecFilters(fy=fy, period="month", month=today.month)))
        targets.append((country, ExecFilters(fy=fy, period="fy")))
    try:
        recent = cache.get(_RECENT_KEY) or {}
    except Exception:  # noqa: BLE001 - the warmer is an optimisation only
        recent = {}
    now = timezone.now().timestamp()
    ranked = sorted(
        (moment, key)
        for key, moment in recent.items()
        if now - moment < WARM_RECENT_SECONDS
    )
    extra = 0
    for _moment, (universe, fy_, period, quarter, month, week) in reversed(ranked):
        country = universe.split(":", 1)[1]
        if country not in countries or extra >= WARM_RECENT_WINDOWS:
            continue
        targets.append(
            (
                country,
                ExecFilters(
                    fy=fy_,
                    period=period,
                    quarter=quarter if period == "quarter" else "",
                    month=month if period == "month" else None,
                    week=week if period == "week" else "",
                ),
            )
        )
        extra += 1
    return targets


def warm(targets=None, *, today: date | None = None) -> int:
    """Rebuild and publish each target's classified activities, so a Country
    Director opening the tab is served rather than kept waiting (spec §27).
    Publishing replaces what readers are served in one step, and moves every
    worker's held copy on with it. The planning figures the tab's Remaining
    Slots read for the same window are warmed with them (the planning warmer
    keeps the year). Returns how many windows were published."""
    from apps.core.cache_utils import publish_snapshot
    from apps.planning.country_oversight.service import (
        WARM_KEEP_SECONDS,
        _write_stamp,
        system_scope,
        universe_key,
    )
    from apps.planning.country_oversight.service import warm as warm_planning

    if _timeout() <= 0:
        return 0
    keep = max(_timeout(), WARM_KEEP_SECONDS)
    today = today or timezone.localdate()
    done = 0
    failed: Exception | None = None
    seen: set = set()
    planning: list = []
    for country, filters in targets if targets is not None else warm_targets(today):
        window = filters.window
        scope = system_scope(country)
        universe = universe_key(scope)
        key = _key(universe, window, today)
        if key in seen:
            continue
        seen.add(key)
        if filters.planning().period != "fy":
            planning.append((country, filters.planning()))
        try:
            dataset = ds.build(scope, window, today=today, universe=universe)
        except Exception as exc:  # noqa: BLE001 - one window must not stop the rest
            logger.exception("Could not warm %s %s", universe, window.cache_part)
            failed = failed or exc
            continue
        publish_snapshot(key, dataset, timeout=keep)
        _write_stamp(key, dataset.stamp, timeout=keep, replace=True)
        done += 1
    if planning:
        try:
            warm_planning(planning)
        except Exception as exc:  # noqa: BLE001 - reported with the rest
            failed = failed or exc
    if failed is not None:
        raise failed
    return done


# ── The tree ─────────────────────────────────────────────────────────────────
class ExecTally:
    """A row's execution figures by name, with the shares the page prints."""

    __slots__ = ("values", "trend_width")

    def __init__(self, values: list | None = None, trend_width: int = 0):
        self.values = (
            values if values is not None else [0] * (ds.BASE_WIDTH + trend_width)
        )
        self.trend_width = trend_width

    def __getattr__(self, name):
        if name.startswith("__") or name in ("values", "trend_width"):
            raise AttributeError(name)
        try:
            return self.values[ds.IDX[name]]
        except KeyError as exc:
            raise AttributeError(name) from exc

    @staticmethod
    def share(part: int, whole: int) -> int | None:
        from apps.core.metrics import percentage

        return percentage(part, whole)

    @property
    def started_share(self):
        return self.share(self.started, self.due)

    @property
    def executed_share(self):
        return self.share(self.executed, self.due)

    @property
    def verified_share(self):
        return self.share(self.verified, self.due)

    @property
    def closed_share(self):
        return self.share(self.closed, self.due)

    @property
    def overdue_share(self):
        return self.share(self.overdue, self.due)

    @property
    def on_time_share(self):
        return self.share(self.on_time, self.due)

    @property
    def backlog(self) -> int:
        return sum(self.values[ds.IDX[f"own_{key}"]] for key, _ in st.OWNERS)

    def trend(self, series: str, buckets: int) -> list[int]:
        offset = ds.BASE_WIDTH + ds.TREND_SERIES.index(series) * buckets
        return self.values[offset : offset + buckets]


def _sum(vectors: list, width: int) -> list:
    if not vectors:
        return [0] * width
    if len(vectors) == 1:
        return list(vectors[0])
    return [sum(column) for column in zip(*vectors)]


@dataclass
class OwnerExec:
    key: str
    name: str
    kind: str
    lead_key: str
    tally: ExecTally
    partners: dict = field(default_factory=dict)  # partner key → ExecTally

    @property
    def label(self) -> str:
        return "PL Personal Delivery" if self.kind == "pl_personal" else self.name


@dataclass
class LeadExec:
    key: str
    name: str
    tally: ExecTally
    owners: list = field(default_factory=list)
    is_no_lead: bool = False


@dataclass
class ExecTree:
    country: ExecTally
    leads: list
    partners: dict  # partner key → ExecTally, across owners
    staff: ExecTally
    partner_channel: ExecTally
    window: Window
    buckets: list


def _cell_keeps(filters: ExecFilters, key: tuple, lead_of: dict) -> bool:
    owner_key, partner_key, channel, region_id, _district_id, activity_type = key
    if filters.region and region_id != filters.region:
        return False
    if filters.cceo and owner_key != filters.cceo:
        return False
    if (
        filters.program_lead
        and lead_of.get(owner_key, NO_LEAD_KEY) != filters.program_lead
    ):
        return False
    if filters.channel and channel != filters.channel:
        return False
    if filters.partner and partner_key != filters.partner:
        return False
    if filters.activity_type and activity_type != filters.activity_type:
        return False
    return True


def fold(dataset: ds.ExecutionDataset, filters: ExecFilters) -> ExecTree:
    """The filtered cells, summed up the hierarchy."""
    width = dataset.width
    trend_width = width - ds.BASE_WIDTH
    owners = dataset.owners
    lead_of = {key: info.lead_key for key, info in owners.items()}
    by_owner: dict[str, list] = {}
    by_owner_partner: dict[tuple, list] = {}
    by_partner: dict[str, list] = {}
    by_channel: dict[str, list] = {"staff": [], "partner": []}
    for key, vector in dataset.cells.items():
        if not _cell_keeps(filters, key, lead_of):
            continue
        owner_key, partner_key, channel = key[0], key[1], key[2]
        by_owner.setdefault(owner_key, []).append(vector)
        by_owner_partner.setdefault((owner_key, partner_key), []).append(vector)
        by_channel[channel].append(vector)
        if partner_key != ds.STAFF_KEY:
            by_partner.setdefault(partner_key, []).append(vector)

    rows: dict[str, OwnerExec] = {}
    for owner_key, vectors in by_owner.items():
        info = owners.get(owner_key)
        rows[owner_key] = OwnerExec(
            key=owner_key,
            name=info.name if info else NO_OWNER_LABEL,
            kind=info.kind if info else "unassigned",
            lead_key=info.lead_key if info else NO_LEAD_KEY,
            tally=ExecTally(_sum(vectors, width), trend_width),
        )
    for (owner_key, partner_key), vectors in by_owner_partner.items():
        row = rows.get(owner_key)
        if row is not None:
            row.partners[partner_key] = ExecTally(_sum(vectors, width), trend_width)

    show_roster = not filters.active_filters or (
        filters.active_filters == 1 and filters.program_lead
    )
    leads: list[LeadExec] = []
    seen: set[str] = set()
    for lead in dataset.leads:
        if filters.program_lead and lead.key != filters.program_lead:
            continue
        seen.add(lead.key)
        members = [row for row in rows.values() if row.lead_key == lead.key]
        if show_roster:
            present = {row.key for row in members}
            for person in dataset.rosters.get(lead.key, []):
                if person.key not in present:
                    members.append(
                        OwnerExec(
                            key=person.key,
                            name=person.name,
                            kind="cceo",
                            lead_key=lead.key,
                            tally=ExecTally(None, trend_width),
                        )
                    )
        leads.append(_lead(lead.key, lead.name, members, width, trend_width))
    orphans: dict[str, list] = {}
    for row in rows.values():
        if row.lead_key not in seen:
            orphans.setdefault(row.lead_key, []).append(row)
    for lead_key, members in orphans.items():
        if lead_key == NO_LEAD_KEY:
            continue
        name = next(
            (owners[m.key].lead_name for m in members if m.key in owners), NO_LEAD_LABEL
        )
        leads.append(_lead(lead_key, name, members, width, trend_width))
    if NO_LEAD_KEY in orphans:
        row = _lead(
            NO_LEAD_KEY, NO_LEAD_LABEL, orphans[NO_LEAD_KEY], width, trend_width
        )
        row.is_no_lead = True
        leads.append(row)

    country = ExecTally(_sum([lead.tally.values for lead in leads], width), trend_width)
    return ExecTree(
        country=country,
        leads=leads,
        partners={
            key: ExecTally(_sum(vectors, width), trend_width)
            for key, vectors in by_partner.items()
        },
        staff=ExecTally(_sum(by_channel["staff"], width), trend_width),
        partner_channel=ExecTally(_sum(by_channel["partner"], width), trend_width),
        window=dataset.window,
        buckets=dataset.buckets,
    )


def _lead(key, name, members, width, trend_width) -> LeadExec:
    order = {"pl_personal": 0, "cceo": 1, "other": 2, "unassigned": 3}
    members.sort(key=lambda row: (order.get(row.kind, 2), row.name.casefold()))
    total = _sum([m.tally.values for m in members], width)
    return LeadExec(
        key=key, name=name, tally=ExecTally(total, trend_width), owners=members
    )


# ── The snapshot the page renders ────────────────────────────────────────────
@dataclass
class ExecSnapshot:
    tree: ExecTree
    filters: ExecFilters
    dataset: ds.ExecutionDataset
    remaining: dict  # ("country"|"lead"|"owner", key) → remaining slots
    unique_schools: int
    required_slots: int

    @property
    def window(self) -> Window:
        return self.dataset.window


def snapshot_for(user, filters: ExecFilters, *, refresh: bool = False) -> ExecSnapshot:
    dataset = dataset_for(user, filters.window, refresh=refresh)
    tree = fold(dataset, filters)
    remaining, required = remaining_slots(user, filters)
    return ExecSnapshot(
        tree=tree,
        filters=filters,
        dataset=dataset,
        remaining=remaining,
        unique_schools=len(
            {
                r.school_id
                for r in filtered_records(dataset, filters)
                if r.school_id and not r.cancelled
            }
        ),
        required_slots=required,
    )


def filtered_records(dataset: ds.ExecutionDataset, filters: ExecFilters):
    lead_of = {key: info.lead_key for key, info in dataset.owners.items()}
    for record in dataset.records:
        key = (
            record.owner_key,
            record.partner_key,
            record.channel,
            record.region_id,
            record.district_id,
            record.activity_type,
        )
        if _cell_keeps(filters, key, lead_of):
            yield record


def remaining_slots(user, filters: ExecFilters) -> tuple[dict, int]:
    """Required visit and training slots not yet verified, per level, from the
    planning coverage service (the same requirement the Planning tab counts)."""
    from apps.planning.country_oversight.service import (
        snapshot_for as planning_snapshot,
    )

    try:
        snap = planning_snapshot(user, filters.planning())
    except Exception:  # noqa: BLE001 - completion is a column, not the page
        logger.warning("Required-slot completion could not be read", exc_info=True)
        return {}, 0

    def left(tally) -> int:
        visits = max(
            0, tally.visit_slots - tally.staff_verified - tally.partner_verified
        )
        training = max(0, tally.training_slots - tally.training_verified)
        return visits + training

    out = {("country", ""): left(snap.tree.country)}
    for lead in snap.tree.leads:
        out[("lead", lead.key)] = left(lead.tally)
        for owner in lead.owners:
            out[("owner", owner.key)] = left(owner.tally)
    country = snap.tree.country
    return out, country.visit_slots + country.training_slots


# ── Figures ──────────────────────────────────────────────────────────────────
def forecast(tally: ExecTally, window: Window, today: date) -> dict:
    """Decision support only (spec §21): the share of the period's due work
    projected to be verified by its end, from the conversion this period's
    own past-due work shows. Never changes a target, a plan or performance."""
    due = tally.due
    if today >= window.end:
        share = tally.share(tally.verified, due)
        return {"status": "closed", "label": "Period closed", "share": share}
    arrived = due - tally.upcoming
    if due < FORECAST_MIN_DUE or arrived < 5:
        return {"status": "insufficient", "label": "Insufficient Data", "share": None}
    started, executed, verified = tally.started, tally.executed, tally.verified
    start_rate = min(1.0, started / arrived) if arrived else 0.0
    submit_rate = executed / started if started else 0.0
    verify_rate = verified / executed if executed else 0.0
    expected = (
        verified
        + (executed - verified) * verify_rate
        + (started - executed) * submit_rate * verify_rate
        + (due - started) * start_rate * submit_rate * verify_rate
    )
    share = ExecTally.share(expected, due)
    on_track = share is not None and share >= FORECAST_ON_TRACK * 100
    return {
        "status": "on_track" if on_track else "at_risk",
        "label": "On Track" if on_track else "At Risk",
        "share": share,
    }


def target_people(dataset: ds.ExecutionDataset, filters: ExecFilters) -> set[str]:
    """The staff whose targets the selection covers: every Lead and their
    people (holding work in the period or not), narrowed as the table is."""
    lead_of = {key: info.lead_key for key, info in dataset.owners.items()}
    people: set[str] = set()
    for lead in dataset.leads:
        if filters.program_lead and lead.key != filters.program_lead:
            continue
        people.add(lead.key)
        people.update(person.key for person in dataset.rosters.get(lead.key, []))
    for key in dataset.owners:
        if key == NO_OWNER_KEY:
            continue
        if filters.program_lead and lead_of.get(key) != filters.program_lead:
            continue
        people.add(key)
    if filters.cceo:
        people = {filters.cceo}
    return people


def target_position(dataset: ds.ExecutionDataset, filters: ExecFilters) -> dict:
    """Planned output, validated actual and the remaining gap for the period's
    people (spec §23), read through the helper CD Analytics uses, which reads
    the same series and ledger as My Targets and Team Targets. Nothing here
    computes performance: the canonical helper does, for all of them."""
    window = dataset.window
    if window.period == "week":
        return {"status": "week"}
    if filters.region or filters.channel or filters.partner or filters.activity_type:
        # A target is a person's, not a region's, channel's, Partner's or
        # activity type's: no honest share of it follows those filters.
        return {"status": "people_only"}
    staff_ids = sorted(target_people(dataset, filters))
    if not staff_ids:
        return {"status": "none"}
    from apps.analytics.cd_analytics_service import CDAnalyticsService

    if window.period == "month":
        period = list(window.months_of_fy)
    elif window.period == "quarter":
        period = window.quarter
    else:
        period = None
    try:
        pct, achieved, target = CDAnalyticsService._weighted_achievement(
            window.fy, period, [], staff_ids
        )
    except Exception:  # noqa: BLE001 - the ledger note is not the page
        logger.warning("The target ledger could not be read", exc_info=True)
        return {"status": "error"}
    if not target:
        return {"status": "none"}
    return {
        "status": "ok",
        "target": target,
        "achieved": achieved,
        "gap": max(0, target - achieved),
        "pct": pct,
    }


def _fmt(value) -> str:
    return f"{value:,}" if isinstance(value, int) else "—"


def kpis(snapshot: ExecSnapshot) -> list[dict]:
    """The six figures (spec §8), each bound to its registered metric, with
    its denominator and its drill-down."""
    from apps.core.metrics import MetricValue, render_metric

    c = snapshot.tree.country
    query = snapshot.filters.query()

    def card(
        metric_key, key, part, *, ratio=True, note="", tone="neutral", icon="", stage=""
    ):
        href = f"{BASE_PATH}/drawer?kind=activities&stage={stage}&{query}"
        measured = (
            MetricValue.ratio(part, c.due) if ratio else MetricValue.measured(part)
        )
        rendered = render_metric(metric_key, measured, drilldown_url=href).as_dict()
        share = ExecTally.share(part, c.due) if ratio else None
        rendered.update(
            {
                "key": key,
                "value": _fmt(part),
                "share": share,
                "meter": max(0, min(100, share or 0)),
                "note": note,
                "tone": tone,
                "icon": icon,
                "href": href,
            }
        )
        return rendered

    return [
        card(
            "cxo_activities_due",
            "due",
            c.due,
            ratio=False,
            note=f"Unique schools: {snapshot.unique_schools:,}",
            icon="calendar",
            stage="due",
        ),
        # "Started on time" (spec §8.2) is the On-Time Execution reading,
        # which keeps work whose start was never recorded apart from late work.
        card(
            "cxo_started",
            "started",
            c.started,
            note=f"{_share_text(c.started_share)} of due",
            tone="good",
            icon="play",
            stage="started",
        ),
        card(
            "cxo_execution_completed",
            "executed",
            c.executed,
            note=f"{_share_text(c.executed_share)} of due",
            tone="info",
            icon="doc",
            stage="executed",
        ),
        card(
            "cxo_ia_verified",
            "verified",
            c.verified,
            note=f"{_share_text(c.verified_share)} of due",
            tone="violet",
            icon="check",
            stage="verified",
        ),
        card(
            "cxo_fully_closed",
            "closed",
            c.closed,
            note=f"{_share_text(c.closed_share)} of due",
            tone="deep",
            icon="flag",
            stage="closed",
        ),
        card(
            "cxo_overdue",
            "overdue",
            c.overdue,
            note=f"{_share_text(c.overdue_share)} of due · {c.carried_forward:,} carried forward",
            tone="alert",
            icon="alert",
            stage="overdue",
        ),
    ]


def _share_text(share) -> str:
    return "—" if share is None else f"{share}%"


def charts(snapshot: ExecSnapshot) -> dict:
    """Every chart's figures, finished (the browser divides nothing)."""
    tree = snapshot.tree
    c, staff, partner = tree.country, tree.staff, tree.partner_channel
    buckets = tree.buckets
    count = len(buckets)
    today = snapshot.dataset.today

    def cumulate(values: list[int], upto: int | None) -> list:
        out, running = [], 0
        for index, value in enumerate(values):
            running += value
            out.append(running if upto is None or index <= upto else None)
        return out

    current = next(
        (
            index
            for index, bucket in enumerate(buckets)
            if bucket.start <= today < bucket.end
        ),
        count - 1 if today >= buckets[-1].end else -1,
    )
    funnel_stages = (
        ("Due", "due"),
        ("Started", "started"),
        ("Evidence Submitted", "executed"),
        ("PL Reviewed (Staff only)", "pl_reviewed"),
        ("IA Verified", "verified"),
        ("Fully Closed", "closed"),
    )
    funnel = {
        "id": "cxo-funnel",
        "categories": [label for label, _ in funnel_stages],
        "series": [
            {"name": "Total", "data": [getattr(c, key) for _, key in funnel_stages]},
            {
                "name": "Staff",
                "data": [getattr(staff, key) for _, key in funnel_stages],
            },
            {
                "name": "Partner",
                # Partner work goes straight to IA: no PL stage to show.
                "data": [
                    None if key == "pl_reviewed" else getattr(partner, key)
                    for _, key in funnel_stages
                ],
            },
        ],
        "table": [
            [
                label,
                getattr(c, key),
                getattr(staff, key),
                "N/A" if key == "pl_reviewed" else getattr(partner, key),
            ]
            for label, key in funnel_stages
        ],
    }
    trend_series = [
        {"name": "Planned", "data": cumulate(c.trend("plan", count), None)},
        {
            "name": "Execution Completed",
            "data": cumulate(c.trend("exec", count), current),
        },
        {"name": "IA Verified", "data": cumulate(c.trend("ver", count), current)},
        {"name": "Fully Closed", "data": cumulate(c.trend("closed", count), current)},
    ]
    trend = {
        "id": "cxo-trend",
        "categories": [[bucket.label, bucket.caption] for bucket in buckets],
        "series": trend_series,
        "table": [
            {
                "label": f"{bucket.label} · {bucket.caption}",
                "cells": [s["data"][index] for s in trend_series],
            }
            for index, bucket in enumerate(buckets)
        ],
    }
    on_time_parts = [
        ("On time", c.on_time),
        ("Started late", c.late),
        ("Start not recorded", c.start_unknown),
        ("Not started", c.not_started),
        ("Not yet due", c.upcoming),
        ("Canceled", c.cancelled),
    ]
    on_time = {
        "id": "cxo-ontime",
        "center": _share_text(c.on_time_share),
        "center_caption": "on time",
        "parts": [
            {"label": label, "value": value}
            for label, value in on_time_parts
            if value or label in ("On time", "Not started")
        ],
    }
    backlog = {
        "id": "cxo-backlog",
        "center": _fmt(c.backlog),
        "center_caption": "open past due",
        "parts": [
            {"label": label, "value": c.values[ds.IDX[f"own_{key}"]], "key": key}
            for key, label in st.OWNERS
        ],
    }
    age = {
        "id": "cxo-age",
        "categories": [label for _, label, _, _ in st.AGE_GROUPS],
        "data": [c.values[ds.IDX[key]] for key, _, _, _ in st.AGE_GROUPS],
        "keys": [key for key, _, _, _ in st.AGE_GROUPS],
        "rows": [(label, c.values[ds.IDX[key]]) for key, label, _, _ in st.AGE_GROUPS],
    }
    outlook = forecast(c, snapshot.window, today)
    return {
        "funnel": funnel,
        "trend": trend,
        "on_time": on_time,
        "backlog": backlog,
        "age": age,
        "forecast": {**outlook, "text": _forecast_text(outlook, snapshot.window)},
    }


def _forecast_text(outlook: dict, window: Window) -> str:
    if outlook["status"] == "insufficient":
        return "Too little due work has reached its date to project this period."
    if outlook["status"] == "closed":
        return f"{window.label} has ended: {_share_text(outlook['share'])} of its due work was verified."
    return (
        f"At the current conversion, {_share_text(outlook['share'])} of the work due in "
        f"{window.label} is expected to be verified by its end."
    )


TABLE_COLUMNS = (
    ("due", "Due"),
    ("started", "Started"),
    ("executed", "Execution Completed"),
    ("verified", "IA Verified"),
    ("closed", "Fully Closed"),
    ("on_time", "On-Time %"),
    ("overdue", "Overdue"),
    ("carried_forward", "Carried Forward"),
    ("returned", "Returned"),
    ("remaining", "Remaining Slots"),
    ("forecast", "Forecast"),
    ("reminders", "Open Reminders"),
)


#: Past-due work a Programme Lead can reasonably act on (spec §10): their
#: team's and their Partners' execution, and their own review queue — not
#: IA's queue, the Accountant's money or a closed school.
LEAD_MANAGEABLE = ("staff", "pl", "partner")


def suggests_reminder(tally: ExecTally, reminders: int) -> bool:
    """Reminder Suggested (spec §20): past-due work the Lead can act on and no
    open reminder about it. A cue for the Director, who decides; nothing is
    ever sent by itself."""
    if reminders:
        return False
    return any(tally.values[ds.IDX[f"own_{owner}"]] for owner in LEAD_MANAGEABLE)


def row_cells(
    tally: ExecTally,
    *,
    remaining,
    reminders: int,
    window: Window,
    today: date,
    suggest: bool = False,
) -> dict:
    outlook = forecast(tally, window, today)
    return {
        "due": tally.due,
        "started": tally.started,
        "executed": tally.executed,
        "verified": tally.verified,
        "closed": tally.closed,
        "on_time": tally.on_time_share,
        "overdue": tally.overdue,
        "carried_forward": tally.carried_forward,
        "returned": tally.returned,
        "remaining": remaining,
        "forecast": outlook,
        "reminders": reminders,
        "blocker": _largest_blocker(tally),
        "suggested": suggest and suggests_reminder(tally, reminders),
    }


def _largest_blocker(tally: ExecTally) -> str:
    best = max(st.OWNERS, key=lambda item: tally.values[ds.IDX[f"own_{item[0]}"]])
    if tally.values[ds.IDX[f"own_{best[0]}"]] <= 0:
        return ""
    return "Waiting on " + ("PL review" if best[0] == "pl" else best[1])


def lead_rows(snapshot: ExecSnapshot, reminders: dict) -> list[dict]:
    today, window = snapshot.dataset.today, snapshot.window
    return [
        {
            "key": lead.key,
            "name": lead.name,
            "is_no_lead": lead.is_no_lead,
            "has_children": bool(lead.owners),
            "cells": row_cells(
                lead.tally,
                remaining=snapshot.remaining.get(("lead", lead.key)),
                reminders=reminders.get(("lead", lead.key), 0),
                window=window,
                today=today,
                suggest=not lead.is_no_lead,
            ),
        }
        for lead in snapshot.tree.leads
    ]


def owner_rows(
    snapshot: ExecSnapshot, lead_key: str | None, reminders: dict
) -> list[dict]:
    today, window = snapshot.dataset.today, snapshot.window
    out = []
    for lead in snapshot.tree.leads:
        if lead_key is not None and lead.key != lead_key:
            continue
        for owner in lead.owners:
            out.append(
                {
                    "key": owner.key,
                    "name": owner.label,
                    "person": owner.name,
                    "kind": owner.kind,
                    "lead_key": lead.key,
                    "lead_name": lead.name,
                    "has_children": bool(owner.partners),
                    "cells": row_cells(
                        owner.tally,
                        remaining=snapshot.remaining.get(("owner", owner.key)),
                        reminders=reminders.get(("owner", owner.key), 0),
                        window=window,
                        today=today,
                        suggest=lead.key != NO_LEAD_KEY,
                    ),
                }
            )
    return out


def owner_partner_rows(snapshot: ExecSnapshot, owner_key: str) -> list[dict]:
    today, window = snapshot.dataset.today, snapshot.window
    owner = find_owner(snapshot, owner_key)
    if owner is None:
        return []
    names = snapshot.dataset.partner_names
    rows = []
    for key, tally in owner.partners.items():
        rows.append(
            {
                "key": key,
                "name": "Staff delivery"
                if key == ds.STAFF_KEY
                else names.get(key, "Unrecorded Partner"),
                "is_staff": key == ds.STAFF_KEY,
                "cells": row_cells(
                    tally, remaining=None, reminders=0, window=window, today=today
                ),
            }
        )
    rows.sort(key=lambda row: (row["is_staff"], row["name"].casefold()))
    return rows


def find_owner(snapshot: ExecSnapshot, owner_key: str):
    for lead in snapshot.tree.leads:
        for owner in lead.owners:
            if owner.key == owner_key:
                return owner
    return None


def find_lead(snapshot: ExecSnapshot, lead_key: str):
    return next((lead for lead in snapshot.tree.leads if lead.key == lead_key), None)


def partner_rows(snapshot: ExecSnapshot) -> list[dict]:
    """Each Partner organisation's delivery (spec §15). IA returns and payment
    are read from the Partner's own records; nothing waits on a PL here."""
    dataset = snapshot.dataset
    names = dataset.partner_names
    records_by_partner: dict[str, list] = {}
    for record in filtered_records(dataset, snapshot.filters):
        if record.channel == "partner":
            records_by_partner.setdefault(record.partner_key, []).append(record)
    unscheduled = _unscheduled_by_partner(dataset, snapshot.filters)
    rows = []
    for key in sorted(
        set(records_by_partner) | set(unscheduled),
        key=lambda k: names.get(k, "").casefold(),
    ):
        records = records_by_partner.get(key, [])
        live = [r for r in records if not r.cancelled]
        rows.append(
            {
                "key": key,
                "name": names.get(key, "Unrecorded Partner")
                if key
                else "Partner not recorded",
                "due": len(live),
                "started": sum(1 for r in live if r.started),
                "executed": sum(1 for r in live if r.executed),
                "returned": sum(1 for r in live if r.returned),
                "verified": sum(1 for r in live if r.verified),
                "awaiting_payment": sum(1 for r in live if r.verified and not r.paid),
                "paid": sum(1 for r in live if r.paid),
                "closed": sum(1 for r in live if r.closed),
                "overdue": sum(1 for r in live if r.overdue),
                "unscheduled": unscheduled.get(key, 0),
                "schools": len(
                    {r.school_id for r in live if r.school_id and r.executed}
                ),
            }
        )
    return rows


def _unscheduled_by_partner(dataset, filters: ExecFilters) -> dict:
    """Handovers not yet dated by the Partner, made in the year (spec §15)."""
    from django.db.models import Count

    from apps.core.fy import get_fy_date_range
    from apps.partners.models import PartnerAssignment

    start, end = get_fy_date_range(dataset.window.fy)
    rows = PartnerAssignment.objects.filter(
        status__in=PartnerAssignment.UNSCHEDULED_STATUSES,
        created_at__gte=start,
        created_at__lt=end,
    )
    if filters.partner:
        rows = rows.filter(partner_id=filters.partner)
    if filters.region:
        rows = rows.filter(school__region_id=filters.region)
    return dict(
        rows.values("partner_id").annotate(n=Count("id")).values_list("partner_id", "n")
    )


ACTIVITIES_PER_PAGE = 50

#: What each KPI's drill-down lists.
STAGE_FILTERS = {
    "due": lambda r: not r.cancelled,
    "started": lambda r: r.started and not r.cancelled,
    "not_started": lambda r: not r.started and not r.cancelled,
    "executed": lambda r: r.executed,
    "pl_review": lambda r: r.stage == "pl_review",
    "ia_review": lambda r: r.stage == "ia_review",
    "verified": lambda r: r.verified,
    "closed": lambda r: r.closed,
    "returned": lambda r: r.returned,
    "overdue": lambda r: bool(r.overdue),
    "finance": lambda r: r.finance_open,
    "cancelled": lambda r: r.cancelled,
}


def activity_rows(
    snapshot: ExecSnapshot,
    *,
    stage: str = "",
    owner_key: str = "",
    lead_key: str = "",
    partner_key: str = "",
    blocker: str = "",
    age: str = "",
    page: int = 1,
) -> dict:
    """The records behind a figure, the oldest past-due first."""
    dataset = snapshot.dataset
    test = STAGE_FILTERS.get(stage)
    owners = dataset.owners
    picked = []
    for record in filtered_records(dataset, snapshot.filters):
        if test is not None and not test(record):
            continue
        if owner_key and record.owner_key != owner_key:
            continue
        if lead_key:
            info = owners.get(record.owner_key)
            if (info.lead_key if info else NO_LEAD_KEY) != lead_key:
                continue
        if partner_key and record.partner_key != partner_key:
            continue
        if blocker and record.owner != blocker:
            continue
        if age and st.age_group(record.age) != age:
            continue
        picked.append(record)
    picked.sort(key=lambda r: (-r.age, r.due or date.min, r.id))
    total = len(picked)
    pages = max(1, (total + ACTIVITIES_PER_PAGE - 1) // ACTIVITIES_PER_PAGE)
    page = min(max(1, page), pages)
    window_rows = picked[(page - 1) * ACTIVITIES_PER_PAGE : page * ACTIVITIES_PER_PAGE]
    return {
        "rows": _describe(dataset, window_rows),
        "total": total,
        "page": page,
        "pages": pages,
    }


def _describe(dataset, records) -> list[dict]:
    from apps.planning.country_oversight.service import _names

    schools = _names("schools.School", {r.school_id for r in records})
    clusters = _names("clusters.Cluster", {r.cluster_id for r in records})
    owners = dataset.owners
    out = []
    for r in records:
        info = owners.get(r.owner_key)
        out.append(
            {
                "id": r.id,
                "type": dataset.type_labels.get(
                    r.activity_type, r.activity_type.replace("_", " ").title()
                ),
                "where": schools.get(r.school_id) or clusters.get(r.cluster_id) or "—",
                "owner": info.name if info else NO_OWNER_LABEL,
                "lead": info.lead_name if info else NO_LEAD_LABEL,
                "channel": "Partner" if r.channel == "partner" else "Staff",
                "partner": dataset.partner_names.get(r.partner_key, "")
                if r.channel == "partner"
                else "",
                "due": r.due,
                "stage": st.STAGE_LABELS.get(r.stage, r.stage),
                "stage_key": r.stage,
                "overdue": st.OVERDUE_LABELS.get(r.overdue, ""),
                "age": r.age,
                "waiting_on": st.OWNER_LABELS.get(r.owner, ""),
                "last_action": r.last_action,
            }
        )
    return out


SCHOOLS_PER_PAGE = 50


def school_completion_rows(
    user, filters: ExecFilters, *, page: int = 1, owner_key: str = ""
) -> dict:
    """Required-slot completion school by school (spec §16), worst first:
    "Visits: 3 of 4 verified · Staff 2 of 2 · Partner 1 of 2 · 1 Partner
    visit remaining". Read from the planning coverage dataset for the same
    window (a week reads its year), so a school's obligation is the one the
    Planning tab shows, and "verified" is the programme-completion level."""
    from apps.planning.country_oversight import service as planning
    from apps.planning.country_oversight.coverage import claims_for

    pfilters = filters.planning()
    dataset = planning.dataset_for(user, pfilters.window)
    owners = dataset.owners
    groups = (
        [dataset.by_owner.get(owner_key, ())]
        if owner_key
        else list(dataset.by_owner.values())
    )
    picked = []
    for schools in groups:
        for school in schools:
            if not school.is_governed:
                continue
            if not planning._keeps(school, owners.get(school.owner_key), pfilters):
                continue
            claims = claims_for(school, dataset.allocations[school.id], dataset.window)
            staff_left = max(0, claims.staff_expected - claims.staff_verified)
            partner_left = max(0, claims.partner_expected - claims.partner_verified)
            # A flexible (Client) slot is one slot, whoever delivers it.
            visit_left = max(
                0, claims.visit_slots - claims.staff_verified - claims.partner_verified
            )
            training_left = max(0, claims.training_slots - claims.training_verified)
            picked.append(
                (
                    visit_left + training_left,
                    school,
                    claims,
                    staff_left,
                    partner_left,
                    visit_left,
                    training_left,
                )
            )
    picked.sort(key=lambda item: (-item[0], item[1].name.casefold(), item[1].id))
    total = len(picked)
    pages = max(1, (total + SCHOOLS_PER_PAGE - 1) // SCHOOLS_PER_PAGE)
    page = min(max(1, page), pages)
    rows = []
    for (
        gap,
        school,
        claims,
        staff_left,
        partner_left,
        visit_left,
        training_left,
    ) in picked[(page - 1) * SCHOOLS_PER_PAGE : page * SCHOOLS_PER_PAGE]:
        owner = owners.get(school.owner_key)
        verified = claims.staff_verified + claims.partner_verified
        remaining_bits = []
        if school.family == CORE_FAMILY:
            if staff_left:
                remaining_bits.append(
                    f"{staff_left} staff visit{'s' if staff_left != 1 else ''}"
                )
            if partner_left:
                remaining_bits.append(
                    f"{partner_left} Partner visit{'s' if partner_left != 1 else ''}"
                )
        elif visit_left:
            remaining_bits.append(f"{visit_left} visit")
        if training_left:
            remaining_bits.append(
                f"{training_left} training{'s' if training_left != 1 else ''}"
            )
        rows.append(
            {
                "id": school.id,
                "code": school.code,
                "name": school.name,
                "type": school.school_type.replace("_", " ").title(),
                "owner": owner.name if owner else NO_OWNER_LABEL,
                "lead": owner.lead_name if owner else NO_LEAD_LABEL,
                "visit_slots": claims.visit_slots,
                "visits_verified": verified,
                "visits_planned": claims.cum_staff + claims.cum_partner_scheduled,
                "staff": (claims.staff_verified, claims.staff_expected),
                "partner": (claims.partner_verified, claims.partner_expected),
                "training": (claims.training_verified, claims.training_slots),
                "training_planned": claims.cum_training,
                "meeting": claims.cum_meeting_covered,
                "remaining": " · ".join(remaining_bits) or "Complete",
                "gap": gap,
            }
        )
    return {
        "rows": rows,
        "total": total,
        "page": page,
        "pages": pages,
        "as_year": filters.period == "week",
    }


ISSUE_ORDER = (
    ("execution_staff", "Activity not started"),
    ("evidence", "Evidence submission overdue"),
    ("correction", "Returned work not corrected"),
    ("pl_review", "PL review pending"),
    ("ia_review", "IA verification pending"),
    ("partner", "Partner execution delay"),
    ("external", "School unavailable"),
    ("funds", "Funding delayed"),
    ("finance", "Finance closure pending"),
    ("closure", "Closure checklist pending"),
)


def issues(snapshot: ExecSnapshot) -> list[dict]:
    """Past-due work by its first cause (spec §27.3), from the records' stage
    and owner: each record counts once."""
    counts: dict[str, int] = {key: 0 for key, _ in ISSUE_ORDER}
    for r in filtered_records(snapshot.dataset, snapshot.filters):
        if r.cancelled or not (r.overdue or r.finance_open):
            continue
        if r.finance_open:
            # Verified, not closed: the Accountant's (payment, accounts,
            # NetSuite) or the closure checklist's (Salesforce ID, analytics).
            counts["finance" if r.owner == "finance" else "closure"] += 1
        elif r.owner == "external":
            counts["external"] += 1
        elif r.owner == "finance":
            counts["funds"] += 1
        elif r.channel == "partner" and r.overdue in (
            "execution",
            "evidence",
            "correction",
        ):
            counts["partner"] += 1
        elif r.overdue == "execution":
            counts["execution_staff"] += 1
        elif r.overdue in counts:
            counts[r.overdue] += 1
    total = sum(counts.values())
    return [
        {
            "key": key,
            "label": label,
            "count": counts[key],
            "share": ExecTally.share(counts[key], total),
        }
        for key, label in ISSUE_ORDER
        if counts[key]
    ]


def recent_activity(
    snapshot: ExecSnapshot, *, days: int = 14, limit: int = 8
) -> list[dict]:
    """What moved lately, by day: verifications (by IA or the Lead), work
    returned, schedules moved, and follow-ups sent."""
    from datetime import timedelta

    from apps.planning.followup_models import PlanningOversightFollowUp

    dataset = snapshot.dataset
    since = dataset.today - timedelta(days=days)
    events: dict[tuple, int] = {}
    for r in filtered_records(dataset, snapshot.filters):
        if r.verified_day and r.verified_day >= since:
            events[
                (
                    r.verified_day,
                    "Verified",
                    "partner" if r.channel == "partner" else "staff",
                )
            ] = (
                events.get(
                    (
                        r.verified_day,
                        "Verified",
                        "partner" if r.channel == "partner" else "staff",
                    ),
                    0,
                )
                + 1
            )
        if r.returned and r.last_action and r.last_action >= since:
            events[(r.last_action, "Returned for correction", "")] = (
                events.get((r.last_action, "Returned for correction", ""), 0) + 1
            )
        if r.executed and not r.verified and r.last_action and r.last_action >= since:
            events[(r.last_action, "Evidence submitted", "")] = (
                events.get((r.last_action, "Evidence submitted", ""), 0) + 1
            )
    rows = []
    for (day, what, channel), n in events.items():
        detail = f"{n} {'activity' if n == 1 else 'activities'}"
        if what == "Verified":
            detail += " verified" + (
                " (Partner work, by IA)" if channel == "partner" else " (staff work)"
            )
        rows.append({"date": day, "what": what, "detail": detail})
    for followup in PlanningOversightFollowUp.objects.filter(
        module="execution", assigned_at__date__gte=since
    ).order_by("-assigned_at")[:limit]:
        rows.append(
            {
                "date": timezone.localtime(followup.assigned_at).date(),
                "what": "Follow-up sent",
                "detail": f"To {followup.program_lead_name}: {followup.remaining_value:,} open",
            }
        )
    rows.sort(key=lambda row: row["date"], reverse=True)
    return rows[:limit]


def header(snapshot: ExecSnapshot) -> dict:
    from apps.planning.country_oversight.service import deployment_country

    window = snapshot.window
    built = snapshot.dataset.built_at
    return {
        "fy_label": fy_label(window.fy),
        "window_label": window.label,
        "period_label": PERIOD_LABELS.get(window.period, "Annual"),
        "built_at": timezone.localtime(built) if timezone.is_aware(built) else built,
        "today": snapshot.dataset.today,
        "country": snapshot.dataset.scope_label or deployment_country(),
        "integrity": snapshot.dataset.integrity,
    }


class CountryExecutionOversightService:
    """The tab's one service, as an importable surface."""

    read_filters = staticmethod(read_filters)
    dataset_for = staticmethod(dataset_for)
    snapshot_for = staticmethod(snapshot_for)
    fold = staticmethod(fold)
    kpis = staticmethod(kpis)
    charts = staticmethod(charts)
    lead_rows = staticmethod(lead_rows)
    owner_rows = staticmethod(owner_rows)
    partner_rows = staticmethod(partner_rows)
    activity_rows = staticmethod(activity_rows)
    issues = staticmethod(issues)
    forecast = staticmethod(forecast)
    warm = staticmethod(warm)
