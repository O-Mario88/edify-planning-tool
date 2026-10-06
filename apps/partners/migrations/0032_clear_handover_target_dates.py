"""A hand-over the partner has not scheduled carries no date.

Owner, 2026-10-05: "the date on the partner assignment drawer should change
from target date to assigned date so that the staff cannot schedule for the
partner. Block any potential scheduling for the partner visit."

The bulk Assign drawers took an optional Target date and stored it in
``scheduled_date``, the column the partner's own scheduling writes. Pages
that read the column then showed a day a staff member had typed as the
planned date, and as overdue once it passed. The drawers no longer ask for
one, and ``partners.services.create_assignment`` no longer stores one.

This clears the dates already stored on hand-overs still waiting for the
partner. The day each hand-over was made is its ``created_at``, untouched.
Every cleared row is printed, so the deploy log keeps what was there.
"""

from django.db import migrations

WAITING = ("assigned", "pending_scheduling")


def clear_target_dates(apps, schema_editor):
    PartnerAssignment = apps.get_model("partners", "PartnerAssignment")
    waiting = PartnerAssignment.objects.filter(
        status__in=WAITING,
        scheduled_activity__isnull=True,
        scheduled_date__isnull=False,
    )
    rows = list(waiting.values_list("id", "scheduled_date").order_by("created_at"))
    if not rows:
        return
    for assignment_id, target in rows:
        print(f"  hand-over {assignment_id}: target date {target} cleared")
    waiting.update(scheduled_date=None)
    print(f"  {len(rows)} hand-over target date(s) cleared")


class Migration(migrations.Migration):
    dependencies = [
        ("partners", "0031_data_collection_handovers_apart"),
    ]

    operations = [
        migrations.RunPython(clear_target_dates, migrations.RunPython.noop),
    ]
