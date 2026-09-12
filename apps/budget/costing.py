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
    "group_training_facilitation_fee",
    "group_training_venue_cost",
)
TOT_MEALS_RATE_KEY = "tot_trainings_meals"
# School work that is SSA work: it carries the SSA Support rate.
SSA_WORK_TYPES = {
    "baseline_ssa_visit",
    "school_visit_ssa_collection",
    "partner_ssa_collection",
    "ssa_activity",
}
# School work at a core school: it carries the core rates.
CORE_WORK_TYPES = {"core_visit", "core_assessment_visit", "core_training"}


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
    costingKind ('core' | 'onetest' | 'tot' | 'student_conference' |
    'proprietor_conference', from the catalogue item's costing profile),
    teachersAttended, leadersAttended, otherParticipants, expectedParticipants,
    nights, days, projectId.

    The recipe (owner, 2026-09-06 catalogue):

    * A staff school mission is a visit day — transport by district and
      lunch; a secondary district adds breakfast, dinner and a night's
      accommodation — and that day is shared across every school planned
      for it (apps/daily_visit_batches). The visit itself has no rate: the
      owner retired Client/Core Staff Visit on 2026-09-12 ("we are adding
      transport + lunch then divide by the number of schools planned for
      that day"). A visit whose reason is OneTest adds the OneTest rate.
    * Partner school work is the partner's rate alone: Client or Core Partner
      Visit for a visit, an in-school training or SSA Support — the owner
      (2026-09-12): "SSA support is the same cost as follow up and other
      partner school visit related activities"; Partner Meetings for a
      partner-run training or a partner/project activity. A partner visit
      whose reason is OneTest fetches the OneTest rate instead.
    * A group session is venue and facilitation per day, printing and
      photocopying of materials, the staff day, and the session's own rate:
      Cluster Meetings/Trainings, TOT trainings (which alone feed their
      participants, at the TOT meals rate), Student or Proprietor Conference.
    * A field event is a visit day for every day away.

    A rate the owner's list ADDED (see ``OPTIONAL_RATE_KEYS``) is charged only
    when the card carries it, so a card that predates the list prices as it
    did; a rate the recipe REQUIRES marks the activity as unfundable when it
    is missing, never substitutes another.
    """
    from apps.budget.reference import (
        OPTIONAL_RATE_KEYS,
        RATE_LABELS,
        with_rate_aliases,
    )

    rates = with_rate_aliases(rates)
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

    def add_rate(key: str, qty: int = 1) -> None:
        """One of the owner's per-activity or materials rates, by its
        catalogue label; skipped on a card that does not carry it."""
        if key in OPTIONAL_RATE_KEYS and key not in rates:
            return
        add(RATE_LABELS.get(key, key), key, qty)

    def add_staff_visit_day(days: int = 1, nights: int | None = None) -> None:
        """One staff day away from base — the ONLY recipe for one.

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
            add(KEY_LABELS[key], key, qty)

    def add_staff_day(days: int = 1) -> None:
        """The staff day inside a group session — the partner's rate already
        covers their own travel, so partner delivery adds none."""
        if is_partner:
            return
        add_staff_visit_day(days)

    def add_materials(days: int) -> None:
        add_rate("printing_training_materials", days)
        add_rate("photocopying_training_materials", days)

    def add_group_session(days: int, rate_key: str | None, meals: bool = False) -> None:
        """The one group-session recipe: the session's own rate, participants
        fed when the session feeds them (TOT trainings), someone facilitates,
        the room costs money, materials are printed and copied, and the staff
        member travels."""
        if rate_key:
            add_rate(rate_key)
        if meals:
            add(
                RATE_LABELS[TOT_MEALS_RATE_KEY],
                TOT_MEALS_RATE_KEY,
                _participants_of(a, 0) * days,
            )
        add(
            RATE_LABELS["group_training_facilitation_fee"],
            "group_training_facilitation_fee",
            days,
        )
        add(RATE_LABELS["group_training_venue_cost"], "group_training_venue_cost", days)
        add_materials(days)
        add_staff_day(days)

    is_partner = a.get("deliveryType") == "partner"
    activity_type = a.get("activityType")
    is_secondary = a.get("districtType") == "secondary"
    kind = a.get("costingKind") or ""
    is_in_school_training = activity_type == "in_school_training"
    is_core = kind == "core" or activity_type in CORE_WORK_TYPES
    is_ssa = activity_type in SSA_WORK_TYPES

    def staff_visit_rate_key() -> str | None:
        """The rate a school mission carries ON TOP of its visit day, or
        None: every staff visit — client, core or SSA collection — is the
        shared visit day alone; only a OneTest reason adds its rate."""
        if kind == "onetest":
            return "onetest"
        return None

    def add_mission_rate() -> None:
        key = staff_visit_rate_key()
        if key:
            add_rate(key)

    if activity_type == "field_event":
        # Attendee-side field work — district meetings, boot camps, workshops.
        # Every day away carries the full per-diem set, accommodation included
        # in a secondary district (owner rule, 2026-08-19).
        add_staff_visit_day(_days_of(a))

    elif activity_type == "programme_event":
        # A conference or camp: a group session with the conference's own
        # rate when the catalogue item says whose conference it is.
        conference = {
            "student_conference": "student_conference",
            "proprietor_conference": "proprietor_conference",
        }.get(kind)
        add_group_session(_days_of(a), conference)

    elif activity_type in CLUSTER_MEETING_TYPES:
        # A cluster meeting: the session rate, the room, the materials and
        # the staff day. Nobody facilitates a meeting.
        days = _days_of(a)
        add_rate("cluster_meetings_trainings")
        add(RATE_LABELS["group_training_venue_cost"], "group_training_venue_cost", days)
        add_materials(days)
        add_staff_day(days)

    elif activity_type in CLUSTER_TRAINING_TYPES:
        add_group_session(_days_of(a), "cluster_meetings_trainings")

    elif is_partner:
        # Each partner workflow has one canonical, CD-visible rate. Do not
        # substitute a different activity's rate merely because the required
        # row is missing; `add` will mark that exact item as a blocker.
        if kind == "onetest":
            key = "onetest"
            basis = "per OneTest visit"
        elif is_in_school_training:
            key = "core_partner_visit" if is_core else "client_partner_visit"
            basis = "per school mission"
        elif activity_type in VISIT_TYPES or is_ssa:
            # SSA Support is a partner school visit and costs as one.
            key = "core_partner_visit" if is_core else "client_partner_visit"
            basis = "per activity"
        elif activity_type in TRAINING_TYPES:
            key = "partner_meetings"
            basis = "per training"
        else:
            key = "partner_meetings"
            basis = "per meeting"
        add(f"{RATE_LABELS[key]} [Rate basis: {basis}]", key)

    elif activity_type in VISIT_TYPES or is_in_school_training:
        # Every school mission by staff is one journey with one recipe, plus
        # the mission's own rate. A secondary-district visit day is an
        # overnight by policy: the Daily Visit Batch pool always carries one
        # night's accommodation unless the activity says otherwise.
        nights = a.get("nights")
        try:
            nights = 1 if nights is None else max(0, int(nights))
        except (TypeError, ValueError):
            nights = 1
        add_mission_rate()
        add_staff_visit_day(1, nights=nights)
    elif activity_type in TRAINING_TYPES:
        # Every group training is the same session; a TOT training also has
        # its own rate and feeds its participants.
        if kind == "tot":
            add_group_session(_days_of(a), "tot_trainings", meals=True)
        else:
            add_group_session(_days_of(a), None)
    elif activity_type in ("partner_activity", "project_activity"):
        add(
            f"{RATE_LABELS['partner_meetings']} [Rate basis: per meeting]",
            "partner_meetings",
        )
    else:
        # ssa_activity and anything else: a staff visit day plus its rate.
        add_mission_rate()
        add_staff_visit_day(1)

    # The costs the Country Director added for this activity's catalogue
    # item (owner, 2026-09-06): each is one line, whatever the recipe above.
    for key, label in a.get("linkedRates") or ():
        add(label, key)

    cost_missing = any(line.missing for line in lines)
    amount = sum(line.amount for line in lines)
    missing_items = [line.key for line in lines if line.missing]
    if any(line.qty == 0 and line.key == TOT_MEALS_RATE_KEY for line in lines):
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
    "TOT_MEALS_RATE_KEY",
    "CLUSTER_MEETING_TYPES",
    "CLUSTER_TRAINING_TYPES",
    "GROUP_TRAINING_RATE_KEYS",
    "LEGACY_CLUSTER_ACTIVITY_COST_KEYS",
    "RETIRED_COST_SETTING_KEYS",
    "cost_for_activity",
]
