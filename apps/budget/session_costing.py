"""
Pure cost calculators for group sessions: a cluster meeting or a group
training, in a primary or a secondary district.

The business rule every calculator here implements has two parts:

* The DIRECT cost of the session itself: participants fed per head, the
  room, and for a training the facilitator and the materials.
* The staff member's DAY away from base: transport and a meal in a primary
  district; transport, the full per diem (breakfast, lunch, dinner) and a
  night's accommodation in a secondary district. That day is paid once and
  shared EQUALLY across every session run on it, so each session carries
  ``daily rate / sessions per day``.

Hence, for all four calculators::

    cost_per_session = direct_cost + daily_rate / sessions_per_day
    total_day_cost   = direct_cost * sessions_per_day + daily_rate

This module is arithmetic only: no models, no rate-card lookups, no writes.
Callers resolve rates (the active Cost Catalogue, apps.budget.reference) and
pass them in. Money is handled as :class:`decimal.Decimal`, so a float or a
form string never introduces binary rounding, and shares are exact quotients
rather than whole shillings: presentation decides rounding, and a per-session
ledger that must sum to the shilling should use
:func:`apps.daily_visit_batches.pricing.allocate_component`.

Every calculator raises :class:`CostingValidationError` for a zero or negative
session count (the divisor) and for any negative count or rate.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.core.exceptions import BadRequest

Number = int | float | Decimal | str

ZERO = Decimal(0)

# Primary-district cluster meeting defaults (the only calculator whose rates
# have agreed defaults; the others take every rate from the caller).
DEFAULT_PRIMARY_MEETING_SNACK_RATE = Decimal(12_000)
DEFAULT_PRIMARY_MEETING_VENUE_FEE = Decimal(50_000)
DEFAULT_PRIMARY_MEETING_DAILY_TRANSPORT = Decimal(300_000)
DEFAULT_PRIMARY_MEETING_DAILY_MEALS = Decimal(30_000)

# A secondary-district session plans for four sessions a day unless told
# otherwise; a secondary training plans for thirty participants.
DEFAULT_SESSIONS_PER_DAY = 4
DEFAULT_SECONDARY_TRAINING_PARTICIPANTS = 30


class CostingValidationError(BadRequest, ValueError):
    """An input the calculators refuse: a zero or negative session count, a
    negative count or rate, or a value that is not a number.

    A ``ValueError`` so plain-Python callers and tests catch it as one; a DRF
    ``BadRequest`` so a view that lets it escape answers 400 with the message
    rather than 500 with none.
    """

    def __init__(self, message: str):
        super().__init__(detail=message)


# ── Input normalisation ──────────────────────────────────────────────────────


def _to_decimal(value: Any, name: str) -> Decimal:
    if isinstance(value, bool):
        raise CostingValidationError(f"{name} must be a number, not a boolean")
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, int):
        amount = Decimal(value)
    elif isinstance(value, float):
        # repr() is the shortest string that round-trips, so 12000.5 stays
        # 12000.5 rather than the binary expansion Decimal(12000.5) exposes.
        amount = Decimal(repr(value))
    elif isinstance(value, str):
        try:
            amount = Decimal(value.strip())
        except InvalidOperation:
            raise CostingValidationError(
                f"{name} must be a number (got {value!r})"
            ) from None
    else:
        raise CostingValidationError(
            f"{name} must be a number (got {type(value).__name__})"
        )
    if not amount.is_finite():
        raise CostingValidationError(f"{name} must be a finite number (got {value!r})")
    return amount


def _money(
    value: Number | None, name: str, *, default: Decimal | None = None
) -> Decimal:
    """A non-negative amount. ``None`` takes the default; a rate with no
    default is required, so a blank required rate is refused rather than
    silently priced at nothing."""
    if value is None:
        if default is None:
            raise CostingValidationError(f"{name} is required")
        return default
    amount = _to_decimal(value, name)
    if amount < 0:
        raise CostingValidationError(f"{name} must not be negative (got {value!r})")
    return amount


def _count(value: Number | None, name: str, *, minimum: int = 0) -> int:
    """A whole number no smaller than ``minimum``. Form payloads carry
    numbers as strings, so "4" counts as 4; 4.5 does not count at all."""
    if value is None:
        raise CostingValidationError(f"{name} is required")
    amount = _to_decimal(value, name)
    if amount != amount.to_integral_value():
        raise CostingValidationError(f"{name} must be a whole number (got {value!r})")
    count = int(amount)
    if count < minimum:
        if minimum > 0:
            raise CostingValidationError(
                f"{name} must be at least {minimum} (got {value!r}): the day's "
                f"rate is shared across the sessions run that day"
            )
        raise CostingValidationError(f"{name} must not be negative (got {value!r})")
    return count


def _per_diem(
    breakfast: Number | None,
    lunch: Number | None,
    dinner: Number | None,
    aggregate: Number | None,
    *,
    aggregate_name: str,
) -> tuple[Decimal | None, Decimal | None, Decimal | None, Decimal]:
    """The day's meal allowance, itemised or as one figure.

    Returns ``(breakfast, lunch, dinner, total)``. The three components are
    ``None`` when the caller passed the aggregate: an aggregate says nothing
    about how it divides, and inventing a split would put a fiction on the
    budget line. Passing both is refused rather than reconciled: if they
    disagree there is no right answer, and if they agree one was redundant.
    """
    itemised = [v for v in (breakfast, lunch, dinner) if v is not None]
    if aggregate is not None:
        if itemised:
            raise CostingValidationError(
                f"pass either {aggregate_name} or breakfast_rate, lunch_rate and "
                f"dinner_rate, not both"
            )
        return None, None, None, _money(aggregate, aggregate_name)
    if not itemised:
        raise CostingValidationError(
            f"either {aggregate_name} or breakfast_rate, lunch_rate and "
            f"dinner_rate is required"
        )
    breakfast_amount = _money(breakfast, "breakfast_rate")
    lunch_amount = _money(lunch, "lunch_rate")
    dinner_amount = _money(dinner, "dinner_rate")
    return (
        breakfast_amount,
        lunch_amount,
        dinner_amount,
        breakfast_amount + lunch_amount + dinner_amount,
    )


@dataclass(frozen=True)
class _CostResult:
    def to_dict(self) -> dict[str, Any]:
        """The same figures as nested plain dicts, for a JSON response or a
        template context. Decimals stay Decimals."""
        return asdict(self)


# ── Cluster meeting, primary district ────────────────────────────────────────


@dataclass(frozen=True)
class PrimaryMeetingDirectCosts:
    snack_total: Decimal
    venue_fee: Decimal
    direct_total: Decimal


@dataclass(frozen=True)
class PrimaryMeetingDailyRates:
    daily_transport: Decimal
    daily_meals: Decimal
    total_daily_rate: Decimal


@dataclass(frozen=True)
class PrimaryMeetingAllocatedRates:
    transport_share: Decimal
    meals_share: Decimal
    allocated_daily_total: Decimal


@dataclass(frozen=True)
class PrimaryMeetingTotals:
    total_cost_per_meeting: Decimal
    total_day_cost: Decimal


@dataclass(frozen=True)
class PrimaryClusterMeetingCost(_CostResult):
    participant_count: int
    meetings_per_day: int
    direct_costs: PrimaryMeetingDirectCosts
    daily_rates: PrimaryMeetingDailyRates
    allocated_daily_rates: PrimaryMeetingAllocatedRates
    totals: PrimaryMeetingTotals


def cost_primary_cluster_meeting(
    participant_count: Number,
    meetings_per_day: Number,
    *,
    snack_rate: Number | None = None,
    venue_fee: Number | None = None,
    daily_transport: Number | None = None,
    daily_meals: Number | None = None,
) -> PrimaryClusterMeetingCost:
    """Cost one cluster meeting in a primary district.

    ::

        snack_total   = participant_count * snack_rate
        direct_total  = snack_total + venue_fee
        allocated     = (daily_transport + daily_meals) / meetings_per_day
        per meeting   = direct_total + allocated
        day           = direct_total * meetings_per_day + daily_transport + daily_meals

    Twenty participants over four meetings at the default rates: snacks
    240,000 and venue 50,000 make 290,000 direct; the day's 330,000 shared four
    ways adds 82,500 (75,000 transport, 7,500 meals), so 372,500 per meeting
    and 1,490,000 for the day. A rate left ``None`` takes its default.
    """
    participants = _count(participant_count, "participant_count")
    meetings = _count(meetings_per_day, "meetings_per_day", minimum=1)
    snack = _money(snack_rate, "snack_rate", default=DEFAULT_PRIMARY_MEETING_SNACK_RATE)
    venue = _money(venue_fee, "venue_fee", default=DEFAULT_PRIMARY_MEETING_VENUE_FEE)
    transport = _money(
        daily_transport,
        "daily_transport",
        default=DEFAULT_PRIMARY_MEETING_DAILY_TRANSPORT,
    )
    meals = _money(
        daily_meals, "daily_meals", default=DEFAULT_PRIMARY_MEETING_DAILY_MEALS
    )

    snack_total = snack * participants
    direct_total = snack_total + venue
    total_daily = transport + meals
    allocated = total_daily / meetings
    return PrimaryClusterMeetingCost(
        participant_count=participants,
        meetings_per_day=meetings,
        direct_costs=PrimaryMeetingDirectCosts(
            snack_total=snack_total, venue_fee=venue, direct_total=direct_total
        ),
        daily_rates=PrimaryMeetingDailyRates(
            daily_transport=transport, daily_meals=meals, total_daily_rate=total_daily
        ),
        allocated_daily_rates=PrimaryMeetingAllocatedRates(
            transport_share=transport / meetings,
            meals_share=meals / meetings,
            allocated_daily_total=allocated,
        ),
        totals=PrimaryMeetingTotals(
            total_cost_per_meeting=direct_total + allocated,
            total_day_cost=direct_total * meetings + total_daily,
        ),
    )


# ── Cluster meeting, secondary district ──────────────────────────────────────


@dataclass(frozen=True)
class SecondaryMeetingDirectCosts:
    participant_meals_total: Decimal
    venue_fee: Decimal
    total_direct: Decimal


@dataclass(frozen=True)
class SecondaryMeetingMeals:
    breakfast: Decimal | None
    lunch: Decimal | None
    dinner: Decimal | None
    total_meals: Decimal


@dataclass(frozen=True)
class SecondaryMeetingDailyOperational:
    transport: Decimal
    meals: SecondaryMeetingMeals
    accommodation: Decimal
    total_daily_operational: Decimal


@dataclass(frozen=True)
class SecondaryMeetingAllocated:
    allocated_transport: Decimal
    allocated_meals: Decimal
    allocated_accommodation: Decimal
    total_allocated: Decimal


@dataclass(frozen=True)
class SecondaryMeetingTotals:
    cost_per_meeting: Decimal
    total_day_budget: Decimal


@dataclass(frozen=True)
class SecondaryClusterMeetingCost(_CostResult):
    participant_count: int
    cluster_meetings_count: int
    direct_costs: SecondaryMeetingDirectCosts
    daily_operational_breakdown: SecondaryMeetingDailyOperational
    allocated_per_meeting: SecondaryMeetingAllocated
    totals: SecondaryMeetingTotals


def cost_secondary_cluster_meeting(
    participant_count: Number,
    cluster_meetings_count: Number = DEFAULT_SESSIONS_PER_DAY,
    *,
    meal_snack_rate_per_person: Number,
    venue_fee: Number,
    transport_daily: Number,
    accommodation_rate: Number,
    breakfast_rate: Number | None = None,
    lunch_rate: Number | None = None,
    dinner_rate: Number | None = None,
    daily_per_diem: Number | None = None,
) -> SecondaryClusterMeetingCost:
    """Cost one cluster meeting in a secondary district, where the staff
    member's day carries the travel per diem and a night's lodging.

    ::

        participant_meals_total = participant_count * meal_snack_rate_per_person
        total_direct            = participant_meals_total + venue_fee
        daily_per_diem          = breakfast_rate + lunch_rate + dinner_rate
        total_daily_operational = transport_daily + daily_per_diem + accommodation_rate
        total_allocated         = total_daily_operational / cluster_meetings_count
        cost_per_meeting        = total_direct + total_allocated
        total_day_budget        = total_direct * cluster_meetings_count
                                  + total_daily_operational

    The per diem is given either as its three meals or as one
    ``daily_per_diem``; not both, not neither.
    """
    participants = _count(participant_count, "participant_count")
    meetings = _count(cluster_meetings_count, "cluster_meetings_count", minimum=1)
    meal_rate = _money(meal_snack_rate_per_person, "meal_snack_rate_per_person")
    venue = _money(venue_fee, "venue_fee")
    transport = _money(transport_daily, "transport_daily")
    accommodation = _money(accommodation_rate, "accommodation_rate")
    breakfast, lunch, dinner, per_diem = _per_diem(
        breakfast_rate,
        lunch_rate,
        dinner_rate,
        daily_per_diem,
        aggregate_name="daily_per_diem",
    )

    participant_meals_total = meal_rate * participants
    total_direct = participant_meals_total + venue
    total_daily = transport + per_diem + accommodation
    total_allocated = total_daily / meetings
    return SecondaryClusterMeetingCost(
        participant_count=participants,
        cluster_meetings_count=meetings,
        direct_costs=SecondaryMeetingDirectCosts(
            participant_meals_total=participant_meals_total,
            venue_fee=venue,
            total_direct=total_direct,
        ),
        daily_operational_breakdown=SecondaryMeetingDailyOperational(
            transport=transport,
            meals=SecondaryMeetingMeals(
                breakfast=breakfast, lunch=lunch, dinner=dinner, total_meals=per_diem
            ),
            accommodation=accommodation,
            total_daily_operational=total_daily,
        ),
        allocated_per_meeting=SecondaryMeetingAllocated(
            allocated_transport=transport / meetings,
            allocated_meals=per_diem / meetings,
            allocated_accommodation=accommodation / meetings,
            total_allocated=total_allocated,
        ),
        totals=SecondaryMeetingTotals(
            cost_per_meeting=total_direct + total_allocated,
            total_day_budget=total_direct * meetings + total_daily,
        ),
    )


# ── Group training: the direct recipe both districts share ───────────────────


@dataclass(frozen=True)
class TrainingDirectCosts:
    participant_meals_total: Decimal
    venue_fee: Decimal
    facilitation_fee: Decimal
    materials_cost: Decimal
    total_direct: Decimal


@dataclass(frozen=True)
class TrainingTotals:
    cost_per_training: Decimal
    total_day_cost: Decimal


def _training_direct_costs(
    participants: int,
    meal_rate_per_participant: Number,
    venue_fee: Number | None,
    facilitation_fee: Number | None,
    materials_cost: Number | None,
) -> TrainingDirectCosts:
    """One session's own bill: everyone fed, the room, the facilitator and
    the handouts. Venue, facilitation and materials default to nothing, which
    is right for a session at an internal office or a school hall run by the
    staff member with no printing."""
    meal_rate = _money(meal_rate_per_participant, "meal_rate_per_participant")
    venue = _money(venue_fee, "venue_fee", default=ZERO)
    facilitation = _money(facilitation_fee, "facilitation_fee", default=ZERO)
    materials = _money(materials_cost, "materials_cost", default=ZERO)
    participant_meals_total = meal_rate * participants
    return TrainingDirectCosts(
        participant_meals_total=participant_meals_total,
        venue_fee=venue,
        facilitation_fee=facilitation,
        materials_cost=materials,
        total_direct=participant_meals_total + venue + facilitation + materials,
    )


# ── Group training, primary district ─────────────────────────────────────────


@dataclass(frozen=True)
class PrimaryTrainingDailyOperational:
    transport: Decimal
    staff_lunch: Decimal
    total_daily: Decimal


@dataclass(frozen=True)
class PrimaryTrainingAllocated:
    allocated_transport: Decimal
    allocated_staff_lunch: Decimal
    total_allocated: Decimal


@dataclass(frozen=True)
class PrimaryGroupTrainingCost(_CostResult):
    participant_count: int
    trainings_per_day: int
    direct_costs: TrainingDirectCosts
    daily_operational_costs: PrimaryTrainingDailyOperational
    allocated_per_training: PrimaryTrainingAllocated
    totals: TrainingTotals


def cost_primary_group_training(
    participant_count: Number,
    trainings_per_day: Number,
    *,
    meal_rate_per_participant: Number,
    daily_transport: Number,
    daily_staff_lunch: Number,
    venue_fee: Number | None = 0,
    facilitation_fee: Number | None = 0,
    materials_cost: Number | None = 0,
) -> PrimaryGroupTrainingCost:
    """Cost one group training in a primary district.

    ::

        participant_meals_total = participant_count * meal_rate_per_participant
        total_direct  = participant_meals_total + venue_fee + facilitation_fee
                        + materials_cost
        total_daily   = daily_transport + daily_staff_lunch
        total_allocated = total_daily / trainings_per_day
        cost_per_training = total_direct + total_allocated
        total_day_cost    = total_direct * trainings_per_day + total_daily
    """
    participants = _count(participant_count, "participant_count")
    trainings = _count(trainings_per_day, "trainings_per_day", minimum=1)
    direct = _training_direct_costs(
        participants,
        meal_rate_per_participant,
        venue_fee,
        facilitation_fee,
        materials_cost,
    )
    transport = _money(daily_transport, "daily_transport")
    staff_lunch = _money(daily_staff_lunch, "daily_staff_lunch")

    total_daily = transport + staff_lunch
    total_allocated = total_daily / trainings
    return PrimaryGroupTrainingCost(
        participant_count=participants,
        trainings_per_day=trainings,
        direct_costs=direct,
        daily_operational_costs=PrimaryTrainingDailyOperational(
            transport=transport, staff_lunch=staff_lunch, total_daily=total_daily
        ),
        allocated_per_training=PrimaryTrainingAllocated(
            allocated_transport=transport / trainings,
            allocated_staff_lunch=staff_lunch / trainings,
            total_allocated=total_allocated,
        ),
        totals=TrainingTotals(
            cost_per_training=direct.total_direct + total_allocated,
            total_day_cost=direct.total_direct * trainings + total_daily,
        ),
    )


# ── Group training, secondary district ───────────────────────────────────────


@dataclass(frozen=True)
class SecondaryTrainingMeals:
    breakfast: Decimal | None
    lunch: Decimal | None
    dinner: Decimal | None
    total_per_diem: Decimal


@dataclass(frozen=True)
class SecondaryTrainingDailyOperational:
    transport: Decimal
    meals: SecondaryTrainingMeals
    accommodation: Decimal
    total_daily_allowances: Decimal


@dataclass(frozen=True)
class SecondaryTrainingAllocated:
    allocated_transport: Decimal
    allocated_meals: Decimal
    allocated_accommodation: Decimal
    total_allocated: Decimal


@dataclass(frozen=True)
class SecondaryGroupTrainingCost(_CostResult):
    participant_count: int
    trainings_per_day: int
    direct_costs: TrainingDirectCosts
    daily_operational_breakdown: SecondaryTrainingDailyOperational
    allocated_per_training: SecondaryTrainingAllocated
    totals: TrainingTotals


def cost_secondary_group_training(
    participant_count: Number = DEFAULT_SECONDARY_TRAINING_PARTICIPANTS,
    trainings_per_day: Number = DEFAULT_SESSIONS_PER_DAY,
    *,
    meal_rate_per_participant: Number,
    transport_rate: Number,
    accommodation_rate: Number,
    breakfast_rate: Number | None = None,
    lunch_rate: Number | None = None,
    dinner_rate: Number | None = None,
    per_diem_total: Number | None = None,
    venue_fee: Number | None = 0,
    facilitation_fee: Number | None = 0,
    materials_cost: Number | None = 0,
) -> SecondaryGroupTrainingCost:
    """Cost one group training in a secondary district, where the staff
    member's day carries the travel per diem and a night's lodging.

    ::

        participant_meals_total = participant_count * meal_rate_per_participant
        total_direct  = participant_meals_total + venue_fee + facilitation_fee
                        + materials_cost
        per_diem_total = breakfast_rate + lunch_rate + dinner_rate
        total_daily_allowances = transport_rate + per_diem_total
                                 + accommodation_rate
        total_allocated   = total_daily_allowances / trainings_per_day
        cost_per_training = total_direct + total_allocated
        total_day_cost    = total_direct * trainings_per_day
                            + total_daily_allowances

    The per diem is given either as its three meals or as one
    ``per_diem_total``; not both, not neither.
    """
    participants = _count(participant_count, "participant_count")
    trainings = _count(trainings_per_day, "trainings_per_day", minimum=1)
    direct = _training_direct_costs(
        participants,
        meal_rate_per_participant,
        venue_fee,
        facilitation_fee,
        materials_cost,
    )
    transport = _money(transport_rate, "transport_rate")
    accommodation = _money(accommodation_rate, "accommodation_rate")
    breakfast, lunch, dinner, per_diem = _per_diem(
        breakfast_rate,
        lunch_rate,
        dinner_rate,
        per_diem_total,
        aggregate_name="per_diem_total",
    )

    total_daily = transport + per_diem + accommodation
    total_allocated = total_daily / trainings
    return SecondaryGroupTrainingCost(
        participant_count=participants,
        trainings_per_day=trainings,
        direct_costs=direct,
        daily_operational_breakdown=SecondaryTrainingDailyOperational(
            transport=transport,
            meals=SecondaryTrainingMeals(
                breakfast=breakfast, lunch=lunch, dinner=dinner, total_per_diem=per_diem
            ),
            accommodation=accommodation,
            total_daily_allowances=total_daily,
        ),
        allocated_per_training=SecondaryTrainingAllocated(
            allocated_transport=transport / trainings,
            allocated_meals=per_diem / trainings,
            allocated_accommodation=accommodation / trainings,
            total_allocated=total_allocated,
        ),
        totals=TrainingTotals(
            cost_per_training=direct.total_direct + total_allocated,
            total_day_cost=direct.total_direct * trainings + total_daily,
        ),
    )


__all__ = [
    "Number",
    "CostingValidationError",
    "DEFAULT_PRIMARY_MEETING_SNACK_RATE",
    "DEFAULT_PRIMARY_MEETING_VENUE_FEE",
    "DEFAULT_PRIMARY_MEETING_DAILY_TRANSPORT",
    "DEFAULT_PRIMARY_MEETING_DAILY_MEALS",
    "DEFAULT_SESSIONS_PER_DAY",
    "DEFAULT_SECONDARY_TRAINING_PARTICIPANTS",
    "PrimaryMeetingDirectCosts",
    "PrimaryMeetingDailyRates",
    "PrimaryMeetingAllocatedRates",
    "PrimaryMeetingTotals",
    "PrimaryClusterMeetingCost",
    "cost_primary_cluster_meeting",
    "SecondaryMeetingDirectCosts",
    "SecondaryMeetingMeals",
    "SecondaryMeetingDailyOperational",
    "SecondaryMeetingAllocated",
    "SecondaryMeetingTotals",
    "SecondaryClusterMeetingCost",
    "cost_secondary_cluster_meeting",
    "TrainingDirectCosts",
    "TrainingTotals",
    "PrimaryTrainingDailyOperational",
    "PrimaryTrainingAllocated",
    "PrimaryGroupTrainingCost",
    "cost_primary_group_training",
    "SecondaryTrainingMeals",
    "SecondaryTrainingDailyOperational",
    "SecondaryTrainingAllocated",
    "SecondaryGroupTrainingCost",
    "cost_secondary_group_training",
]
