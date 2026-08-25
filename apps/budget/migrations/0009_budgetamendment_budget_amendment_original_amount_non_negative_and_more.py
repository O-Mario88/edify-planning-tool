"""INT-01: money floors on the cost spine.

apps/budget declared two unique constraints and ZERO check constraints, so a
negative rate was a legal row on the rate card that every activity cost in
the platform is multiplied out of.

>= 0 rather than > 0 on all five columns, and the reason is the same one each
time: apps/budget/costing.py distinguishes a MISSING rate (None — the
activity is flagged costMissing and blocked from funding entirely) from a
rate of zero, which is a real priced "no charge" line. A `> 0` floor would
reject a rate the costing engine is built to accept, and would reject the
`default=0` that BudgetAmendment.original_amount already ships.

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
# the rows that don't). A `__lt` lookup never matches NULL, which is what
# keeps the nullable old_unit_cost out of the check for free.
_SPECS = (
    (
        "BudgetAmendment",
        "budget_amendment",
        "budget_amendment_original_amount_non_negative",
        "original_amount >= 0",
        "original_amount",
        Q(original_amount__lt=0),
    ),
    (
        "CostSetting",
        "cost_setting",
        "cost_setting_unit_cost_non_negative",
        "unit_cost >= 0",
        "unit_cost",
        Q(unit_cost__lt=0),
    ),
    (
        "CostSettingHistory",
        "cost_setting_history",
        "cost_setting_history_new_unit_cost_non_negative",
        "new_unit_cost >= 0",
        "new_unit_cost",
        Q(new_unit_cost__lt=0),
    ),
    (
        "CostSettingHistory",
        "cost_setting_history",
        "cost_setting_history_old_unit_cost_non_negative",
        "old_unit_cost IS NULL OR old_unit_cost >= 0",
        "old_unit_cost",
        Q(old_unit_cost__lt=0),
    ),
    (
        "MonthlyFundRequest",
        "monthly_fund_request",
        "monthly_fund_request_amount_non_negative",
        "amount >= 0",
        "amount",
        Q(amount__lt=0),
    ),
)


def check_money_floors(apps, schema_editor):
    """Refuse to apply the floors while any row already breaks one.

    `_base_manager`, not `objects`: a soft-delete default manager would hide
    exactly the tombstoned rows that would still fail the DDL.
    """
    for model_name, table, constraint, rule, column, violation in _SPECS:
        model = apps.get_model("budget", model_name)
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
            f"Correct those rows (they price work at a negative amount), "
            f"then re-run the migration. No schema change has been applied."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("activities", "0048_backfill_cluster_attendance"),
        ("budget", "0008_consolidate_cost_setting_registry"),
    ]

    operations = [
        # Runs before any DDL. Reverse is a no-op: dropping a constraint
        # cannot fail on data, so there is nothing to verify on the way back.
        migrations.RunPython(check_money_floors, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="budgetamendment",
            constraint=models.CheckConstraint(
                condition=models.Q(("original_amount__gte", 0)),
                name="budget_amendment_original_amount_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="costsetting",
            constraint=models.CheckConstraint(
                condition=models.Q(("unit_cost__gte", 0)),
                name="cost_setting_unit_cost_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="costsettinghistory",
            constraint=models.CheckConstraint(
                condition=models.Q(("new_unit_cost__gte", 0)),
                name="cost_setting_history_new_unit_cost_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="costsettinghistory",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("old_unit_cost__isnull", True),
                    ("old_unit_cost__gte", 0),
                    _connector="OR",
                ),
                name="cost_setting_history_old_unit_cost_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="monthlyfundrequest",
            constraint=models.CheckConstraint(
                condition=models.Q(("amount__gte", 0)),
                name="monthly_fund_request_amount_non_negative",
            ),
        ),
    ]
