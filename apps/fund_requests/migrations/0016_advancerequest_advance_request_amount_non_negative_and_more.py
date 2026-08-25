"""INT-01 + INTG-07: money floors and NetSuite-Code uniqueness for the
fund-request tables.

Four tables in this app carried unique constraints and ZERO check
constraints, so Postgres accepted a negative disbursement on any of the three
channels money leaves through (period, weekly, per-line advance). Every
service that writes them bounds them; a management command, a data repair or
an import does not. The floors below are the boundary those services already
enforce, restated where nothing can route around it.

INTG-07 adds the partial unique index on AdvanceRequest
.accountability_netsuite_id, so one NetSuite expense reference can clear one
advance and not an unlimited number of them.

WHY THE PRE-CHECK BELOW EXISTS
The development database is empty; production is not, and neither is
staging. Adding a CHECK to a table with a violating row surfaces as a raw
Postgres `check constraint ... is violated by some row` with no id, no count
and no column — an operator gets a failed deploy and a guessing game. The
RunPython guard runs first, inside the same transaction, and turns that into
a named table, a named column, a row count, an example id and the exact SQL
to list the rest. Nothing has been altered when it raises.
"""

from __future__ import annotations

from django.db import migrations, models
from django.db.models import Count, Q

# (model, table, constraint, SQL rule the rows must satisfy, column, Q that
# selects the rows that DON'T). A `__lt` lookup never matches NULL, which is
# what makes the nullable settlement columns fall out of the check for free.
_SPECS = (
    (
        "FundRequest",
        "fund_request",
        "fund_request_total_amount_non_negative",
        "total_amount >= 0",
        "total_amount",
        Q(total_amount__lt=0),
    ),
    (
        "FundRequest",
        "fund_request",
        "fund_request_disbursed_amount_non_negative",
        "disbursed_amount IS NULL OR disbursed_amount >= 0",
        "disbursed_amount",
        Q(disbursed_amount__lt=0),
    ),
    (
        "FundRequest",
        "fund_request",
        "fund_request_accounted_amount_non_negative",
        "accounted_amount IS NULL OR accounted_amount >= 0",
        "accounted_amount",
        Q(accounted_amount__lt=0),
    ),
    (
        "FundRequest",
        "fund_request",
        "fund_request_returned_amount_non_negative",
        "returned_amount IS NULL OR returned_amount >= 0",
        "returned_amount",
        Q(returned_amount__lt=0),
    ),
    (
        "FundRequestItem",
        "fund_request_item",
        "fund_request_item_amount_non_negative",
        "amount >= 0",
        "amount",
        Q(amount__lt=0),
    ),
    (
        "AdvanceRequest",
        "advance_request",
        "advance_request_amount_non_negative",
        "amount >= 0",
        "amount",
        Q(amount__lt=0),
    ),
    (
        "AdvanceRequest",
        "advance_request",
        "advance_request_disbursed_amount_non_negative",
        "disbursed_amount IS NULL OR disbursed_amount >= 0",
        "disbursed_amount",
        Q(disbursed_amount__lt=0),
    ),
    (
        "AdvanceRequest",
        "advance_request",
        "advance_request_accounted_amount_non_negative",
        "accounted_amount IS NULL OR accounted_amount >= 0",
        "accounted_amount",
        Q(accounted_amount__lt=0),
    ),
    (
        "AdvanceRequest",
        "advance_request",
        "advance_request_returned_amount_non_negative",
        "returned_amount IS NULL OR returned_amount >= 0",
        "returned_amount",
        Q(returned_amount__lt=0),
    ),
    # The one > 0 floor in this migration. advance_service.reimburse() pays
    # only when the amount due is strictly positive and the payout equals it
    # exactly, so a stored 0 records a payment that never happened.
    (
        "AdvanceRequest",
        "advance_request",
        "advance_request_reimbursed_amount_positive",
        "reimbursed_amount IS NULL OR reimbursed_amount > 0",
        "reimbursed_amount",
        Q(reimbursed_amount__lte=0),
    ),
    (
        "WeeklyFundRequest",
        "weekly_fund_request",
        "weekly_fund_request_total_amount_non_negative",
        "total_amount >= 0",
        "total_amount",
        Q(total_amount__lt=0),
    ),
    (
        "WeeklyFundRequest",
        "weekly_fund_request",
        "weekly_fund_request_disbursed_amount_non_negative",
        "disbursed_amount IS NULL OR disbursed_amount >= 0",
        "disbursed_amount",
        Q(disbursed_amount__lt=0),
    ),
    (
        "WeeklyFundRequest",
        "weekly_fund_request",
        "weekly_fund_request_accounted_amount_non_negative",
        "accounted_amount IS NULL OR accounted_amount >= 0",
        "accounted_amount",
        Q(accounted_amount__lt=0),
    ),
    (
        "WeeklyFundRequest",
        "weekly_fund_request",
        "weekly_fund_request_returned_amount_non_negative",
        "returned_amount IS NULL OR returned_amount >= 0",
        "returned_amount",
        Q(returned_amount__lt=0),
    ),
)


def check_money_floors(apps, schema_editor):
    """Refuse to apply the floors while any row already breaks one.

    `_base_manager`, not `objects`: a soft-delete default manager would hide
    exactly the tombstoned rows that would still fail the DDL.
    """
    for model_name, table, constraint, rule, column, violation in _SPECS:
        model = apps.get_model("fund_requests", model_name)
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
            f"Correct those rows (they record money that cannot exist), then "
            f"re-run the migration. No schema change has been applied."
        )


def check_netsuite_ids_unique(apps, schema_editor):
    """Refuse to apply the partial unique index while a code is shared.

    Matches the index predicate exactly — non-null and non-blank — so it
    cannot pass a case the index would then reject.
    """
    model = apps.get_model("fund_requests", "AdvanceRequest")
    shared = (
        model._base_manager.exclude(accountability_netsuite_id__isnull=True)
        .exclude(accountability_netsuite_id="")
        .values("accountability_netsuite_id")
        # order_by() clears AdvanceRequest.Meta.ordering — otherwise
        # created_at joins the GROUP BY and every row becomes its own group.
        .order_by()
        .annotate(rows=Count("id"))
        .filter(rows__gt=1)
    )
    count = shared.count()
    if not count:
        return
    worst = shared.order_by("-rows").first()
    code = worst["accountability_netsuite_id"]
    example = (
        model._base_manager.filter(accountability_netsuite_id=code)
        .order_by()
        .values_list("pk", flat=True)
        .first()
    )
    raise RuntimeError(
        f"\nMIGRATION ABORTED (INTG-07) — cannot add "
        f"uniq_advance_accountability_netsuite_id.\n"
        f"  Table   : advance_request\n"
        f"  Column  : accountability_netsuite_id\n"
        f"  Rule    : a NetSuite Code clears at most one advance\n"
        f"  Rows    : {count} NetSuite Code(s) are shared by more than one "
        f"advance\n"
        f"  Example : code {code!r} is on {worst['rows']} advances, "
        f"e.g. advance_request.id = {example!r}\n"
        f"  List all: SELECT accountability_netsuite_id, count(*), "
        f"array_agg(id) FROM advance_request\n"
        f"            WHERE accountability_netsuite_id IS NOT NULL "
        f"AND accountability_netsuite_id <> ''\n"
        f"            GROUP BY 1 HAVING count(*) > 1;\n"
        f"Each of those advances needs its own expense reference, or the "
        f"duplicates must be cleared to NULL. Finance clearance currently "
        f"treats every one of them as accounted for. No schema change has "
        f"been applied."
    )


class Migration(migrations.Migration):
    dependencies = [
        ("fund_requests", "0015_partnerinvoice_partnerinvoiceitem"),
    ]

    operations = [
        # Both guards run before any DDL. Reverse is a no-op: dropping a
        # constraint cannot fail on data, so there is nothing to verify on
        # the way back.
        migrations.RunPython(check_money_floors, migrations.RunPython.noop),
        migrations.RunPython(check_netsuite_ids_unique, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="advancerequest",
            constraint=models.CheckConstraint(
                condition=models.Q(("amount__gte", 0)),
                name="advance_request_amount_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="advancerequest",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("disbursed_amount__isnull", True),
                    ("disbursed_amount__gte", 0),
                    _connector="OR",
                ),
                name="advance_request_disbursed_amount_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="advancerequest",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("accounted_amount__isnull", True),
                    ("accounted_amount__gte", 0),
                    _connector="OR",
                ),
                name="advance_request_accounted_amount_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="advancerequest",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("returned_amount__isnull", True),
                    ("returned_amount__gte", 0),
                    _connector="OR",
                ),
                name="advance_request_returned_amount_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="advancerequest",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("reimbursed_amount__isnull", True),
                    ("reimbursed_amount__gt", 0),
                    _connector="OR",
                ),
                name="advance_request_reimbursed_amount_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="advancerequest",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("accountability_netsuite_id__isnull", False),
                    models.Q(("accountability_netsuite_id", ""), _negated=True),
                ),
                fields=("accountability_netsuite_id",),
                name="uniq_advance_accountability_netsuite_id",
            ),
        ),
        migrations.AddConstraint(
            model_name="fundrequest",
            constraint=models.CheckConstraint(
                condition=models.Q(("total_amount__gte", 0)),
                name="fund_request_total_amount_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="fundrequest",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("disbursed_amount__isnull", True),
                    ("disbursed_amount__gte", 0),
                    _connector="OR",
                ),
                name="fund_request_disbursed_amount_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="fundrequest",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("accounted_amount__isnull", True),
                    ("accounted_amount__gte", 0),
                    _connector="OR",
                ),
                name="fund_request_accounted_amount_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="fundrequest",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("returned_amount__isnull", True),
                    ("returned_amount__gte", 0),
                    _connector="OR",
                ),
                name="fund_request_returned_amount_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="fundrequestitem",
            constraint=models.CheckConstraint(
                condition=models.Q(("amount__gte", 0)),
                name="fund_request_item_amount_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="weeklyfundrequest",
            constraint=models.CheckConstraint(
                condition=models.Q(("total_amount__gte", 0)),
                name="weekly_fund_request_total_amount_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="weeklyfundrequest",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("disbursed_amount__isnull", True),
                    ("disbursed_amount__gte", 0),
                    _connector="OR",
                ),
                name="weekly_fund_request_disbursed_amount_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="weeklyfundrequest",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("accounted_amount__isnull", True),
                    ("accounted_amount__gte", 0),
                    _connector="OR",
                ),
                name="weekly_fund_request_accounted_amount_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="weeklyfundrequest",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("returned_amount__isnull", True),
                    ("returned_amount__gte", 0),
                    _connector="OR",
                ),
                name="weekly_fund_request_returned_amount_non_negative",
            ),
        ),
    ]
