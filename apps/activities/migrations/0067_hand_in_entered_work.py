"""Work holding its Salesforce ID is handed in; a lead's own is approved.

Owner, 2026-10-15: "as long as the activity is completed and entered in
salesforce, completed using salesforce ID it is counted and marked as
completed from my Plan and everywhere they appear ... it is the PL who
approves for CCEO and theirs are approved automatically."

From this release entering the Salesforce ID on staff work hands it in, and a
Programme Lead's own work is approved when it is handed in. Rows written
before it are as the old code left them: a CCEO's or a lead's work with its ID
saved and never handed in (often a visit done ahead of its day, still
"scheduled"), and a lead's own work waiting on the lead. This applies what the
``hand_in_entered_work`` command does (``apps.pl_review.handed_in``) and
prints every row it touches to the deploy log.

As in 0057, 0058 and 0066, the historical models only decide whether there is
anything to do, so on a database with none of these rows (a fresh install,
the test database) the live code is never reached.

Reverse is a no-op: handed-in work stays handed in.
"""

from django.db import migrations
from django.db.models import Q

_STATUSES = (
    "scheduled",
    "rescheduled",
    "in_progress",
    "completion_started",
    "evidence_uploaded",
    "evidence_accepted",
    "salesforce_id_required",
    "completed",
    "submitted_to_pl",
    "awaiting_ia_verification",
)


def hand_in(apps, schema_editor):
    Activity = apps.get_model("activities", "Activity")
    if (
        not Activity.objects.filter(deleted_at__isnull=True, status__in=_STATUSES)
        .exclude(delivery_type="partner")
        .exclude(Q(salesforce_activity_id__isnull=True) | Q(salesforce_activity_id=""))
        .exists()
    ):
        return
    from apps.pl_review.handed_in import hand_in_entered_work

    rows = hand_in_entered_work(apply=True)
    if not rows:
        return
    print()
    for row in rows:
        print(f"  handed in {row['id']}: {row['from']} -> {row['to']}")
    print(f"  work holding its Salesforce ID: {len(rows)} handed in")


class Migration(migrations.Migration):
    dependencies = [("activities", "0066_cancelled_work_stops_counting")]

    operations = [migrations.RunPython(hand_in, migrations.RunPython.noop)]
