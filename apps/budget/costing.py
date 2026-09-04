"""
The automatic costing engine — faithful port of costing.ts.

Every scheduled activity is costed from the CD-owned rate card (CostSetting,
keyed by a stable string). No staff invents a cost. If a required rate is
missing, the activity is flagged costMissing and must not enter a budget / fund
request until the CD resolves it (spec §10).

This is the SINGLE source of truth for activity cost on the backend.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from apps.core.activity_types import CLUSTER_MEETING_TYPES, TRAINING_TYPES, VISIT_TYPES
from apps.budget.reference import (
    LEGACY_CLUSTER_ACTIVITY_COST_KEYS,
    RETIRED_COST_SETTING_KEYS,
)


RateCard = dict  # CostSetting.key -> unitCost


@dataclass
class CostLine:
    label: str
    key: str
    unit: int | None  # None = rate missing; integer UGX when present
    qty: int
    amount: int  # integer UGX (0 when the rate is missing)
    missing: bool
    allocation_count: int | None = None
    allocation_index: int | None = None


@dataclass
class ActivityCost:
    amount: int = 0  # integer UGX
    lines: list[CostLine] = field(default_factory=list)
    cost_missing: bool = False
    missing_items: list[str] = field(default_factory=list)


# A cluster session has a deliberately small, predictable cost recipe.  These
# stable keys are shared by the catalogue, planning preview, saved schedule
# lines, fund requests and budget reports.  Do not add ad-hoc cluster costs in
# a caller: ``cost_for_activity`` is the one place that defines the recipe.
CLUSTER_TRAINING_TYPES = {
    "cluster_training",
    "cluster_training_ssa_collection",
}
GROUP_TRAINING_RATE_KEYS = (
    "group_training_participant_meal_cost_per_head",
    "group_training_facilitation_fee",
    "group_training_venue_cost",
)
CLUSTER_MEETING_SNACK_RATE_KEY = "cluster_meeting_participant_meal_cost_per_head"


def _nonnegative_count(raw) -> int:
    """Normalize a participant count from an API or HTML form payload.

    Django's request payloads keep number inputs as strings.  Costing is also
    called by JSON clients and by persisted-model serializers, so this pure
    engine deliberately accepts either representation.  Invalid or negative
    values contribute zero here; the scheduling/completion services remain
    responsible for returning their field-specific validation errors.
    """
    try:
        return max(0, int(raw or 0))
    except (TypeError, ValueError):
        return 0


def _participants_of(a: dict, default_n: int) -> int:
    """Participant quantity for per-head pricing.

    The PLANNED count drives the budget (2026-07-30 audit §32: participant
    rate × planned participant count) — attendance actuals are a completion
    record, and preferring them here meant a post-completion reschedule
    silently converted a planned estimate into an actuals-based figure.
    Actuals are used only when no plan was ever captured, ahead of the
    hardcoded default."""
    if a.get("expectedParticipants") is not None:
        return _nonnegative_count(a["expectedParticipants"])
    counted = sum(
        _nonnegative_count(a.get(key))
        for key in (
            "teachersAttended",
            "leadersAttended",
            "otherParticipants",
        )
    )
    return counted if counted > 0 else default_n


def _days_of(a: dict) -> int:
    """Service days an activity spans (1 unless it carries a date range).

    A Group-delivered camp or conference planned centrally from the Work Plan
    runs for several days, and its per-day components must be priced per day.
    Everything scheduled through school/cluster planning has no end date and
    therefore prices exactly as before."""
    try:
        return max(1, int(a.get("days") or 1))
    except (TypeError, ValueError):
        return 1


def cost_for_activity(a: dict, rates: RateCard) -> ActivityCost:
    """Compute the cost of an activity from the rate card.

    `a` keys: activityType, deliveryType, districtType ('primary'|'secondary'),
    teachersAttended, leadersAttended, otherParticipants, expectedParticipants,
    nights, projectId.
    """
    lines: list[CostLine] = []

    def add(label: str, key: str, qty: int = 1) -> None:
        unit = rates.get(key)
        missing = unit is None
        lines.append(
            CostLine(
                label=label,
                key=key,
                unit=None if missing else unit,
                qty=qty,
                amount=0 if missing else unit * qty,
                missing=missing,
            )
        )

    def add_staff_visit_day(days: int = 1, nights: int | None = None) -> None:
        """One staff day away from base — the ONLY recipe for one.

        This used to be written three times: here, inline in the visit branch
        and again in the field-event branch. The inline copies left out
        `secondary_incidentals_per_day`, so the same person on the same day
        cost 157,000 inside a cluster training and 152,000 on a school visit
        (owner, 2026-09-04: "fix all the cost").

        `nights` exists because a visit day charges accommodation per NIGHT
        (one by default, the activity may say otherwise) while a multi-day
        trip carries the full per-diem set per day.
        """
        from apps.daily_visit_batches.pricing import (
            KEY_LABELS,
            OPTIONAL_KEYS,
            REQUIRED_KEYS,
        )

        profile = "secondary" if is_secondary else "primary"
        nights = days if nights is None else nights
        for key in REQUIRED_KEYS[profile] + OPTIONAL_KEYS[profile]:
            if key in OPTIONAL_KEYS[profile] and key not in rates:
                continue
            qty = nights if key == "secondary_accommodation_per_night" else days
            if qty <= 0:
                continue
            add(KEY_LABELS[key].replace("shared, ", ""), key, qty)

    def add_staff_day(days: int = 1) -> None:
        """The staff day inside a group session — the partner's lump sum
        already covers their own travel, so partner delivery adds none."""
        if is_partner:
            return
        add_staff_visit_day(days)

    def add_group_session(days: int) -> None:
        """The one group-training recipe: participants eat, someone
        facilitates, the room costs money, and the staff member travels.
        Cluster trainings, general trainings and non-school programme events
        (conferences, camps) are the same event with different attendees."""
        n = _participants_of(a, 0)
        add(
            "Participant meals",
            "group_training_participant_meal_cost_per_head",
            n * days,
        )
        add("Facilitation fee", "group_training_facilitation_fee", days)
        add("Venue fee", "group_training_venue_cost", days)
        add_staff_day(days)

    is_partner = a.get("deliveryType") == "partner"
    activity_type = a.get("activityType")
    is_secondary = a.get("districtType") == "secondary"
    # An in-school training is delivered during the same school mission as a
    # school visit. Its Training record describes the programme result, not a
    # second journey or a venue-based group training. Price it from the visit
    # recipe for both staff and partner delivery.
    is_in_school_training = activity_type == "in_school_training"

    # Non-school programme events (conferences, camps, exhibitions, launches)
    # price from the configurable programme component keys. Days come from the
    # activity's date range; participants from the PLANNED count. A component
    # is included only when the CD has configured its rate, except the two
    # core components (venue + participant meals) which are always demanded so
    # a missing rate blocks funded scheduling rather than under-costing.
    # Attendee-side field events (district meetings, boot camps, workshops)
    # price from the MOU travel per-diems. The profile derives from the
    # owner's PRIMARY (home) district vs the destination: same district — or
    # a same-day return — draws transport + lunch; a different district with
    # an overnight adds accommodation, dinner and breakfast per night.
    if activity_type == "field_event":
        # Attendee-side field work — district meetings, boot camps, workshops.
        # Every day away carries the full per-diem set, accommodation included
        # in a secondary district (owner rule, 2026-08-19).
        add_staff_visit_day(_days_of(a))

    elif activity_type == "programme_event":
        # A conference, camp, exhibition or launch is a group training whose
        # attendees are not one school's staff. It had its own six-key rate
        # family — venue 300,000 against the group training's 30,000,
        # facilitation 100,000 against 50,000 — for an activity type no
        # catalogue item even produced, while the real conferences and camps
        # were catalogued as trainings and priced on the group recipe. One
        # recipe (owner, 2026-09-04).
        add_group_session(_days_of(a))

    # Cluster meetings and cluster trainings use their fixed recipe even when
    # a partner delivers the session.  The programme budget needs the same
    # transparent snack/meal/facilitation/venue breakdown in every workflow.
    elif activity_type in CLUSTER_MEETING_TYPES:
        n = _participants_of(a, 0)
        days = _days_of(a)
        add("Participant snacks", CLUSTER_MEETING_SNACK_RATE_KEY, n * days)
        add("Venue fee", "group_training_venue_cost", days)
        add_staff_day(days)

    elif activity_type in CLUSTER_TRAINING_TYPES:
        add_group_session(_days_of(a))

    elif is_partner:
        # Each partner workflow has one canonical, CD-visible rate. Do not
        # substitute a different activity's rate merely because the required
        # row is missing; `add` will mark that exact item as a blocker.
        if is_in_school_training:
            key = "partner_visit_lump_sum"
            basis = "per school mission"
            label = "Partner visit rate"
        elif activity_type in TRAINING_TYPES:
            key = "partner_training_lump_sum"
            basis = "per training"
            label = "Partner training rate"
        else:
            # Including special-project work: `project_partner_lump_sum` held
            # the same 40,000 as the partner visit rate, so it was a second
            # name for one number (owner, 2026-09-04).
            key = "partner_visit_lump_sum"
            basis = "per activity"
            label = "Partner visit lump sum"

        label_with_basis = f"{label} [Rate basis: {basis}]"
        add(label_with_basis, key)

    elif activity_type in VISIT_TYPES or is_in_school_training:
        # Every school mission by staff, whatever the school is called: an
        # ordinary visit, a core school visit, an SSA visit, a core
        # assessment, a special-project visit and an in-school training are
        # one journey with one recipe. `core_school_visit` and
        # `ssa_visit_rate` used to intercept two of them with a flat 50,000
        # that ignored the district — 12,000 short in a primary district and
        # 102,000 short in a secondary one (owner, 2026-09-04).
        #
        # A secondary-district visit day is an overnight by policy: the Daily
        # Visit Batch pool always carries one night's accommodation unless the
        # activity says otherwise.
        nights = a.get("nights")
        try:
            nights = 1 if nights is None else max(0, int(nights))
        except (TypeError, ValueError):
            nights = 1
        add_staff_visit_day(1, nights=nights)
    elif activity_type in TRAINING_TYPES:
        # Every group training is the same event: cluster, general, core and
        # special-project trainings all price here (owner, 2026-09-02 and
        # 2026-09-04). `core_training` used to take a 55,000 lump of its own.
        add_group_session(_days_of(a))
    elif activity_type in ("partner_activity", "project_activity"):
        add("Partner/project lump sum", "partner_visit_lump_sum")
    else:
        # ssa_activity and anything else: a staff visit day. This used to add
        # PRIMARY transport and lunch whatever the district, so the same work
        # in a secondary district was costed 90,000 short.
        add_staff_visit_day(1)

    cost_missing = any(line.missing for line in lines)
    amount = sum(line.amount for line in lines)
    missing_items = [line.key for line in lines if line.missing]
    if any(
        line.qty == 0
        and line.key
        in {
            "group_training_participant_meal_cost_per_head",
            CLUSTER_MEETING_SNACK_RATE_KEY,
        }
        for line in lines
    ):
        missing_items.append("expectedParticipants")
        cost_missing = True
    return ActivityCost(
        amount=amount,
        lines=lines,
        cost_missing=cost_missing,
        missing_items=missing_items,
    )


# NOTE: a `resolve_activity_cost` helper used to live here ("prefer the
# snapshot; recalc when actuals exist"). It had no callers, and its recalc
# branch would have re-priced completed work at CURRENT rates — the exact
# snapshot-vs-live desync the persisted cost lines exist to prevent — so it
# was removed rather than left as an attractive nuisance (2026-08-12 audit L-1).

__all__ = [
    "RateCard",
    "CostLine",
    "ActivityCost",
    "CLUSTER_MEETING_SNACK_RATE_KEY",
    "CLUSTER_MEETING_TYPES",
    "CLUSTER_TRAINING_TYPES",
    "GROUP_TRAINING_RATE_KEYS",
    "LEGACY_CLUSTER_ACTIVITY_COST_KEYS",
    "RETIRED_COST_SETTING_KEYS",
    "cost_for_activity",
]
