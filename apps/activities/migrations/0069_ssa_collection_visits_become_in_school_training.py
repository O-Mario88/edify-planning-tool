"""School Visit + SSA Collection visits still on the plan become In-school
Training + SSA Collection, each awaiting its training (owner, 2026-10-20).

"make sure all those who used "school visit + ssa collection" are changed to
In-school training + SSA Collection and they should be able to fetch the
training from the system." The owner chose to leave completed visits as they
are, and to see a dry run first: ``manage.py convert_ssa_collection_visits``
lists what this changes. The rule lives in
``apps.activities.ssa_collection_to_training``.

As in 0058, the historical model only decides whether there is anything to
do, so on a database with none (a fresh install, the test database) the live
code is never reached and a migration further down the history can never meet
a model newer than its schema.

Reverse is a no-op: each changed visit's purpose before is in the audit trail
(``activity.purpose_changed``).
"""

from django.db import migrations


def convert_visits(apps, schema_editor):
    from apps.activities.ssa_collection_to_training import (
        anything_to_convert,
        convert,
    )

    if not anything_to_convert(apps):
        return
    found = convert(apply=True)
    print(
        f"\n  Changed {len(found['converted'])} School Visit + SSA Collection "
        "visit(s) to In-school Training + SSA Collection: "
        + ", ".join(row["id"] for row in found["converted"])
    )


class Migration(migrations.Migration):
    dependencies = [
        ("activities", "0068_planned_date_before_completion"),
        ("audit", "0008_domain_event_aggregate_id_width"),
    ]

    operations = [migrations.RunPython(convert_visits, migrations.RunPython.noop)]
