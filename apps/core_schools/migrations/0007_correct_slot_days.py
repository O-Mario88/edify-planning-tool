"""Put Core package slots back on the day their work is planned for.

Owner, 2026-10-02: "The calendar is completely off … the planned are falling
on different days."

A day chosen in a scheduling drawer is saved as midnight Africa/Nairobi, which
the database hands back as 21:00 UTC on the day before. The three places that
date a package slot from its activity (``Activity.save``,
``package_credit`` and ``cluster_credit``) read that instant's UTC day, so a
visit planned for 29 September left its slot saying 28 September. They now
read the local day (``apps.core.clock.local_day``).

This corrects the slots already written. Only a slot whose stored day is
exactly its activity's UTC day, where that differs from the local day, is
touched: a slot dated by hand, or already right, is left alone.

Historical models only, and no live service code (see activities 0057/0058).
Every corrected slot is printed to the deploy log. The reverse is a no-op.
"""

from __future__ import annotations

from datetime import date, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import migrations

_BATCH = 500


def _stored_day(value) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def correct_slot_days(Slot, Activity, *, write: bool = True, out=print) -> list[dict]:
    """Move each slot that sits a day early onto its activity's local day.

    Returns what was (or, with ``write=False``, would be) corrected.
    """
    local_zone = ZoneInfo(settings.TIME_ZONE)
    slots = list(
        Slot.objects.exclude(activity_id__isnull=True)
        .exclude(activity_id="")
        .exclude(scheduled_for__isnull=True)
        .exclude(scheduled_for="")
        .order_by("id")
    )
    instants: dict[str, object] = {}
    ids = sorted({slot.activity_id for slot in slots})
    for start in range(0, len(ids), _BATCH):
        instants.update(
            Activity.objects.filter(
                id__in=ids[start : start + _BATCH], scheduled_date__isnull=False
            ).values_list("id", "scheduled_date")
        )

    corrected = []
    for slot in slots:
        instant = instants.get(slot.activity_id)
        stored = _stored_day(slot.scheduled_for)
        if instant is None or stored is None:
            continue
        utc_day = instant.astimezone(dt_timezone.utc).date()
        local_day = instant.astimezone(local_zone).date()
        if utc_day == local_day or stored != utc_day:
            continue
        corrected.append(
            {
                "slot": slot.id,
                "activity": slot.activity_id,
                "from": stored.isoformat(),
                "to": local_day.isoformat(),
            }
        )
        if write:
            slot.scheduled_for = local_day.isoformat()
            slot.save(update_fields=["scheduled_for"])
        out(
            f"[0007_correct_slot_days] slot {slot.id} (activity "
            f"{slot.activity_id}): {stored.isoformat()} -> {local_day.isoformat()}"
        )
    out(f"[0007_correct_slot_days] {len(corrected)} slot day(s) corrected")
    return corrected


def forwards(apps, schema_editor):
    correct_slot_days(
        apps.get_model("core_schools", "CoreActivitySlot"),
        apps.get_model("activities", "Activity"),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core_schools", "0006_core_package_split_counting"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
