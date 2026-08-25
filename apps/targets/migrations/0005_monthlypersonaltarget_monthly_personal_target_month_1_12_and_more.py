"""INT-01: closed domains on the personal-target tables.

apps/targets declared two unique constraints and ZERO check constraints. The
three domains pinned here are each already stated in the models themselves
and enforced nowhere:

  * month_of_fy is "1 = October … 12 = September" (the field's own comment),
    and the only writer enumerates exactly that range. Out of range, the row
    is unreachable by every quarter and FY roll-up that derives its period
    from the number — it stops counting silently instead of failing.
  * target is a count. >= 0, not > 0: the largest-remainder phasing in
    hr/performance_engine.py legitimately assigns 0 to months a commitment
    does not land in, and the field's `default=0` means "no target set".
  * weight is a percent share that "must total 100 across active areas"
    (TargetArea's docstring). A negative weight would SUBTRACT an area's
    achievement from Overall Progress; one above 100 would let a single area
    outvote a full board.

TargetAdjustment carries the same two domains because it records
MonthlyPersonalTarget values either side of an audited change — if it
accepted less, a legal target would become an unrecordable adjustment.

WHY THE PRE-CHECK BELOW EXISTS
The development database is empty; production is not. A CHECK added over a
violating row surfaces as a raw Postgres `check constraint ... is violated by
some row` naming neither the row nor the column. The guard runs first, in the
same transaction, and names the table, the column, the count, an example id
and the SQL to list the rest. Nothing has been altered when it raises.
"""

from __future__ import annotations

from django.db import migrations, models
from django.db.models import Q

# (model, table, constraint, SQL rule rows must satisfy, column, Q selecting
# the rows that don't).
_SPECS = (
    (
        "MonthlyPersonalTarget",
        "monthly_personal_target",
        "monthly_personal_target_month_1_12",
        "month_of_fy BETWEEN 1 AND 12",
        "month_of_fy",
        ~Q(month_of_fy__gte=1) | ~Q(month_of_fy__lte=12),
    ),
    (
        "MonthlyPersonalTarget",
        "monthly_personal_target",
        "monthly_personal_target_non_negative",
        "target >= 0",
        "target",
        Q(target__lt=0),
    ),
    (
        "TargetAdjustment",
        "target_adjustment",
        "target_adjustment_values_non_negative",
        "old_target >= 0 AND new_target >= 0",
        "old_target / new_target",
        Q(old_target__lt=0) | Q(new_target__lt=0),
    ),
    (
        "TargetAdjustment",
        "target_adjustment",
        "target_adjustment_month_1_12",
        "month_of_fy BETWEEN 1 AND 12",
        "month_of_fy",
        ~Q(month_of_fy__gte=1) | ~Q(month_of_fy__lte=12),
    ),
    (
        "TargetArea",
        "target_area",
        "target_area_weight_0_100",
        "weight BETWEEN 0 AND 100",
        "weight",
        ~Q(weight__gte=0) | ~Q(weight__lte=100),
    ),
)


def check_target_domains(apps, schema_editor):
    """Refuse to apply the domains while any row already sits outside one."""
    for model_name, table, constraint, rule, column, violation in _SPECS:
        model = apps.get_model("targets", model_name)
        bad = model._base_manager.filter(violation).order_by()
        count = bad.count()
        if not count:
            continue
        example = bad.values_list("pk", flat=True).first()
        raise RuntimeError(
            f"\nMIGRATION ABORTED (INT-01) — cannot add {constraint}.\n"
            f"  Table   : {table}\n"
            f"  Column  : {column}\n"
            f"  Rule    : {rule}\n"
            f"  Rows    : {count} existing row(s) violate it\n"
            f"  Example : {table}.id = {example!r}\n"
            f"  List all: SELECT id, {column} FROM {table} "
            f"WHERE NOT ({rule});\n"
            f"Those rows are already invisible to the roll-ups that read "
            f"them. Correct them, then re-run the migration. No schema "
            f"change has been applied."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("targets", "0004_catchupplan"),
    ]

    operations = [
        # Runs before any DDL. Reverse is a no-op: dropping a constraint
        # cannot fail on data, so there is nothing to verify on the way back.
        migrations.RunPython(check_target_domains, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="monthlypersonaltarget",
            constraint=models.CheckConstraint(
                condition=models.Q(("month_of_fy__gte", 1), ("month_of_fy__lte", 12)),
                name="monthly_personal_target_month_1_12",
            ),
        ),
        migrations.AddConstraint(
            model_name="monthlypersonaltarget",
            constraint=models.CheckConstraint(
                condition=models.Q(("target__gte", 0)),
                name="monthly_personal_target_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="targetadjustment",
            constraint=models.CheckConstraint(
                condition=models.Q(("old_target__gte", 0), ("new_target__gte", 0)),
                name="target_adjustment_values_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="targetadjustment",
            constraint=models.CheckConstraint(
                condition=models.Q(("month_of_fy__gte", 1), ("month_of_fy__lte", 12)),
                name="target_adjustment_month_1_12",
            ),
        ),
        migrations.AddConstraint(
            model_name="targetarea",
            constraint=models.CheckConstraint(
                condition=models.Q(("weight__gte", 0), ("weight__lte", 100)),
                name="target_area_weight_0_100",
            ),
        ),
    ]
