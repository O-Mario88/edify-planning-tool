"""CountryPlanningOversightService — one dataset behind every surface of the page.

The strip, the four charts, the drill-down table, the drawers, the export and
the follow-up snapshots all read the same tree, built from the same filtered
set of schools. A graph and a table cannot disagree because there is nothing
else for either to read, and the browser is handed finished figures — it
divides nothing.

**Reads, cached and bounded.** The per-school facts are a handful of grouped
queries whatever the size of the estate; the tree is a fold over them. Both
are kept for ``DASHBOARD_CACHE_SECONDS`` under a key that names the reader's
school universe (a country role's country, a region role's regions), the
window, the filters and the policy version — so no reader is ever served
figures from outside their scope, and the page says when its figures were
read. Refresh drops the snapshot. Drawers that list schools read the records
live for the portfolio they open.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field, fields, replace
from datetime import date, datetime
from functools import cached_property

from django.utils import timezone

from apps.planning.country_oversight import people as people_read
from apps.planning.country_oversight import policy, rules
from apps.planning.country_oversight.coverage import (
    P_RETURNED,
    FactsTable,
    SchoolFacts,
    Window,
    annual_position,
    claims_for,
    duplicate_reasons,
    fy_label,
    load_facts,
    window_for,
)
from apps.planning.country_oversight.hierarchy import (
    I_AWAITING,
    I_UNALLOCATED,
    I_UNMAPPED,
    I_PEOPLE,
    IDX,
    TYPE_FIELDS,
    LeadRow,
    OwnerRow,
    Tally,
    Tree,
    blank,
    phase,
    planning_state,
    school_values,
    state_of,
    sum_vectors,
)
from apps.planning.country_oversight.requirements import (
    NO_LEAD_KEY,
    NO_LEAD_LABEL,
    NO_OWNER_KEY,
    NO_OWNER_LABEL,
    OwnerInfo,
    allocate,
    eligible_school_queryset,
    historical_adjustments,
    owner_directory,
    reporting_date,
    roster_for,
)

logger = logging.getLogger(__name__)

PAGE_PATH = "/country-planning-oversight/"

# ── Filters ──────────────────────────────────────────────────────────────────
PERIODS = ("fy", "quarter", "month", "week")
#: The school types a reader can narrow the page to (the rulebook's order).
TYPE_OPTIONS = tuple(
    (school_type, rules.TYPE_LABELS[school_type]) for school_type in rules.TYPE_ORDER
)
CHANNEL_OPTIONS = (("staff", "Staff"), ("partner", "Partner"))
CLUSTER_OPTIONS = (("clustered", "Clustered"), ("unclustered", "Unclustered"))
STATUS_OPTIONS = (
    ("full", "Fully planned"),
    ("partial", "Partially planned"),
    ("none", "Not planned"),
    ("awaiting", "Awaiting Partner schedule"),
)


@dataclass(frozen=True)
class Filters:
    """Everything that narrows the page. Every surface reads the same one."""

    fy: str
    period: str = "fy"
    quarter: str = ""
    month: int | None = None
    week: str = ""
    region: str = ""
    district: str = ""
    program_lead: str = ""
    cceo: str = ""
    school_type: str = ""
    channel: str = ""
    partner: str = ""
    cluster_status: str = ""
    planning_status: str = ""

    # Filters that pick schools (the period only moves the window).
    SCHOOL_FILTERS = (
        "region",
        "district",
        "program_lead",
        "cceo",
        "school_type",
        "channel",
        "partner",
        "cluster_status",
        "planning_status",
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
        out = {"fy": values["fy"], "period": values["period"]}
        if values["period"] == "quarter" and values["quarter"]:
            out["quarter"] = values["quarter"]
        if values["period"] == "month" and values["month"]:
            out["month"] = values["month"]
        if values["period"] == "week" and values["week"]:
            out["week"] = values["week"]
        for name in self.SCHOOL_FILTERS:
            if values.get(name):
                out[name] = values[name]
        return out

    def query(self, **overrides) -> str:
        from urllib.parse import urlencode

        return urlencode(self.params(**overrides))

    @property
    def active_school_filters(self) -> int:
        return sum(1 for name in self.SCHOOL_FILTERS if getattr(self, name))

    def without_school_filters(self) -> "Filters":
        return replace(self, **{name: "" for name in self.SCHOOL_FILTERS})


def read_filters(request) -> Filters:
    """The page's filters from a request. Old period links keep their meaning."""
    from apps.core.fy import get_operational_fy

    # A form posted from the page carries the page's filters with it.
    get = request.POST if request.method == "POST" and request.POST else request.GET
    fy = (get.get("fy") or "").strip() or get_operational_fy()
    if not fy.isdigit():
        fy = get_operational_fy()
    raw_month = (get.get("month") or "").strip()
    month = (
        int(raw_month) if raw_month.isdigit() and 1 <= int(raw_month) <= 12 else None
    )
    quarter = (get.get("quarter") or "").strip().upper()
    quarter = quarter if quarter in ("Q1", "Q2", "Q3", "Q4") else ""
    period = (get.get("period") or "").strip().lower()
    if period not in PERIODS:
        period = "month" if month else "quarter" if quarter else "fy"
    week = (get.get("week") or "").strip()
    today = date.today()
    if period == "quarter" and not quarter:
        from apps.core.fy import get_quarter_for_date

        quarter = get_quarter_for_date(today)
    if period == "month" and not month:
        month = today.month
    if period == "week" and not week:
        week = today.strftime("%G-W%V")

    def pick(name, allowed=None):
        value = (get.get(name) or "").strip()
        if allowed is not None and value not in allowed:
            return ""
        return value if value not in ("all", "All") else ""

    return Filters(
        fy=fy,
        period=period,
        quarter=quarter if period == "quarter" else "",
        month=month if period == "month" else None,
        week=week if period == "week" else "",
        region=pick("region"),
        district=pick("district"),
        program_lead=pick("program_lead"),
        cceo=pick("cceo"),
        school_type=pick("school_type", {key for key, _ in TYPE_OPTIONS})
        # A link made before the page read schools by type named a family.
        or {"core_family": "core"}.get(pick("family"), ""),
        channel=pick("channel", {key for key, _ in CHANNEL_OPTIONS}),
        partner=pick("partner"),
        cluster_status=pick("cluster_status", {key for key, _ in CLUSTER_OPTIONS}),
        planning_status=pick("planning_status", {key for key, _ in STATUS_OPTIONS}),
    )


# ── Scope ────────────────────────────────────────────────────────────────────
def universe_key(scope) -> str:
    """Which schools this reader's figures are built from — the part of the
    cache key that keeps one country's figures out of another's page."""
    if getattr(scope, "country_scope", False):
        return f"country:{getattr(scope, 'country', '') or '*'}"
    if getattr(scope, "region_scope", False):
        return "region:" + (",".join(sorted(scope.region_ids or [])) or "-")
    if getattr(scope, "can_view_summary_only", False):
        if getattr(scope, "rvp_region_scoped", False):
            return "rvp:" + ",".join(sorted(scope.region_ids or []))
        return "rvp:*"
    digest = hashlib.sha256(",".join(sorted(scope.school_ids or [])).encode())
    return f"schools:{digest.hexdigest()[:16]}"


def _timeout() -> int:
    from django.conf import settings

    return int(getattr(settings, "DASHBOARD_CACHE_SECONDS", 0) or 0)


# ── The dataset ──────────────────────────────────────────────────────────────
@dataclass
class Dataset:
    window: Window
    as_of: date
    built_at: datetime
    facts: dict  # school id → SchoolRecord (a FactsTable)
    owners: dict  # canonical owner key → OwnerInfo
    leads: list
    rosters: dict
    partner_names: dict
    region_names: dict
    district_names: dict
    allocations: dict
    scope_label: str = ""
    universe: str = ""
    policy_version: str = policy.POLICY_VERSION
    # channel ("" | "staff" | "partner") → (cells, partner cells, unmapped):
    # the schools' figures summed per filterable attribute (see Rollup). The
    # unfiltered channel is made with the dataset; the others on first use.
    cells: dict = field(default_factory=dict)
    # Which build this is: a worker holding a copy compares it with the
    # stamp published beside the cached dataset (see dataset_for).
    stamp: str = field(default_factory=lambda: uuid.uuid4().hex)

    @cached_property
    def by_owner(self) -> dict:
        """owner key → that owner's records, for this process only."""
        grouped: dict[str, list] = {}
        for school in self.facts.values():
            grouped.setdefault(school.owner_key, []).append(school)
        return grouped

    def __getstate__(self):
        state = dict(self.__dict__)
        state.pop("by_owner", None)  # rebuilt on demand; not worth caching
        return state


_SCHOOL_COLUMNS = (
    "id",
    "school_id",
    "name",
    "school_type",
    "account_owner_id",
    "region_id",
    "district_id",
    "cluster_id",
    "cluster_status",
)


def build_dataset(
    scope,
    window: Window,
    *,
    base=None,
    today: date | None = None,
    universe: str = "",
) -> Dataset:
    """The facts for every school in ``scope`` operating on the reporting date.

    ``base`` narrows the schools (a drawer reads one owner's portfolio); the
    allocation is still made per owner over what is read, so ``base`` must
    always hold whole portfolios.
    """
    as_of = reporting_date(window.fy, today)
    queryset = eligible_school_queryset(scope, as_of, base)
    rows = list(queryset.values_list(*_SCHOOL_COLUMNS)) if queryset is not None else []
    owner_as_of, type_as_of = ({}, {})
    if rows and as_of < (today or date.today()):
        owner_as_of, type_as_of = historical_adjustments([r[0] for r in rows], as_of)
    facts = load_facts(
        rows,
        window,
        school_ids=queryset.values("id") if queryset is not None else [],
        owner_as_of=owner_as_of,
        type_as_of=type_as_of,
    )

    directory = owner_directory({f.raw_owner_id for f in facts.values()})
    owners: dict[str, OwnerInfo] = {}
    for school in facts.values():
        info = directory.get(str(school.raw_owner_id or ""))
        if info is None:
            school.owner_key = NO_OWNER_KEY
        else:
            school.owner_key = info.key
            owners.setdefault(info.key, info)
    if any(f.owner_key == NO_OWNER_KEY for f in facts.values()):
        owners[NO_OWNER_KEY] = OwnerInfo(
            key=NO_OWNER_KEY, name=NO_OWNER_LABEL, active=False
        )

    by_owner: dict[str, list[SchoolFacts]] = {}
    for school in facts.values():
        annual_position(school)
        by_owner.setdefault(school.owner_key, []).append(school)
    allocations = {}
    for owner_key, schools in by_owner.items():
        allocations.update(allocate(owners.get(owner_key), schools))

    # Each school's figures, read once: kept on the record for the school
    # lists, and summed into the cells every filter combination is read from.
    shared: dict = {}
    records = FactsTable()
    roller = _Roller("")
    for school in facts.values():
        if school.is_governed:
            claims = claims_for(school, allocations[school.id], window)
            record = school.freeze(tuple(school_values(school, claims)), shared)
            roller.add(record, record.vector, claims)
        else:
            record = school.freeze((), shared)
            roller.add_unmapped(record)
        records[record.id] = record

    # Every Lead and their CCEOs, each Lead's own row first (see _tree).
    leads, rosters = roster_for(getattr(scope, "country", "") or "")

    partner_ids = {
        pid for school in facts.values() for pid in (school.partners or {}) if pid
    }
    partner_names = _names("partners.Partner", partner_ids)
    region_names = _names("geography.Region", {f.region_id for f in facts.values()})
    district_names = _names(
        "geography.District", {f.district_id for f in facts.values()}
    )
    return Dataset(
        window=window,
        as_of=as_of,
        built_at=timezone.now(),
        facts=records,
        owners=owners,
        leads=leads,
        rosters=rosters,
        partner_names=partner_names,
        region_names=region_names,
        district_names=district_names,
        allocations=allocations,
        scope_label=(getattr(scope, "country", "") or "").strip(),
        universe=universe,
        cells={"": roller.done()},
    )


def _names(model_label: str, ids) -> dict[str, str]:
    from django.apps import apps

    ids = {i for i in ids if i}
    if not ids:
        return {}
    model = apps.get_model(model_label)
    manager = getattr(model, "all_objects", model.objects)
    return dict(manager.filter(id__in=ids).values_list("id", "name"))


def _key(kind: str, universe: str, window: Window) -> str:
    return (
        f"cpo:{kind}:v4:{policy.POLICY_VERSION}:{universe}:{window.cache_part}:"
        f"{reporting_date(window.fy).isoformat()}"
    )


def dataset_for(user, window: Window, *, refresh: bool = False) -> Dataset:
    """The reader's dataset for the window, from the snapshot when there is one.

    A worker keeps the last dataset it read. Reading a whole country's schools
    back from the shared cache costs ~100 ms at 50,000 schools, on every list
    of schools a drawer opens; the copy the worker already holds is used
    instead whenever the stamp published beside the cached dataset says it is
    the same build — so a rebuild anywhere (the warmer, a Refresh) is seen by
    every worker on its next request, and nothing is served that the shared
    cache would not serve.
    """
    from apps.core.cache_utils import forget_snapshot, stampede_safe_get_or_compute
    from apps.core.scoping import resolve_user_scope

    scope = resolve_user_scope(user)
    universe = universe_key(scope)
    key = _key("facts", universe, window)
    timeout = _timeout()
    if refresh:
        forget_snapshot(key)
        forget_snapshot(_stamp_key(key))
        _HELD.pop(key, None)
    elif timeout > 0:
        held = _HELD.get(key)
        if held is not None and held.stamp == _read_stamp(key):
            return held

    built: list[Dataset] = []

    def build():
        built.append(build_dataset(scope, window, universe=universe))
        return built[0]

    dataset = stampede_safe_get_or_compute(key, build, timeout=timeout)
    if timeout > 0:
        # The builder publishes its stamp after the dataset is stored; a
        # reader of a dataset whose stamp has gone restores it, but never
        # over a newer one.
        _write_stamp(key, dataset.stamp, timeout=timeout, replace=bool(built))
        _HELD.clear()
        _HELD[key] = dataset
    return dataset


#: The dataset this worker last read (one: a whole country's schools is
#: ~35 MB of records at 50,000 schools).
_HELD: dict[str, Dataset] = {}


def _stamp_key(key: str) -> str:
    return f"{key}:stamp"


def _read_stamp(key: str) -> str | None:
    from django.core.cache import cache

    from apps.core.cache_utils import snapshot_key

    try:
        return cache.get(snapshot_key(_stamp_key(key)))
    except Exception:  # noqa: BLE001 - no stamp means read the shared copy
        return None


def _write_stamp(key: str, stamp: str, *, timeout: int, replace: bool) -> None:
    from django.core.cache import cache

    from apps.core.cache_utils import snapshot_key

    try:
        if replace:
            cache.set(snapshot_key(_stamp_key(key)), stamp, timeout=timeout)
        else:
            cache.add(snapshot_key(_stamp_key(key)), stamp, timeout=timeout)
    except Exception:  # noqa: BLE001 - workers then read the shared copy
        logger.warning("Could not publish the dataset stamp", exc_info=True)


# ── The rollup ───────────────────────────────────────────────────────────────
@dataclass
class Rollup:
    """Every school's figures, summed by each attribute the page filters on.

    A cell is one owner's schools in one region, district, school type,
    cluster state and planning state. Any combination of those filters is a set of
    whole cells, so the tree for new filters is a pass over a few thousand
    cells rather than every school — and the rollup is kept apart from the
    school facts, so a filter change never reads them. The figures in a cell
    are the schools' own, summed; nothing is re-derived, so a tree folded from
    the rollup is the tree folded school by school (the tests hold them equal).
    """

    channel: str
    window: Window
    as_of: date
    built_at: datetime
    owners: dict
    leads: list
    rosters: dict
    partner_names: dict
    region_names: dict
    district_names: dict
    cells: dict
    partner_cells: dict
    unmapped: dict
    scope_label: str = ""
    universe: str = ""


class _Roller:
    """Sums school vectors into rollup cells as the schools are read."""

    def __init__(self, channel: str):
        self.channel = channel
        self.cells: dict[tuple, list] = {}
        self.partner_cells: dict[tuple, list] = {}
        self.unmapped: dict[tuple, int] = {}

    def add(self, school, vector, claims) -> None:
        place = (
            school.owner_key,
            school.region_id,
            school.district_id,
            school.school_type,
            school.cluster_id is not None,
            state_of(vector),
            vector[I_AWAITING],
        )
        self.cells.setdefault(place, []).append(vector)
        partners = school.partners
        if partners and self.channel != "staff":
            shares = claims.by_partner or {}
            for pid, counts in partners.items():
                share = shares.get(pid) or (0, 0, 0, counts[P_RETURNED])
                self.partner_cells.setdefault((*place, pid), []).append(
                    _partner_values(vector, share)
                )
        else:
            self.partner_cells.setdefault((*place, NO_PARTNER_KEY), []).append(vector)

    def add_unmapped(self, school) -> None:
        key = (
            school.owner_key,
            school.region_id,
            school.district_id,
            school.cluster_id is not None,
        )
        self.unmapped[key] = self.unmapped.get(key, 0) + 1

    def done(self) -> tuple[dict, dict, dict]:
        return (
            {key: sum_vectors(rows) for key, rows in self.cells.items()},
            {key: sum_vectors(rows) for key, rows in self.partner_cells.items()},
            dict(self.unmapped),
        )


def rollup_of(dataset: Dataset, channel: str = "") -> Rollup:
    """The dataset's rollup for a delivery channel ("" is both)."""
    channel = channel or ""
    cells = dataset.cells.get(channel)
    if cells is None:
        roller = _Roller(channel)
        window = dataset.window
        for school in dataset.facts.values():
            if not school.is_governed:
                roller.add_unmapped(school)
                continue
            claims = claims_for(
                school,
                dataset.allocations[school.id],
                window,
                channel=channel or None,
            )
            roller.add(school, tuple(school_values(school, claims)), claims)
        cells = dataset.cells[channel] = roller.done()
    return Rollup(
        channel=channel,
        window=dataset.window,
        as_of=dataset.as_of,
        built_at=dataset.built_at,
        owners=dataset.owners,
        leads=dataset.leads,
        rosters=dataset.rosters,
        partner_names=dataset.partner_names,
        region_names=dataset.region_names,
        district_names=dataset.district_names,
        cells=cells[0],
        partner_cells=cells[1],
        unmapped=cells[2],
        scope_label=dataset.scope_label,
        universe=dataset.universe,
    )


def rollup_for(
    user, window: Window, channel: str = "", *, refresh: bool = False
) -> Rollup:
    """The reader's rollup for the window and channel, cached on its own."""
    from apps.core.cache_utils import forget_snapshot, stampede_safe_get_or_compute
    from apps.core.scoping import resolve_user_scope

    universe = universe_key(resolve_user_scope(user))
    key = f"{_key('rollup', universe, window)}:{channel or 'all'}"
    if refresh:
        forget_snapshot(key)
    return stampede_safe_get_or_compute(
        key,
        lambda: rollup_of(dataset_for(user, window, refresh=refresh), channel),
        timeout=_timeout(),
    )


# ── The tree ─────────────────────────────────────────────────────────────────
def _keeps_place(
    filters: Filters,
    owner_key: str,
    lead_key: str,
    region_id,
    district_id,
    school_type: str,
    clustered: bool,
) -> bool:
    if filters.region and region_id != filters.region:
        return False
    if filters.district and district_id != filters.district:
        return False
    if filters.school_type and school_type != filters.school_type:
        return False
    if filters.cluster_status == "clustered" and not clustered:
        return False
    if filters.cluster_status == "unclustered" and clustered:
        return False
    if filters.cceo and owner_key != filters.cceo:
        return False
    if filters.program_lead and lead_key != filters.program_lead:
        return False
    return True


def _keeps(school, owner: OwnerInfo | None, filters: Filters) -> bool:
    if filters.partner and filters.partner not in (school.partners or {}):
        return False
    return _keeps_place(
        filters,
        school.owner_key,
        owner.lead_key if owner is not None else NO_LEAD_KEY,
        school.region_id,
        school.district_id,
        school.school_type,
        school.cluster_id is not None,
    )


def _state_matches(filters: Filters, state: str, awaiting) -> bool:
    wanted = filters.planning_status
    if not wanted:
        return True
    if wanted == "awaiting":
        return bool(awaiting)
    return state == wanted


def _status_matches(claims, filters: Filters) -> bool:
    return _state_matches(
        filters,
        planning_state(claims),
        claims.cum_partner_assigned > claims.cum_partner_scheduled,
    )


def _partner_values(values, share) -> list:
    """A school's vector with the Partner claims one Partner holds."""
    partner_values = list(values)
    assigned, scheduled, verified, returned = share
    core = values[IDX["core_schools"]] == 1
    partner_values[IDX["partner_assigned"]] = assigned
    partner_values[IDX["partner_scheduled"]] = scheduled
    partner_values[IDX["partner_verified"]] = verified
    partner_values[IDX["returned"]] = returned
    partner_values[IDX["partner_core_assigned"]] = assigned if core else 0
    partner_values[IDX["partner_core_scheduled"]] = scheduled if core else 0
    partner_values[IDX["partner_client_assigned"]] = 0 if core else assigned
    partner_values[IDX["partner_client_scheduled"]] = 0 if core else scheduled
    return partner_values


NO_PARTNER_KEY = "__staff__"


def fold(source, filters: Filters, *, placement: bool = False, plan=None) -> Tree:
    """Fold the schools through the filters into the hierarchy.

    From the rollup whenever the filters are made of whole cells — every
    filter but a single Partner — and school by school otherwise, or when the
    caller needs to know where each kept school landed (``placement``).

    ``plan`` is the people-first read for the same filters (``people``): each
    person's own plan, added to their row. Without it the rows carry their
    schools' figures only, which is all a follow-up's gap needs.
    """
    if isinstance(source, Rollup):
        if filters.partner or (filters.channel or "") != source.channel:
            raise ValueError("This rollup cannot answer these filters.")
        return _fold_rollup(source, filters, plan)
    if placement or filters.partner:
        return _fold_schools(source, filters, placement=placement, plan=plan)
    return _fold_rollup(rollup_of(source, filters.channel), filters, plan)


def _fold_rollup(rollup: Rollup, filters: Filters, plan=None) -> Tree:
    owners = rollup.owners
    lead_of = {key: owner.lead_key for key, owner in owners.items()}
    owner_parts: dict[str, list] = {}
    type_parts: dict[tuple, list] = {}
    partner_parts: dict[tuple, list] = {}
    kept: dict[tuple, bool] = {}

    def keeps(owner_key, region_id, district_id, school_type, clustered) -> bool:
        place = (owner_key, region_id, district_id, school_type, clustered)
        answer = kept.get(place)
        if answer is None:
            answer = kept[place] = _keeps_place(
                filters,
                owner_key,
                lead_of.get(owner_key, NO_LEAD_KEY),
                region_id,
                district_id,
                school_type,
                clustered,
            )
        return answer

    for (
        owner_key,
        region_id,
        district_id,
        school_type,
        clustered,
        state,
        awaiting,
    ), vector in rollup.cells.items():
        if keeps(
            owner_key, region_id, district_id, school_type, clustered
        ) and _state_matches(filters, state, awaiting):
            owner_parts.setdefault(owner_key, []).append(vector)
            type_parts.setdefault((owner_key, school_type), []).append(vector)
    for (
        owner_key,
        region_id,
        district_id,
        school_type,
        clustered,
        state,
        awaiting,
        partner_key,
    ), vector in rollup.partner_cells.items():
        if keeps(
            owner_key, region_id, district_id, school_type, clustered
        ) and _state_matches(filters, state, awaiting):
            partner_parts.setdefault((owner_key, partner_key), []).append(vector)
    unmapped = sum(
        count
        for (
            owner_key,
            region_id,
            district_id,
            clustered,
        ), count in rollup.unmapped.items()
        if keeps(owner_key, region_id, district_id, "", clustered)
    )
    return _tree(
        rollup,
        filters,
        {key: sum_vectors(parts) for key, parts in owner_parts.items()},
        {key: sum_vectors(parts) for key, parts in partner_parts.items()},
        unmapped,
        {},
        {key: sum_vectors(parts) for key, parts in type_parts.items()},
        plan,
    )


def _fold_schools(
    dataset: Dataset, filters: Filters, *, placement: bool, plan=None
) -> Tree:
    window = dataset.window
    owners = dataset.owners
    channel = filters.channel or None
    only_partner = filters.partner or None

    owner_parts: dict[str, list] = {}
    type_parts: dict[tuple, list] = {}
    partner_parts: dict[tuple[str, str], list] = {}
    placed: dict[str, tuple[str, str]] = {}
    unmapped = 0
    for school in dataset.facts.values():
        owner = owners.get(school.owner_key)
        if not _keeps(school, owner, filters):
            continue
        if not school.is_governed:
            # Outside every denominator until its type is decided, and still
            # counted, so the page can say how many schools that is.
            unmapped += 1
            continue
        claims = claims_for(
            school,
            dataset.allocations[school.id],
            window,
            channel=channel,
            only_partner=only_partner,
        )
        if not _status_matches(claims, filters):
            continue
        values = school_values(school, claims)
        owner_parts.setdefault(school.owner_key, []).append(values)
        type_parts.setdefault((school.owner_key, school.school_type), []).append(values)
        if placement:
            placed[school.id] = (
                school.owner_key,
                owner.lead_key if owner is not None else NO_LEAD_KEY,
            )
        involved = [
            pid
            for pid in (school.partners or {})
            if not only_partner or pid == only_partner
        ]
        if involved and channel != "staff":
            shares = claims.by_partner or {}
            for pid in involved:
                share = shares.get(pid) or (0, 0, 0, school.partners[pid][P_RETURNED])
                partner_parts.setdefault((school.owner_key, pid), []).append(
                    _partner_values(values, share)
                )
        else:
            partner_parts.setdefault((school.owner_key, NO_PARTNER_KEY), []).append(
                values
            )
    return _tree(
        dataset,
        filters,
        {key: sum_vectors(parts) for key, parts in owner_parts.items()},
        {key: sum_vectors(parts) for key, parts in partner_parts.items()},
        unmapped,
        placed,
        {key: sum_vectors(parts) for key, parts in type_parts.items()},
        plan,
    )


def _plan_values(person) -> list:
    """A person's own plan (``people.PersonPlan``) as the row's people fields."""
    values = blank()
    values[IDX["p_visits"]] = person.visits_planned
    values[IDX["p_follow_up"]] = person.visits.get(rules.KIND_FOLLOW_UP, 0)
    values[IDX["p_in_school"]] = person.visits.get(rules.KIND_IN_SCHOOL, 0)
    values[IDX["p_ssa"]] = person.visits.get(rules.KIND_SSA, 0)
    values[IDX["p_outreach"]] = person.outreach
    values[IDX["p_trainings"]] = person.trainings
    values[IDX["p_cluster_trainings"]] = person.cluster_trainings
    values[IDX["p_meetings"]] = person.meetings
    values[IDX["pa_work"]] = person.partner_assigned
    values[IDX["pp_work"]] = person.partner_planned
    values[IDX["pa_schools"]] = person.partner_schools
    return values


def _tree(
    source,
    filters: Filters,
    owner_values: dict,
    partner_values: dict,
    unmapped: int,
    placement: dict,
    type_values: dict | None = None,
    plan=None,
) -> Tree:
    """The hierarchy over each person's figures, phased per person.

    A row is a person: the schools they hold (``owner_values``) and, when the
    people-first read is given, their own plan against the visits their role
    plans. Somebody who planned and holds no school is a row; so is every
    Lead and CCEO on the roster when nothing narrows the schools.
    """
    window = source.window
    owners = source.owners
    plans = {person.key: person for person in plan.people} if plan else {}
    roster = {
        person.key: person for members in source.rosters.values() for person in members
    }
    show_roster = not filters.active_school_filters or (
        filters.active_school_filters == 1 and filters.program_lead
    )

    keys = set(owner_values)
    keys.update(key for key, person in plans.items() if person.has_anything)
    if show_roster:
        keys.update(roster)

    rows: dict[str, OwnerRow] = {}
    for key in keys:
        owner = owners.get(key) or roster.get(key)
        person = plans.get(key)
        if owner is None and person is None:
            owner_name, kind, role, lead_key, ceiling = (
                NO_OWNER_LABEL,
                "unassigned",
                "",
                NO_LEAD_KEY,
                0,
            )
        elif owner is None:
            # Somebody the year's plans name who holds no school and is on no
            # roster: shown, with no target.
            owner_name, role, lead_key, ceiling = person.name, "", NO_LEAD_KEY, 0
            kind = "unassigned" if key.startswith("__") else "other"
        else:
            owner_name, kind, role = owner.name, owner.kind, owner.role
            lead_key, ceiling = owner.lead_key, owner.ceiling
        if filters.program_lead and lead_key != filters.program_lead:
            continue
        if filters.cceo and key != filters.cceo:
            continue
        values = list(owner_values.get(key) or blank())
        if person is not None:
            for index, amount in zip(I_PEOPLE, _people_part(person)):
                values[index] += amount
        if plan is not None:
            values[IDX["target"]] = ceiling
        row = OwnerRow(
            key=key,
            name=owner_name,
            kind=kind,
            role=role,
            lead_key=lead_key,
            tally=Tally(phase(values, window)),
            ceiling=ceiling,
        )
        if person is not None:
            for pid, (assigned, dated, school_ids) in person.by_partner.items():
                hands = blank()
                hands[IDX["pa_work"]] = assigned
                hands[IDX["pp_work"]] = dated
                hands[IDX["pa_schools"]] = len(school_ids)
                row.assigned[pid] = Tally(hands)
        rows[key] = row
    for (owner_key, pid), values in partner_values.items():
        row = rows.get(owner_key)
        if row is not None:
            row.partners[pid] = Tally(phase(values, window))

    # Every Programme Lead is a row whether or not the filters left them any
    # schools.
    leads: list[LeadRow] = []
    seen_leads: set[str] = set()
    for lead in source.leads:
        if filters.program_lead and lead.key != filters.program_lead:
            continue
        seen_leads.add(lead.key)
        members = [row for row in rows.values() if row.lead_key == lead.key]
        leads.append(_lead_row(lead.key, lead.name, members))
    # Leads the role list does not know (an owner reporting to someone whose
    # role has since changed) keep their rows rather than dropping schools.
    orphan_leads: dict[str, list[OwnerRow]] = {}
    for row in rows.values():
        if row.lead_key not in seen_leads:
            orphan_leads.setdefault(row.lead_key, []).append(row)
    for lead_key, members in orphan_leads.items():
        if lead_key == NO_LEAD_KEY:
            continue
        name = next(
            (owners[m.key].lead_name for m in members if m.key in owners),
            NO_LEAD_LABEL,
        )
        leads.append(_lead_row(lead_key, name, members))
    if NO_LEAD_KEY in orphan_leads:
        row = _lead_row(NO_LEAD_KEY, NO_LEAD_LABEL, orphan_leads[NO_LEAD_KEY])
        row.is_no_lead = True
        leads.append(row)

    country = sum_vectors([lead.tally.values for lead in leads])
    country[I_UNMAPPED] += unmapped

    # The same schools by their own type: each person's share phased as the
    # person's is, so a type's row is the sum of its people's.
    by_type: dict[str, list] = {}
    for (owner_key, school_type), values in (type_values or {}).items():
        if owner_key in rows:
            by_type.setdefault(school_type, []).append(phase(values, window))
    return Tree(
        country=Tally(country),
        leads=leads,
        window=window,
        placement=placement,
        by_type={
            school_type: Tally(sum_vectors(parts))
            for school_type, parts in by_type.items()
        },
    )


def _people_part(person) -> list:
    values = _plan_values(person)
    return [values[index] for index in I_PEOPLE]


def _lead_row(key: str, name: str, members: list) -> LeadRow:
    order = {"pl_personal": 0, "cceo": 1, "other": 2, "unassigned": 3}
    members.sort(key=lambda row: (order.get(row.kind, 2), row.name.casefold()))
    total = sum_vectors([member.tally.values for member in members])
    return LeadRow(key=key, name=name, tally=Tally(total), owners=members)


@dataclass
class Snapshot:
    """What the page renders: the tree, and when and how it was read."""

    tree: Tree
    filters: Filters
    built_at: datetime
    as_of: date
    universe: str
    region_names: dict = field(default_factory=dict)
    district_names: dict = field(default_factory=dict)
    partner_names: dict = field(default_factory=dict)
    lead_options: list = field(default_factory=list)
    owner_options: list = field(default_factory=list)
    scope_label: str = ""


def _narrow(filters: Filters, school_ids=None) -> people_read.Narrow:
    """The page's filters as the people-first read applies them."""
    return people_read.Narrow(
        region=filters.region,
        district=filters.district,
        school_type=filters.school_type,
        cluster_status=filters.cluster_status,
        channel=filters.channel,
        partner=filters.partner,
        school_ids=school_ids,
    )


def _people_window(window: Window) -> Window:
    """A week has no approved phasing, so a person's plan is read for the
    year so far, as the week's cards read the schools."""
    if window.period == "week":
        return replace(window, start=window.fy_start)
    return window


def _snapshot(source, filters: Filters, scope) -> Snapshot:
    """Fold ``source`` (a Rollup or a Dataset) into what the page renders:
    the schools' figures, and each person's own plan beside them."""
    school_ids = None
    if filters.planning_status or filters.partner:
        # Only the school-by-school fold knows which schools these keep.
        school_ids = tuple(fold(source, filters, placement=True).placement)
    plan = people_read.people_plan(
        None,
        filters.fy,
        window=_people_window(source.window),
        scope=scope,
        narrow=_narrow(filters, school_ids),
        portfolio=False,
    )
    return Snapshot(
        tree=fold(source, filters, plan=plan),
        filters=filters,
        built_at=source.built_at,
        as_of=source.as_of,
        universe=source.universe,
        region_names=source.region_names,
        district_names=source.district_names,
        partner_names={
            **source.partner_names,
            **_names(
                "partners.Partner",
                {
                    pid
                    for person in plan.people
                    for pid in person.by_partner
                    if pid and pid not in source.partner_names
                },
            ),
        },
        lead_options=[{"key": lead.key, "name": lead.name} for lead in source.leads],
        owner_options=sorted(
            (
                {
                    "key": owner.key,
                    "name": owner.name,
                    "lead": owner.lead_key,
                    "kind": owner.kind,
                }
                for owner in {
                    **{
                        person.key: person
                        for members in source.rosters.values()
                        for person in members
                    },
                    **source.owners,
                }.values()
                if owner.kind != "unassigned"
            ),
            key=lambda option: option["name"].casefold(),
        ),
        scope_label=source.scope_label,
    )


def snapshot_for(user, filters: Filters, *, refresh: bool = False) -> Snapshot:
    """The folded tree for these filters, cached with the dataset it came from."""
    from apps.core.cache_utils import forget_snapshot, stampede_safe_get_or_compute
    from apps.core.scoping import resolve_user_scope

    window = filters.window
    scope = resolve_user_scope(user)
    universe = universe_key(scope)
    key = f"{_key('tree', universe, window)}:{filters.key()}"
    if refresh:
        forget_snapshot(key)
    _note_window(universe, filters)

    def build():
        if filters.partner or filters.planning_status:
            # One Partner's claims, and which schools a planning status
            # keeps, are read school by school.
            source = dataset_for(user, window, refresh=refresh)
        else:
            source = rollup_for(user, window, filters.channel, refresh=refresh)
        return _snapshot(source, filters, scope)

    return stampede_safe_get_or_compute(key, build, timeout=_timeout())


# ── Keeping the country's figures warm ───────────────────────────────────────
#: How often the scheduler rebuilds the figures (apps.realtime.registry) and
#: how long what it publishes is kept: longer than the interval, so a reader
#: never finds the slot empty between two runs, and short enough that figures
#: outlive a stopped scheduler by minutes, not hours.
WARM_EVERY_MINUTES = 4
WARM_KEEP_SECONDS = 6 * 60
#: Besides the year, the most recently read windows the warmer keeps ready.
WARM_RECENT_WINDOWS = 3
WARM_RECENT_SECONDS = 60 * 60
_RECENT_KEY = "cpo:recent-windows:v1"


def _note_window(universe: str, filters: Filters) -> None:
    """Remember a country reader's window, so the warmer keeps it ready.

    Only the year is warmed unasked. Written at most every few minutes per
    window, and best-effort: two workers noting at once can lose one note,
    which costs one cold build, never a wrong figure.
    """
    if _timeout() <= 0 or not universe.startswith("country:"):
        return
    if filters.period == "fy":
        return
    from django.core.cache import cache

    entry = (
        universe,
        filters.fy,
        filters.period,
        filters.quarter,
        filters.month,
        filters.week,
    )
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
        logger.warning("Could not note the oversight window", exc_info=True)


def warm_targets(today: date | None = None) -> list[tuple[str, Filters]]:
    """(country, filters) the warmer rebuilds: each country a Country Director
    or Impact Assessment officer reads, for the operational year, plus the
    windows country readers opened in the last hour."""
    from django.core.cache import cache
    from django.db.models import Q

    from apps.accounts.models import StaffProfile
    from apps.core.fy import get_operational_fy
    from apps.core.rbac import EdifyRole

    roles = [EdifyRole.COUNTRY_DIRECTOR.value, EdifyRole.IMPACT_ASSESSMENT.value]
    countries = sorted(
        {
            (country or "").strip()
            for country in StaffProfile.objects.filter(
                Q(user__active_role__in=roles) | Q(user__roles__overlap=roles),
                deleted_at__isnull=True,
                user__is_active=True,
                user__deleted_at__isnull=True,
            ).values_list("country", flat=True)
        }
        - {""}
    )
    fy = get_operational_fy(today) if today else get_operational_fy()
    targets = [(country, Filters(fy=fy)) for country in countries]
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
    for _moment, (universe, fy_, period, quarter, month, week) in reversed(ranked):
        country = universe.split(":", 1)[1]
        if country not in countries:
            continue
        targets.append(
            (
                country,
                Filters(fy=fy_, period=period, quarter=quarter, month=month, week=week),
            )
        )
        if len(targets) >= len(countries) + WARM_RECENT_WINDOWS:
            break
    return targets


def warm(targets=None) -> int:
    """Rebuild and publish each target's dataset, rollup and unfiltered tree.

    Publishing replaces what readers are served in one step per key, so a
    reader never waits on a build the warmer could have done; a reader who
    arrives while nothing is published builds it, as before. Returns how many
    windows were published.
    """
    from apps.core.cache_utils import publish_snapshot

    if _timeout() <= 0:
        return 0
    keep = max(_timeout(), WARM_KEEP_SECONDS)
    done = 0
    failed: Exception | None = None
    seen: set = set()
    for country, filters in targets if targets is not None else warm_targets():
        window = filters.window
        scope = system_scope(country)
        universe = universe_key(scope)
        mark = (universe, window.cache_part)
        if mark in seen:
            continue
        seen.add(mark)
        try:
            dataset = build_dataset(scope, window, universe=universe)
            rollup = rollup_of(dataset, "")
            snapshot = _snapshot(rollup, filters, scope)
        except Exception as exc:  # noqa: BLE001 - one window must not stop the rest
            logger.exception("Could not warm %s %s", universe, window.cache_part)
            failed = failed or exc
            continue
        publish_snapshot(_key("facts", universe, window), dataset, timeout=keep)
        _write_stamp(
            _key("facts", universe, window), dataset.stamp, timeout=keep, replace=True
        )
        publish_snapshot(
            f"{_key('rollup', universe, window)}:all", rollup, timeout=keep
        )
        publish_snapshot(
            f"{_key('tree', universe, window)}:{filters.key()}", snapshot, timeout=keep
        )
        done += 1
    if failed is not None:
        raise failed
    return done


def system_scope(country: str):
    """The whole of one country, as the system reads it (no reader's scope)."""
    from apps.core.scoping import UserScope

    return UserScope(
        user_id="system",
        active_role="CountryDirector",
        country_scope=True,
        country=country or "",
    )


# ── View models ──────────────────────────────────────────────────────────────
KPI_KEYS = (
    "cpo_staff_visit_planning",
    "cpo_partner_planning",
    "cpo_total_visit_coverage",
    "cpo_training_planning",
    "cpo_cluster_membership",
    "cpo_cluster_meeting_planning",
)


def _fmt(value) -> str:
    return f"{int(value):,}"


def headcount(snapshot: Snapshot) -> tuple[int, int]:
    """(Programme Leads, CCEOs) whose rows the snapshot holds."""
    leads = cceos = 0
    for lead in snapshot.tree.leads:
        for owner in lead.owners:
            if not owner.ceiling:
                continue
            if owner.kind == "pl_personal":
                leads += 1
            elif owner.kind == "cceo":
                cceos += 1
    return leads, cceos


def kpis(snapshot: Snapshot) -> list[dict]:
    """The six planning cards, each bound to its registered metric, by the
    planning rulebook (owner, 2026-10-01)."""
    from apps.core.metrics import MetricValue, render_metric

    t = snapshot.tree.country
    window = snapshot.tree.window
    phased = window.has_phased_target
    week = window.period == "week"
    leads, cceos = headcount(snapshot)

    def card(
        key, part, whole, *, headline, note, extras, tone_part=None, icon="", more=()
    ):
        rendered = render_metric(
            key,
            MetricValue.ratio(part, whole),
            drilldown_url=f"{PAGE_PATH}drawer?kind=kpi&metric={key}&{snapshot.filters.query()}",
        ).as_dict()
        share = Tally.share(part, whole)
        rendered.update(
            {
                "part": _fmt(part),
                "whole": _fmt(whole),
                "share": share,
                "meter": min(100, share or 0),
                "headline": headline,
                "note": note,
                "extras": [e for e in extras if e],
                # Said in the opened card, where there is room for it.
                "more": [m for m in more if m],
                "tone": _tone(share if tone_part is None else tone_part),
                "icon": icon,
            }
        )
        return rendered

    period_note = ""
    if phased:
        period_note = f"Phased target for {window.label}"
    elif week:
        period_note = "Year to date against the annual requirement"

    visit_part, training_part = t.planned, t.training
    meeting_part = t.meeting_covered
    if week:
        # A week has no approved phasing: the card reads the year so far.
        visit_part = t.cum_staff + t.cum_partner_scheduled
        training_part, meeting_part = t.cum_training, t.cum_meeting_covered

    lead_target = policy.ceiling_for(policy.PROGRAM_LEAD_ROLE)
    cceo_target = policy.ceiling_for(policy.CCEO_ROLE)
    cards = [
        card(
            "cpo_staff_visit_planning",
            t.p_visits,
            t.target,
            headline=(
                _fmt(t.plan_remaining),
                "visits still to plan",
            ),
            note=period_note,
            extras=[
                f"{_fmt(cceos)} CCEOs × {cceo_target} + "
                f"{_fmt(leads)} Leads × {lead_target}",
            ],
            more=[
                f"Follow up {_fmt(t.p_follow_up)} · In-school Training "
                f"{_fmt(t.p_in_school)} · SSA Support {_fmt(t.p_ssa)}",
                f"{_fmt(t.p_outreach)} donor, story and social visits not counted"
                if t.p_outreach
                else "",
            ],
            icon="staff",
        ),
        card(
            "cpo_partner_planning",
            t.pp_work,
            t.pa_work,
            headline=(_fmt(t.pa_schools), "Schools assigned to Partners"),
            note="" if phased else period_note,
            extras=[
                f"{_fmt(t.pa_work)} assigned by staff",
                f"{_fmt(t.partner_waiting)} awaiting the Partner's date",
            ],
            icon="partner",
        ),
        card(
            "cpo_total_visit_coverage",
            visit_part,
            t.visit_slots,
            headline=(_fmt(t.any_visit), "Schools with a visit planned"),
            note=period_note,
            extras=[
                f"{_fmt(t.no_visit)} schools not yet planned",
                f"{_fmt(t.duplicates)} planned twice" if t.duplicates else "",
            ],
            icon="target",
        ),
        card(
            "cpo_training_planning",
            training_part,
            t.training_slots,
            headline=(_fmt(t.any_training), "Schools with training planned"),
            note=period_note,
            extras=[
                f"{_fmt(t.no_training)} schools not yet planned",
                f"{_fmt(t.training_gap)} slots remaining",
            ],
            icon="training",
        ),
        card(
            "cpo_cluster_membership",
            t.clustered,
            t.schools,
            headline=(_fmt(t.unclustered), "Unclustered schools"),
            note="",
            extras=[],
            icon="cluster",
        ),
        card(
            "cpo_cluster_meeting_planning",
            meeting_part,
            t.schools,
            headline=(_fmt(t.p_meetings), "Cluster meetings planned by staff"),
            note=period_note,
            extras=[
                f"{_fmt(t.meeting_covered_clustered)} of {_fmt(t.clustered)} "
                "clustered schools on a planned meeting",
            ],
            icon="meeting",
        ),
    ]
    return cards


def type_rows(snapshot: Snapshot) -> list[dict]:
    """The same schools by their own type (owner, 2026-10-01: "separate all
    the plans for Core, Clients, Core Trained, Core Graduates ... how many
    schools have been planned for and how many are not yet. Do the same for
    trainings"). One row per type the selection holds, the rulebook's order;
    a type the requirement asks nothing of shows what it has and no gap."""
    by_type = snapshot.tree.by_type
    order = [
        t for t in rules.TYPE_ORDER if t in by_type or not snapshot.filters.school_type
    ]
    order += sorted(t for t in by_type if t not in rules.TYPE_ORDER)
    rows = []
    for school_type in order:
        tally = by_type.get(school_type) or Tally()
        need = rules.requirement_for(school_type)
        rows.append(
            {
                "key": school_type,
                "label": rules.type_label(school_type),
                "needs_visits": bool(need.visits),
                "needs_trainings": bool(need.trainings),
                "schools": _fmt(tally.schools),
                "visit_slots": _fmt(tally.visit_slots),
                "staff": _fmt(tally.staff),
                "partner_scheduled": _fmt(tally.partner_scheduled),
                "visit_share": tally.unique_visit_share,
                "visit_tone": _tone(tally.unique_visit_share),
                "any_visit": _fmt(tally.any_visit),
                "no_visit": _fmt(tally.no_visit),
                "with_partner": _fmt(tally.with_partner),
                "training_slots": _fmt(tally.training_slots),
                "training": _fmt(tally.training),
                "training_share": tally.training_share,
                "training_tone": _tone(tally.training_share),
                "trained_share": Tally.share(
                    tally.any_training, tally.training_schools
                ),
                "any_training": _fmt(tally.any_training),
                "no_training": _fmt(tally.no_training),
                "duplicates": tally.duplicates,
            }
        )
    return rows


def _tone(share) -> str:
    """How a share reads on the card: the design's green, amber and red."""
    if share is None:
        return "none"
    if share >= 70:
        return "good"
    if share >= 40:
        return "fair"
    return "low"


#: Chart series colours, as tokens the page stylesheet defines for both
#: themes. Colour follows the measure on every chart.
CHART_COLOURS = {
    "staff_core": "var(--cpo-series-1)",
    "staff_client": "var(--cpo-series-2)",
    "partner_scheduled": "var(--cpo-series-4)",
    "partner_waiting": "var(--cpo-series-3)",
    "gap": "var(--cpo-series-gap)",
    "staff_only": "var(--cpo-series-1)",
    "partner_only": "var(--cpo-series-3)",
    "both": "var(--cpo-series-4)",
    "none": "var(--cpo-series-5)",
    "required": "var(--cpo-series-1)",
    "planned": "var(--cpo-series-3)",
    "total": "var(--cpo-series-1)",
    "clustered": "var(--cpo-series-3)",
    "meetings": "var(--cpo-series-4)",
}


def charts(snapshot: Snapshot) -> list[dict]:
    """The four planning charts, one category per Programme Lead row.

    Each chart's categories are the table's Lead rows and its values are
    those rows' own figures, so a chart total is the table total. A Lead's
    bar is the Lead's own plan and their CCEOs' together. The visit chart
    stacks a PARTITION of each team's target — the three counted kinds and
    what is still to plan — so a bar's length is the team's target (or its
    plan, where that is larger).
    """
    leads = [
        lead
        for lead in snapshot.tree.leads
        if lead.tally.schools or lead.tally.p_visits or not lead.is_no_lead
    ]
    names = [lead.name for lead in leads]
    keys = [lead.key for lead in leads]
    t = [lead.tally for lead in leads]

    def pct(part, whole):
        return [Tally.share(p, w) or 0 for p, w in zip(part, whole)]

    visit = {
        "id": "cpo-visit-chart",
        "title": "Visits Planned Against Target by Program Lead",
        "form": "stacked",
        "categories": names,
        "keys": keys,
        "series": [
            {
                "name": "Follow up",
                "color": CHART_COLOURS["staff_core"],
                "data": [x.p_follow_up for x in t],
            },
            {
                "name": "In-school Training",
                "color": CHART_COLOURS["staff_client"],
                "data": [x.p_in_school for x in t],
            },
            {
                "name": "SSA Support",
                "color": CHART_COLOURS["partner_scheduled"],
                "data": [x.p_ssa for x in t],
            },
            {
                "name": "Still to plan",
                "color": CHART_COLOURS["gap"],
                "data": [x.plan_remaining for x in t],
            },
        ],
        "table": {
            "columns": [
                "Visit target",
                "Visits planned",
                "Follow up",
                "In-school Training",
                "SSA Support",
                "Still to plan",
                "Assigned to Partners",
                "Partner planned",
                "Donor, story and social (not counted)",
            ],
            "rows": [
                [
                    x.target,
                    x.p_visits,
                    x.p_follow_up,
                    x.p_in_school,
                    x.p_ssa,
                    x.plan_remaining,
                    x.pa_work,
                    x.pp_work,
                    x.p_outreach,
                ]
                for x in t
            ],
        },
    }
    unique = {
        "id": "cpo-unique-chart",
        "title": "Schools With a Visit Planned by Program Lead",
        "form": "share",
        "categories": names,
        "keys": keys,
        "series": [
            {
                "name": "Staff Plan Only",
                "color": CHART_COLOURS["staff_only"],
                "data": pct([x.staff_only for x in t], [x.visit_schools for x in t]),
                "counts": [x.staff_only for x in t],
            },
            {
                "name": "Partner Plan Only",
                "color": CHART_COLOURS["partner_only"],
                "data": pct([x.partner_only for x in t], [x.visit_schools for x in t]),
                "counts": [x.partner_only for x in t],
            },
            {
                "name": "Both",
                "color": CHART_COLOURS["both"],
                "data": pct([x.both for x in t], [x.visit_schools for x in t]),
                "counts": [x.both for x in t],
            },
            {
                "name": "Not Yet Planned",
                "color": CHART_COLOURS["none"],
                "data": pct([x.no_visit for x in t], [x.visit_schools for x in t]),
                "counts": [x.no_visit for x in t],
            },
        ],
        "table": {
            "columns": [
                "Schools needing a visit",
                "Staff plan only",
                "Partner plan only",
                "Both",
                "Not yet planned",
                "In a Partner's hands",
                "Planned twice",
            ],
            "rows": [
                [
                    x.visit_schools,
                    x.staff_only,
                    x.partner_only,
                    x.both,
                    x.no_visit,
                    x.with_partner,
                    x.duplicates,
                ]
                for x in t
            ],
        },
    }
    _even_shares(unique)
    training = {
        "id": "cpo-training-chart",
        "title": "Training Planning by Program Lead",
        "form": "columns",
        "categories": names,
        "keys": keys,
        "series": [
            {
                "name": "Required Training Slots",
                "color": CHART_COLOURS["required"],
                "data": [x.training_slots for x in t],
            },
            {
                "name": "Planned Training Slots",
                "color": CHART_COLOURS["planned"],
                "data": [x.training for x in t],
            },
        ],
        "table": {
            "columns": [
                "Required slots",
                "Planned slots",
                "Remaining slots",
                "Schools with training",
                "Schools with none",
            ],
            "rows": [
                [
                    x.training_slots,
                    x.training,
                    x.training_gap,
                    x.any_training,
                    x.no_training,
                ]
                for x in t
            ],
        },
    }
    clusters = {
        "id": "cpo-cluster-chart",
        "title": "Cluster & Cluster-Meeting Coverage",
        "form": "columns",
        "categories": names,
        "keys": keys,
        "series": [
            {
                "name": "Total Schools",
                "color": CHART_COLOURS["total"],
                "data": [x.schools for x in t],
            },
            {
                "name": "Clustered",
                "color": CHART_COLOURS["clustered"],
                "data": [x.clustered for x in t],
            },
            {
                "name": "Meeting Coverage",
                "color": CHART_COLOURS["meetings"],
                "data": [x.meeting_covered for x in t],
            },
        ],
        "table": {
            "columns": [
                "Eligible schools",
                "Clustered",
                "Unclustered",
                "Covered by a planned meeting",
                "Clustered, no meeting planned",
                "Meetings planned by staff",
            ],
            "rows": [
                [
                    x.schools,
                    x.clustered,
                    x.unclustered,
                    x.meeting_covered,
                    x.clustered_no_meeting,
                    x.p_meetings,
                ]
                for x in t
            ],
        },
    }
    for chart in (visit, unique, training, clusters):
        chart["data_id"] = f"{chart['id']}-data"
        # Whether there is anything to draw, decided here so the browser
        # never sums a figure.
        chart["empty"] = not any(value for s in chart["series"] for value in s["data"])
        chart["table"]["rows"] = [
            {"label": name, "cells": row}
            for name, row in zip(names, chart["table"]["rows"])
        ]
    return [visit, unique, training, clusters]


def _even_shares(chart: dict) -> None:
    """Make each Lead's shares sum to exactly 100 (largest remainder)."""
    series = chart["series"]
    for index in range(len(chart["categories"])):
        counts = [s["counts"][index] for s in series]
        whole = sum(counts)
        if not whole:
            for s in series:
                s["data"][index] = 0
            continue
        raw = [100 * c / whole for c in counts]
        base = [int(r) for r in raw]
        left = 100 - sum(base)
        for position in sorted(
            range(len(raw)), key=lambda i: raw[i] - base[i], reverse=True
        )[:left]:
            base[position] += 1
        for s, value in zip(series, base):
            s["data"][index] = value


TABLE_COLUMNS = (
    ("name", "Name"),
    ("p_visits", "Visits Planned"),
    ("schools", "Portfolio"),
    ("core_schools", "Core"),
    ("client_schools", "Client"),
    ("core_trained_schools", "Core Trained"),
    ("core_graduate_schools", "Core Graduate"),
    ("any_visit", "Schools Planned"),
    ("pp_work", "Partner Planned"),
    ("training", "Training Coverage"),
    ("unclustered", "Unclustered"),
    ("meeting", "Cluster Meeting Coverage"),
    ("followups", "Open Follow-ups"),
    ("action", "Action"),
)
TABLE_WIDTH = len(TABLE_COLUMNS)


def row_cells(tally: Tally) -> dict:
    """The table's figures for one row, formatted on the server.

    The first two are the person's own plan against the visits their role
    plans; the Partner pair is the work they handed over and what the
    Partner has dated; the rest are the schools they hold.
    """
    return {
        "target": _fmt(tally.target),
        "has_target": bool(tally.target),
        "p_visits": _fmt(tally.p_visits),
        "plan_share": tally.plan_share,
        "plan_tone": _tone(tally.plan_share),
        "schools": _fmt(tally.schools),
        **{field: _fmt(getattr(tally, field)) for field in TYPE_FIELDS.values()},
        "visit_slots": _fmt(tally.visit_slots),
        "staff": _fmt(tally.staff),
        "any_visit": f"{_fmt(tally.any_visit)} / {_fmt(tally.visit_schools)}",
        "visit_share": tally.unique_visit_share,
        "visit_tone": _tone(tally.unique_visit_share),
        "no_visit": _fmt(tally.no_visit),
        "pa_work": _fmt(tally.pa_work),
        "pp_work": _fmt(tally.pp_work),
        "pa_schools": _fmt(tally.pa_schools),
        "partner_assigned": _fmt(tally.partner_assigned),
        "partner_scheduled": _fmt(tally.partner_scheduled),
        "unallocated": _fmt(tally.unallocated),
        "training": f"{_fmt(tally.training)} / {_fmt(tally.training_slots)}",
        "training_share": tally.training_share,
        "training_tone": _tone(tally.training_share),
        "unclustered": _fmt(tally.unclustered),
        "meeting": f"{_fmt(tally.meeting_covered)} / {_fmt(tally.schools)}",
        "meeting_share": tally.meeting_share,
        "meeting_tone": _tone(tally.meeting_share),
        "deficit": tally.deficit,
        "shortfall": tally.shortfall,
        "duplicates": tally.duplicates,
    }


def lead_rows(snapshot: Snapshot, followup_counts: dict) -> list[dict]:
    rows = []
    for lead in snapshot.tree.leads:
        rows.append(
            {
                "key": lead.key,
                "name": lead.name,
                "is_no_lead": lead.is_no_lead,
                "cells": row_cells(lead.tally),
                "followups": followup_counts.get(("lead", lead.key), 0),
                "has_children": bool(lead.owners),
            }
        )
    return rows


def owner_rows(snapshot: Snapshot, lead_key: str, followup_counts: dict) -> list[dict]:
    lead = next((row for row in snapshot.tree.leads if row.key == lead_key), None)
    if lead is None:
        return []
    rows = []
    for owner in lead.owners:
        rows.append(
            {
                "key": owner.key,
                "name": owner.label,
                "person": owner.name,
                "kind": owner.kind,
                "cells": row_cells(owner.tally),
                "followups": followup_counts.get(("owner", owner.key), 0),
                "has_children": bool(owner.assigned),
                "ceiling": owner.ceiling,
            }
        )
    return rows


def partner_rows(snapshot: Snapshot, owner_key: str) -> list[dict]:
    """The Partners one person handed work to: what they assigned to each,
    and how much of it the Partner has dated."""
    _lead, owner = find_owner(snapshot, owner_key)
    if owner is None:
        return []
    rows = []
    for pid, tally in sorted(
        owner.assigned.items(),
        key=lambda item: snapshot.partner_names.get(item[0], item[0]).casefold(),
    ):
        rows.append(
            {
                "key": pid,
                "name": snapshot.partner_names.get(pid) or "Unrecorded Partner",
                "schools": _fmt(tally.pa_schools),
                "assigned": _fmt(tally.pa_work),
                "planned": _fmt(tally.pp_work),
                "waiting": tally.partner_waiting,
                "has_school_side": pid in owner.partners,
            }
        )
    return rows


def find_owner(
    snapshot: Snapshot, owner_key: str
) -> tuple[LeadRow | None, OwnerRow | None]:
    for lead in snapshot.tree.leads:
        for owner in lead.owners:
            if owner.key == owner_key:
                return lead, owner
    return None, None


def find_lead(snapshot: Snapshot, lead_key: str) -> LeadRow | None:
    return next((lead for lead in snapshot.tree.leads if lead.key == lead_key), None)


#: School-level figures a drill-down can be narrowed to — every KPI's gap.
GAP_FIGURES = {
    "staff_gap": "Staff visit slots with no plan",
    "partner_gap": "Partner slots nobody holds",
    "awaiting_partner": "Assigned, awaiting the Partner's schedule",
    "unallocated": "Visit slots unallocated",
    "no_visit": "No visit plan",
    "training_gap": "Training slots not planned",
    "no_training": "No training planned",
    "unclustered": "Not in an active cluster",
    "clustered_no_meeting": "Clustered, on no planned meeting",
    "deficit": "Core staff slots beyond capacity",
    "with_partner": "In a Partner's hands",
    "duplicates": "Planned twice",
}

#: Which gap each KPI card opens on.
KPI_GAPS = {
    "cpo_staff_visit_planning": "staff_gap",
    "cpo_partner_planning": "with_partner",
    "cpo_total_visit_coverage": "no_visit",
    "cpo_training_planning": "training_gap",
    "cpo_cluster_membership": "unclustered",
    "cpo_cluster_meeting_planning": "clustered_no_meeting",
}

SCHOOLS_PER_PAGE = 25


def school_rows(
    dataset: Dataset,
    filters: Filters,
    *,
    lead_key: str = "",
    owner_key: str = "",
    partner_id: str = "",
    gap: str = "",
    page: int = 1,
) -> dict:
    """The schools behind a figure, worst first, one page at a time.

    The same filters, claims and vectors as the row the reader opened — a
    school list cannot hold a school the row did not count.
    """
    window = dataset.window
    owners = dataset.owners
    channel = filters.channel or None
    only_partner = partner_id or filters.partner or None
    if only_partner == NO_PARTNER_KEY:
        only_partner = None
    # With no channel or Partner filter a school's figures are the ones kept
    # on its record; only the page of schools shown is read claim by claim.
    kept_figures = channel is None and only_partner is None
    gap_index = IDX.get(gap)

    by_owner = dataset.by_owner
    if owner_key:
        groups = [by_owner.get(owner_key, ())]
    elif lead_key:
        groups = [
            schools
            for key, schools in by_owner.items()
            if (owners[key].lead_key if key in owners else NO_LEAD_KEY) == lead_key
        ]
    else:
        groups = list(by_owner.values())

    def partner_row_keeps(school) -> bool:
        if partner_id == NO_PARTNER_KEY:
            return not school.partners
        return not partner_id or partner_id in (school.partners or {})

    picked = []
    if kept_figures:
        # The common case, kept tight: a country-wide list walks every school.
        index = gap_index if gap_index is not None else I_UNALLOCATED
        narrowed = any(
            getattr(filters, name)
            for name in (
                "region",
                "district",
                "school_type",
                "cluster_status",
                "cceo",
                "program_lead",
                "partner",
            )
        )
        status = filters.planning_status
        for schools in groups:
            for school in schools:
                values = school.vector
                if not values:  # no governed family, so no figures
                    continue
                if narrowed and not _keeps(
                    school, owners.get(school.owner_key), filters
                ):
                    continue
                if partner_id and not partner_row_keeps(school):
                    continue
                if status and not _state_matches(
                    filters, state_of(values), values[I_AWAITING]
                ):
                    continue
                amount = values[index]
                if gap_index is not None and amount <= 0:
                    continue
                picked.append((amount, school, None, values))
    else:
        for schools in groups:
            for school in schools:
                if not school.is_governed:
                    continue
                if not _keeps(school, owners.get(school.owner_key), filters):
                    continue
                if not partner_row_keeps(school):
                    continue
                claims = claims_for(
                    school,
                    dataset.allocations[school.id],
                    window,
                    channel=channel,
                    only_partner=only_partner,
                )
                if not _status_matches(claims, filters):
                    continue
                values = school_values(school, claims)
                amount = (
                    values[gap_index]
                    if gap_index is not None
                    else values[I_UNALLOCATED]
                )
                if gap_index is not None and amount <= 0:
                    continue
                picked.append((amount, school, claims, values))
    picked.sort(key=lambda item: (-item[0], item[1].name.casefold(), item[1].id))
    total = len(picked)
    pages = max(1, (total + SCHOOLS_PER_PAGE - 1) // SCHOOLS_PER_PAGE)
    page = min(max(1, page), pages)
    window_rows = [
        (
            amount,
            school,
            claims
            if claims is not None
            else claims_for(school, dataset.allocations[school.id], window),
            values,
        )
        for amount, school, claims, values in picked[
            (page - 1) * SCHOOLS_PER_PAGE : page * SCHOOLS_PER_PAGE
        ]
    ]
    cluster_names = _names(
        "clusters.Cluster", {school.raw_cluster_id for _, school, _, _ in window_rows}
    )
    from apps.planning.followup_models import (
        OPEN_FOLLOW_UP_STATES,
        PlanningOversightFollowUp,
    )

    followed = set(
        PlanningOversightFollowUp.objects.filter(
            fy=window.fy,
            status__in=OPEN_FOLLOW_UP_STATES,
            school_id__in=[school.id for _, school, _, _ in window_rows],
        ).values_list("school_id", flat=True)
    )
    rows = []
    for amount, school, claims, values in window_rows:
        owner = owners.get(school.owner_key)
        rows.append(
            {
                "id": school.id,
                "code": school.code,
                "name": school.name,
                "type": rules.type_label(school.school_type),
                "twice": [
                    rules.DUPLICATE_LABELS[reason]
                    for reason in duplicate_reasons(school)
                ],
                "with_partner": school.with_partner,
                "owner": owner.name if owner else NO_OWNER_LABEL,
                "owner_key": school.owner_key,
                "lead": owner.lead_name if owner else NO_LEAD_LABEL,
                "lead_key": owner.lead_key if owner else NO_LEAD_KEY,
                "cluster": cluster_names.get(school.raw_cluster_id, "")
                if school.clustered
                else "",
                "clustered": school.clustered,
                "staff_slots": claims.staff_expected,
                "staff_planned": claims.cum_staff
                if not window.has_phased_target
                else claims.staff,
                "partner_slots": claims.partner_expected,
                "partner_assigned": claims.cum_partner_assigned,
                "partner_scheduled": claims.cum_partner_scheduled,
                "training_slots": claims.training_slots,
                "training_planned": claims.cum_training,
                "meeting_planned": claims.cum_meeting_covered,
                "remaining": values[I_UNALLOCATED],
                "deficit": claims.deficit,
                "gap_amount": amount,
                "followed_up": school.id in followed,
                "state": planning_state(claims),
            }
        )
    return {
        "rows": rows,
        "total": total,
        "page": page,
        "pages": pages,
        "gap": gap,
        "gap_label": GAP_FIGURES.get(gap, ""),
    }


def header(snapshot: Snapshot) -> dict:
    window = snapshot.tree.window
    return {
        "fy_label": fy_label(window.fy),
        "view_label": window.view_label,
        "window_label": window.label,
        "as_of": snapshot.as_of,
        "built_at": timezone.localtime(snapshot.built_at)
        if timezone.is_aware(snapshot.built_at)
        else snapshot.built_at,
        "country": snapshot.scope_label or deployment_country(),
    }


def deployment_country() -> str:
    """The country a reader with no country of their own is reading: the one
    the deployment's staff work in, or "Country" when that is not one."""
    from django.db.models import Count

    from apps.accounts.models import StaffProfile

    row = (
        StaffProfile.objects.exclude(country__isnull=True)
        .exclude(country="")
        .values("country")
        .annotate(n=Count("id"))
        .order_by("-n")
        .first()
    )
    return (row or {}).get("country") or "Country"


class CountryPlanningOversightService:
    """The page's one service, as an importable surface."""

    read_filters = staticmethod(read_filters)
    dataset_for = staticmethod(dataset_for)
    snapshot_for = staticmethod(snapshot_for)
    build_dataset = staticmethod(build_dataset)
    fold = staticmethod(fold)
    kpis = staticmethod(kpis)
    type_rows = staticmethod(type_rows)
    charts = staticmethod(charts)
    lead_rows = staticmethod(lead_rows)
    owner_rows = staticmethod(owner_rows)
    partner_rows = staticmethod(partner_rows)
    rollup_for = staticmethod(rollup_for)
    school_rows = staticmethod(school_rows)
    warm = staticmethod(warm)
