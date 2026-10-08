"""Cancelled work stops counting: put right what earlier cancellations left.

Owner, 2026-10-08: "cancelled activities should undo the scheduling done" and
"the cancelled activities should not remain counting ... the v1 or v2 v3 or
v4 should be reset back to the actual scheduled activities."

From this release a cancellation gives its Core package slot back, renumbers
what is left, and puts a Partner's hand-over back to waiting for its date.
Rows written before it are still as the old code left them: package slots
pointing at cancelled work, and hand-overs "scheduled by the partner" on a
cancelled activity. This applies the same repair the
``repair_cancelled_work`` command runs (``apps.activities.cancelled_work``),
and prints every row it touches to the deploy log.

As in 0057 and 0058, the historical models only decide whether there is
anything to do, so on a database with none of these rows (a fresh install,
the test database) the live code is never reached. A row that cannot be put
right is reported and left; the migration does not fail over it.

Reverse is a no-op: the slots stay given back.
"""

from django.db import migrations


def repair(apps, schema_editor):
    from apps.activities import cancelled_work

    found = cancelled_work.find(
        apps.get_model("core_schools", "CoreActivitySlot"),
        apps.get_model("activities", "Activity"),
        apps.get_model("partners", "PartnerAssignment"),
    )
    if not (found["slots"] or found["handovers"]):
        return
    print()
    report = cancelled_work.repair(write=True, out=print)
    print(
        f"  cancelled work: {report['slots']} slot(s) given back, "
        f"{report['renumbered']} renumbered, {report['reopened']} hand-over(s) "
        f"waiting again, {report['closed']} closed, {report['skipped']} left"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("activities", "0065_activity_meeting_kind"),
        ("core_schools", "0012_index_slot_activity"),
        ("partners", "0032_clear_handover_target_dates"),
    ]

    operations = [migrations.RunPython(repair, migrations.RunPython.noop)]
