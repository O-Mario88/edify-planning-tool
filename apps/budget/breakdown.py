"""How one activity's budget is made up, for the people who check it.

Owner, 2026-10-05: "make sure the activity profile shows the budget breakdown
for that activity for the team to make sure it is the right cost."

The activity page showed one figure. This reads the cost the activity was
priced at, line by line, and says how each line was worked out: the rate,
what it was multiplied by, and, for the day's transport and meals, how many of
the officer's activities share that day (apps.daily_visit_batches).

Nothing here prices anything. The amounts are the stored budget lines
(ActivityScheduleCostLine), the rows the Work Plan and the weekly request
read. The arithmetic beside an amount is written only when it reproduces that
amount to the shilling, so the page never shows a sum that does not add up;
a line it cannot reproduce says what it is and leaves the working out.
"""

from __future__ import annotations

from apps.core.activity_types import NON_FUNDABLE_ACTIVITY_STATUSES

#: A multi-day activity crossing a month end stores a component once per
#: month, under its key and this suffix (costing_service._programme_period_specs).
_PERIOD_SUFFIX = "#m"


def _money(amount: int) -> str:
    return f"UGX {int(amount):,}"


def _activity_name(activity) -> str:
    return activity.activity_name_snapshot or activity.get_activity_type_display()


def _place(activity) -> str:
    if activity.school_id:
        return activity.school.name
    if activity.cluster_id:
        return activity.cluster.name
    return ""


def _joined(words: list[str]) -> str:
    """'transport', 'transport and lunch', 'transport, lunch and dinner'."""
    if len(words) <= 1:
        return "".join(words)
    return f"{', '.join(words[:-1])} and {words[-1]}"


def _base_key(cost_setting_key: str) -> str:
    return (cost_setting_key or "").split(_PERIOD_SUFFIX, 1)[0]


def _day_rate(amount: int, count: int, index: int | None, candidates) -> int | None:
    """The day's full rate behind one activity's share of it: the first
    candidate that, divided between ``count`` activities, gives ``amount``."""
    from apps.daily_visit_batches.pricing import allocate_component

    for rate in candidates:
        if rate is None:
            continue
        shares = allocate_component(int(rate), count)
        if index is not None and 0 <= index < count:
            if shares[index] == amount:
                return int(rate)
        elif amount in shares:
            return int(rate)
    return None


def activity_budget_breakdown(
    activity,
    *,
    snapshot=None,
    staff_name: str = "",
    partner_view: bool = False,
) -> dict:
    """The budget of one activity as rows a person can check.

    ``snapshot`` is the activity's current ActivityCostSnapshot when the
    caller has already read it. ``partner_view`` is a partner reading its own
    work: it sees what it is paid, never the staff member's day.

    Returns ``rows`` (key, label, basis, amount, minimum, status), ``total``,
    ``minimum_total`` and ``show_minimum`` (the CD's minimum viable rates,
    shown only where they differ from the budget), ``day`` (who shares the
    day's costs), ``notes``, ``missing_note`` and ``source``; ``empty_note``,
    ``empty_link`` and ``captured_elsewhere`` say why an activity has no lines.
    """
    from apps.activities.facilitation import FEE_LINE_TYPE
    from apps.budget.costing_service import (
        _missing_label,
        minimum_share,
        setting_for_line,
    )
    from apps.budget.models import ActivityCostSnapshot, CostSetting
    from apps.budget.reference import RATE_UNITS
    from apps.daily_visit_batches.pricing import KEY_LABELS

    lines = list(activity.schedule_cost_lines.all())
    if partner_view and activity.delivery_type != "partner":
        lines = [line for line in lines if line.line_item_type == FEE_LINE_TYPE]
    if snapshot is None:
        snapshot = (
            ActivityCostSnapshot.objects.filter(activity=activity, is_current=True)
            .select_related("operational_rate_card")
            .first()
        )

    priced = (
        {line["key"]: line for line in (snapshot.operational_breakdown or [])}
        if snapshot
        else {}
    )
    rate_card_id = (
        snapshot.operational_rate_card_id
        if snapshot and snapshot.operational_rate_card_id
        else next((line.catalogue_id for line in lines if line.catalogue_id), None)
    )
    rates = (
        {
            (row.catalogue_id, row.key): row
            for row in CostSetting.objects.filter(catalogue_id=rate_card_id)
        }
        if rate_card_id and lines
        else {}
    )
    batch = (
        activity.daily_visit_batch
        if activity.daily_visit_batch_id and not partner_view
        else None
    )

    # One row per cost item, in the order it was priced.
    grouped: dict[str, list] = {}
    for line in sorted(lines, key=lambda row: (row.created_at, row.id)):
        grouped.setdefault(_base_key(line.cost_setting_key), []).append(line)
    order = [key for key in priced if key in grouped]
    order += [key for key in grouped if key not in priced]

    rows = []
    shared_counts: set[int] = set()
    shared_labels: list[str] = []
    for key in order:
        members = grouped[key]
        amount = sum(int(line.amount or 0) for line in members)
        quantity = sum(int(line.quantity or 0) for line in members)
        unit = int(members[0].unit_cost or 0)
        setting = setting_for_line(rates, rate_card_id, key)
        # The snapshot line speaks for these rows only while it is the same
        # money: a repair that moved lines between activities leaves the
        # snapshot behind.
        priced_line = priced.get(key)
        if priced_line is not None and int(priced_line.get("amount") or 0) != amount:
            priced_line = None
        unit_label = (
            (setting.unit if setting and setting.unit != "unit" else "")
            or RATE_UNITS.get(key, "")
        ).strip()
        label = ((setting.label or "").strip() if setting else "") or members[
            0
        ].label.split(" [Rate basis:", 1)[0]

        allocation = (priced_line or {}).get("dailyAllocation")
        missing = bool(priced_line and priced_line.get("missing"))
        if missing:
            basis = "Rate not set in the Cost Catalogue"
        elif key in KEY_LABELS and (allocation or batch is not None):
            count = int(
                allocation["count"] if allocation else (batch.school_count or 1)
            )
            day_rate = _day_rate(
                amount,
                max(count, 1),
                allocation["index"] if allocation else None,
                (
                    (batch.rate_snapshot or {}).get(key) if batch is not None else None,
                    setting.unit_cost if setting else None,
                ),
            )
            if day_rate is None:
                basis = "Share of the day's cost"
            elif count > 1:
                basis = f"{_money(day_rate)} {unit_label} ÷ {count} activities".replace(
                    "  ", " "
                )
                shared_counts.add(count)
            else:
                basis = f"1 × {_money(day_rate)} {unit_label}".strip()
                shared_counts.add(1)
            shared_labels.append(KEY_LABELS[key].split(" ", 1)[0].lower())
        elif quantity * unit == amount:
            basis = f"{quantity:,} × {_money(unit)} {unit_label}".strip()
        else:
            basis = "As priced"

        rows.append(
            {
                "key": key,
                "label": label,
                "basis": basis,
                "amount": amount,
                "missing": missing,
                "minimum": (
                    minimum_share(priced_line, setting)
                    if priced_line is not None
                    else None
                ),
                "status": members[0].finance_status,
            }
        )

    total = sum(row["amount"] for row in rows)
    minimums = [row["minimum"] for row in rows]
    minimum_total = sum(minimums) if rows and None not in minimums else None
    show_minimum = minimum_total is not None and any(
        row["minimum"] != row["amount"] for row in rows
    )

    notes: list[str] = []
    day = None
    if batch is not None and shared_labels and len(shared_counts) == 1:
        count = next(iter(shared_counts))
        who = staff_name or "The responsible officer"
        visit_date = batch.visit_date
        when = f"{visit_date:%A} {visit_date.day} {visit_date:%B %Y}"
        what = _joined(list(dict.fromkeys(shared_labels)))
        others = []
        if count > 1:
            sharing = list(
                batch.activities.filter(deleted_at__isnull=True)
                .exclude(status__in=NON_FUNDABLE_ACTIVITY_STATUSES)
                .select_related("school", "cluster")
                .order_by("planned_date", "id")
            )
            # Name the others only while the day still holds the activities
            # it was priced for.
            if len(sharing) == count:
                others = [
                    {
                        "id": other.id,
                        "name": _activity_name(other),
                        "place": _place(other),
                    }
                    for other in sharing
                    if other.id != activity.id
                ]
            sentence = (
                f"{who} has {count} activities on {when}, so the day's {what} "
                f"{'is' if ' and ' not in what else 'are'} paid once and divided "
                "equally between them."
            )
        else:
            sentence = (
                f"This is the only activity {who} has on {when}, so it carries the "
                f"day's {what} in full. Another activity planned on the same day "
                "would share "
                f"{'it' if ' and ' not in what else 'them'}."
            )
        day = {"count": count, "sentence": sentence, "others": others}

        from apps.daily_visit_batches.return_day import priced_as_return_day

        if priced_as_return_day(batch):
            notes.append(
                "This is the day home from a run of days in a secondary district, "
                "so it carries no accommodation and no dinner."
            )

    missing_items = []
    if not partner_view:
        for key in (snapshot.missing_configuration if snapshot else None) or []:
            missing_items.append(
                "the planned participant count"
                if key == "expectedParticipants"
                else _missing_label(key)
            )

    # The UGX 0 half of an in-school Training / School Visit pair, and the
    # half that carries it (apps.activities.pair_costing).
    empty_note = ""
    empty_link = None
    pair_note = ""
    if not partner_view:
        from apps.activities.models import Activity
        from apps.activities.pair_costing import (
            CAPTURED_IN_TRAINING_NOTE,
            is_uncosted_pair_training,
            pair_cost_notes,
        )

        pair_note = pair_cost_notes([activity]).get(activity.id, "")
        training_id = None
        if activity.activity_type == "school_visit":
            training_id = (
                Activity.objects.filter(
                    paired_school_visit_id=activity.id,
                    activity_type="in_school_training",
                    deleted_at__isnull=True,
                )
                .values_list("id", flat=True)
                .first()
            )
        if pair_note and not rows:
            empty_note = f"UGX 0 {pair_note}"
            if pair_note == CAPTURED_IN_TRAINING_NOTE and training_id:
                empty_link = {"id": training_id, "label": "Open the in-school training"}
            elif is_uncosted_pair_training(activity):
                empty_link = {
                    "id": activity.paired_school_visit_id,
                    "label": "Open the school visit",
                }
        elif rows and training_id:
            notes.append(
                "This visit carries the in-school training done during it; the "
                "training itself is kept at UGX 0."
            )
    missing_note = ""
    if missing_items:
        missing_note = (
            f"Cost setup required: {_joined(missing_items)} "
            f"{'is' if len(missing_items) == 1 else 'are'} not set"
        )
    if not rows and not empty_note:
        empty_note = (
            f"{missing_note}, so this activity has no budget yet."
            if missing_note
            else "No budget has been worked out for this activity yet."
        )

    source = ""
    card = snapshot.operational_rate_card if snapshot and rows else None
    if card is not None:
        source = (
            f"Rates from the {card.label or f'FY{card.fy} Cost Catalogue'}, "
            f"version {card.version}."
        )

    return {
        "rows": rows,
        "total": total,
        "minimum_total": minimum_total,
        "show_minimum": show_minimum,
        "day": day,
        "notes": notes,
        "missing_note": (
            f"{missing_note}, so this total is incomplete."
            if missing_note and rows
            else ""
        ),
        "source": source,
        "calculated_at": snapshot.calculated_at if snapshot and rows else None,
        "empty_note": empty_note,
        "empty_link": empty_link,
        # Set on the UGX 0 half of an in-school Training / School Visit pair.
        "captured_elsewhere": pair_note if not rows else "",
    }


__all__ = ["activity_budget_breakdown"]
