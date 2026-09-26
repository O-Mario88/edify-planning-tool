"""
Pure cost calculator for a staff member's day of school visits (school visit
costing spec, 2026-09-26).

Two rules and one formula:

* **Cost parity.** A client school visit costs exactly what a core school
  visit costs. The day's visits are counted together and the day's money is
  shared equally across all of them, whichever kind each one is.
* **District resolution.** Whether the day is a primary-district day
  (transport and lunch) or a secondary-district day (transport, breakfast,
  lunch, dinner and a night's accommodation) depends on who travels: field
  staff (a CCEO or a Program Lead) have one primary district of their own;
  everyone else works from the Kampala, Wakiso and Mukono zone. The rule
  itself lives in apps.daily_visit_batches.districts and is shared with the
  engine.
* ``cost_per_school_visit = total_daily_cost / total_visits``, with every
  daily rate allocated the same way.

Like apps.budget.session_costing this module is arithmetic only: no models
and no rate-card lookups. Money is :class:`decimal.Decimal`; shares are exact
quotients, and the Daily Visit Batch (apps.daily_visit_batches.pricing) is
what splits a day into whole shillings. Inputs may be the dataclasses below
or plain mappings with the spec's camelCase keys (``primaryDistrict``,
``coreVisitsCount``) or their snake_case equivalents.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from decimal import Decimal
from typing import Any

from apps.budget.session_costing import (
    CostingValidationError,
    Number,
    _CostResult,
    _count,
    _money,
)
from apps.daily_visit_batches.districts import (
    HQ_PRIMARY_DISTRICTS,
    PRIMARY,
    is_field_role,
    resolve_district_type,
)

__all__ = [
    "HQ_PRIMARY_DISTRICTS",
    "StaffUser",
    "PrimaryDistrictRates",
    "SecondaryDistrictRates",
    "PrimaryVisitDay",
    "SecondaryVisitDay",
    "PrimaryVisitShare",
    "SecondaryVisitShare",
    "VisitDayTotals",
    "SchoolVisitDayCost",
    "resolve_visit_district_type",
    "cost_school_visit_day",
]


# ── Inputs ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StaffUser:
    id: str
    name: str
    role: str
    primary_district: str | None = None


@dataclass(frozen=True)
class PrimaryDistrictRates:
    transport: Number
    lunch: Number


@dataclass(frozen=True)
class SecondaryDistrictRates:
    transport: Number
    breakfast: Number
    lunch: Number
    dinner: Number
    accommodation: Number


def _snake(key: str) -> str:
    out = []
    for ch in key:
        if ch.isupper():
            out.append("_")
            out.append(ch.lower())
        else:
            out.append(ch)
    return "".join(out)


def _as_mapping(value: Any, name: str) -> dict[str, Any]:
    """A dataclass or a mapping as a snake_case dict, so the spec's camelCase
    payloads and this module's dataclasses read the same."""
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: getattr(value, f.name) for f in fields(value)}
    if isinstance(value, Mapping):
        return {_snake(str(key)): item for key, item in value.items()}
    raise CostingValidationError(f"{name} must be a mapping or a dataclass")


# ── Outputs ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PrimaryVisitDay:
    transport: Decimal
    lunch: Decimal
    total_daily_cost: Decimal


@dataclass(frozen=True)
class SecondaryVisitDay:
    transport: Decimal
    breakfast: Decimal
    lunch: Decimal
    dinner: Decimal
    daily_per_diem: Decimal
    accommodation: Decimal
    total_daily_cost: Decimal


@dataclass(frozen=True)
class PrimaryVisitShare:
    allocated_transport: Decimal
    allocated_lunch: Decimal
    cost_per_school_visit: Decimal


@dataclass(frozen=True)
class SecondaryVisitShare:
    allocated_transport: Decimal
    allocated_breakfast: Decimal
    allocated_lunch: Decimal
    allocated_dinner: Decimal
    allocated_accommodation: Decimal
    cost_per_school_visit: Decimal


@dataclass(frozen=True)
class VisitDayTotals:
    cost_per_school_visit: Decimal
    cost_per_core_visit: Decimal
    cost_per_client_visit: Decimal
    core_visits_total: Decimal
    client_visits_total: Decimal
    total_day_cost: Decimal


@dataclass(frozen=True)
class SchoolVisitDayCost(_CostResult):
    user_id: str
    role: str
    is_field_staff: bool
    target_district: str
    district_type: str
    core_visits_count: int
    client_visits_count: int
    total_visits: int
    daily_operational: PrimaryVisitDay | SecondaryVisitDay
    allocated_per_visit: PrimaryVisitShare | SecondaryVisitShare
    totals: VisitDayTotals


# ── The calculation ──────────────────────────────────────────────────────────


def resolve_visit_district_type(user: StaffUser | Mapping, target_district) -> str:
    """``"primary"`` or ``"secondary"`` for ``user`` visiting
    ``target_district``, by the role rule in apps.daily_visit_batches.districts.
    A field user with no primary district is refused, never guessed."""
    person = _as_mapping(user, "user")
    try:
        return resolve_district_type(
            person.get("role"), person.get("primary_district"), target_district
        )
    except ValueError as exc:
        raise CostingValidationError(str(exc)) from None


def cost_school_visit_day(
    user: StaffUser | Mapping,
    target_district,
    core_visits_count: Number,
    client_visits_count: Number,
    *,
    primary_rates: PrimaryDistrictRates | Mapping | None = None,
    secondary_rates: SecondaryDistrictRates | Mapping | None = None,
) -> SchoolVisitDayCost:
    """Cost one day of school visits for ``user`` in ``target_district``.

    ::

        total_visits          = core_visits_count + client_visits_count
        primary day:   total_daily_cost = transport + lunch
        secondary day: total_daily_cost = transport + (breakfast + lunch + dinner)
                                          + accommodation
        cost_per_school_visit = total_daily_cost / total_visits
        allocated_<rate>      = <rate> / total_visits

    Only the rates for the district type the visit resolves to are needed;
    the other set may be left out. At least one visit is required, as the
    divisor.
    """
    person = _as_mapping(user, "user")
    role = str(person.get("role") or "")
    district_type = resolve_visit_district_type(person, target_district)
    core = _count(core_visits_count, "core_visits_count")
    client = _count(client_visits_count, "client_visits_count")
    total_visits = core + client
    if total_visits < 1:
        raise CostingValidationError(
            "at least one school visit is required: the day's cost is shared "
            "across the visits planned for it"
        )

    if district_type == PRIMARY:
        if primary_rates is None:
            raise CostingValidationError(
                f"primary_rates are required: {target_district} is a primary "
                f"district for this {role or 'user'}"
            )
        rates = _as_mapping(primary_rates, "primary_rates")
        transport = _money(rates.get("transport"), "primary_rates.transport")
        lunch = _money(rates.get("lunch"), "primary_rates.lunch")
        total_daily = transport + lunch
        day: PrimaryVisitDay | SecondaryVisitDay = PrimaryVisitDay(
            transport=transport, lunch=lunch, total_daily_cost=total_daily
        )
        per_visit = total_daily / total_visits
        share: PrimaryVisitShare | SecondaryVisitShare = PrimaryVisitShare(
            allocated_transport=transport / total_visits,
            allocated_lunch=lunch / total_visits,
            cost_per_school_visit=per_visit,
        )
    else:
        if secondary_rates is None:
            raise CostingValidationError(
                f"secondary_rates are required: {target_district} is a "
                f"secondary district for this {role or 'user'}"
            )
        rates = _as_mapping(secondary_rates, "secondary_rates")
        transport = _money(rates.get("transport"), "secondary_rates.transport")
        breakfast = _money(rates.get("breakfast"), "secondary_rates.breakfast")
        lunch = _money(rates.get("lunch"), "secondary_rates.lunch")
        dinner = _money(rates.get("dinner"), "secondary_rates.dinner")
        accommodation = _money(
            rates.get("accommodation"), "secondary_rates.accommodation"
        )
        per_diem = breakfast + lunch + dinner
        total_daily = transport + per_diem + accommodation
        day = SecondaryVisitDay(
            transport=transport,
            breakfast=breakfast,
            lunch=lunch,
            dinner=dinner,
            daily_per_diem=per_diem,
            accommodation=accommodation,
            total_daily_cost=total_daily,
        )
        per_visit = total_daily / total_visits
        share = SecondaryVisitShare(
            allocated_transport=transport / total_visits,
            allocated_breakfast=breakfast / total_visits,
            allocated_lunch=lunch / total_visits,
            allocated_dinner=dinner / total_visits,
            allocated_accommodation=accommodation / total_visits,
            cost_per_school_visit=per_visit,
        )

    return SchoolVisitDayCost(
        user_id=str(person.get("id") or ""),
        role=role,
        is_field_staff=is_field_role(role),
        target_district=str(target_district).strip(),
        district_type=district_type,
        core_visits_count=core,
        client_visits_count=client,
        total_visits=total_visits,
        daily_operational=day,
        allocated_per_visit=share,
        totals=VisitDayTotals(
            cost_per_school_visit=per_visit,
            # Cost parity: a client school visit costs exactly a core one.
            cost_per_core_visit=per_visit,
            cost_per_client_visit=per_visit,
            core_visits_total=per_visit * core,
            client_visits_total=per_visit * client,
            total_day_cost=total_daily,
        ),
    )
