"""Re-file work dated 1 October, January, April or July under its own year and
quarter.

Until 2026-09-28 a date picked in the app — stored as local midnight, 21:00
UTC the day before — was read in UTC, so work on the new year's first day went
to the old year and work on a quarter's first day to the quarter before. The
reading is fixed in ``apps.core.fy``; which rows are re-filed, and how, lives
in ``apps.activities.fy_boundary_refile`` (the ``refile_fy_boundary_rows``
command runs the same code). Only a value that is exactly the old reading's is
changed. Every re-filed row is printed to the deploy log.

As in 0057 and 0058, the historical models decide whether there is anything to
do and write the corrections; the live fund-request sync runs only when a cost
line moved period, so on a database with nothing misfiled (a fresh install,
the test database) no live code is reached.

Reverse is a no-op: the old values were wrong.
"""

from django.db import migrations


def refile(apps, schema_editor):
    from apps.activities.fy_boundary_refile import find_misfiled, refile_misfiled

    rows = find_misfiled(apps)
    if not rows:
        return
    refile_misfiled(rows, registry=apps)


class Migration(migrations.Migration):
    dependencies = [
        ("activities", "0059_activity_facilitating_partner"),
        ("budget", "0022_group_training_meals_rate"),
        ("fund_requests", "0018_weekly_funding_source"),
        ("ssa", "0009_ssa_record_source_and_return"),
    ]

    operations = [migrations.RunPython(refile, migrations.RunPython.noop)]
