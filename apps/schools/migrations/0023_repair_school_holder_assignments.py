"""The portfolio says what the school record says about who holds a school.

Owner, 2026-10-02: "PL are not seeing all the plans for their cceos ... Repair
the old school holder mismatches."

``School.account_owner_id`` is the holder; ``StaffSchoolAssignment`` is the
same fact as the scoping chain reads it. Four paths that named a new holder —
the school upload, the directory's match and bulk match, staff setup — added
the new holder's row and left the previous holder's. The school then sat in
two people's scope, and in two Programme Leads', while the directory and the
monitors filed it under one; where the old row was the only one, the holder's
Programme Lead did not have the school at all. Those paths now replace the
row (`apps.schools.ownership_transfer.hold_schools`). This repairs the rows
they left behind.

WHAT CHANGES
Only portfolio rows, and only toward the school record, which every one of
those paths wrote last:

* a row naming anybody but the school's holder is removed;
* the holder's own row is added where it is missing.

WHAT DOES NOT
The school record is not written. A school with no holder, or a holder that
resolves to no staff profile, is left exactly as it is. No activity, plan,
cluster or hand-over is touched: they follow the holder already.

Every change is printed to the deploy log, one line each, with the school ID
and both people, so a removed row can be put back by hand. The same report,
without the change, is ``python manage.py reconcile_school_holders``.

The work is three reads and two batched writes over historical models
(`apps.schools.holder_reconcile` takes the model classes and reads no column
newer than this migration's dependencies), so it stays well inside the
deploy job's time.

Reverse is a no-op: the removed rows are not recreated.
"""

from __future__ import annotations

from django.db import migrations


def repair_school_holder_assignments(apps, schema_editor):
    from apps.schools.holder_reconcile import apply_holder_repair, plan_holder_repair

    School = apps.get_model("schools", "School")
    StaffProfile = apps.get_model("accounts", "StaffProfile")
    StaffSchoolAssignment = apps.get_model("accounts", "StaffSchoolAssignment")

    plan = plan_holder_repair(School, StaffProfile, StaffSchoolAssignment)
    print(
        "\n  [schools.0023] school holders: "
        f"{plan.schools_with_holder} schools with a holder; "
        f"{plan.schools_also_assigned_elsewhere} also assigned to somebody else; "
        f"{len(plan.missing)} missing their holder's own row; "
        f"{plan.unresolved} with a holder that is no staff profile (left alone)."
    )
    if not plan:
        print("  [schools.0023] nothing to repair.")
        return
    for line in plan.lines():
        print(f"  [schools.0023] {line}")
    apply_holder_repair(plan, StaffSchoolAssignment)
    print(
        f"  [schools.0023] repaired {plan.schools_changed} schools: "
        f"{len(plan.stray)} rows removed, {len(plan.missing)} added."
    )


class Migration(migrations.Migration):
    dependencies = [
        ("schools", "0022_school_ownership_transfers"),
        ("accounts", "0035_staff_activity_sessions"),
    ]

    operations = [
        migrations.RunPython(
            repair_school_holder_assignments, migrations.RunPython.noop
        ),
    ]
