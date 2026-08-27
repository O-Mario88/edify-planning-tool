"""INT-02: one active TemporaryCoverageAssignment per leave request, and a
coverage window that runs forwards.

The model's Meta contained only db_table. "One active assignment" was held up
by a revoke-then-create pair under a row lock in one code path
(apps/hr/leave_services.py), so any other writer could hand a second person
the same absent employee's authority — and every authority check downstream
returns EVERY match rather than picking one.

On the choice of key, see the model comment: `is_live` warns that nothing
ever writes status="expired", so a partial index on status="active" is only
safe for a key that cannot recur. leave_request cannot; original_staff can,
and would have refused a legitimate new delegation because of one from years
ago. The per-person overlap rule that WOULD need original_staff is already
closed upstream by the overlapping-leave guard in leave_services, and stating
it here would need a GiST exclusion constraint over a tstzrange — which means
CREATE EXTENSION btree_gist at migrate time, a privilege a managed-Postgres
role may not hold. This migration deliberately requires no extension.

WHY THE PRE-CHECK BELOW EXISTS
The development database is empty. Production is not, and the state this
constraint forbids is one production has had no defence against. Adding the
index to a table that already holds two active assignments for one leave
surfaces as a bare `could not create unique index ... Key (leave_request_id)
is duplicated` — no count, no list, no idea which leave. The guard runs
first, in the same transaction, and names the leave, the count and the SQL to
find the rest. Nothing has been altered when it raises.
"""

from __future__ import annotations

from django.db import migrations, models
from django.db.models import Count, F, Q


def check_one_active_coverage_per_leave(apps, schema_editor):
    """Refuse the index while any leave request has two active coverages."""
    model = apps.get_model("accounts", "TemporaryCoverageAssignment")
    clashes = (
        model._base_manager.filter(status="active")
        .values("leave_request_id")
        # order_by() clears any Meta ordering so it cannot join the GROUP BY.
        .order_by()
        .annotate(rows=Count("id"))
        .filter(rows__gt=1)
    )
    count = clashes.count()
    if not count:
        return
    worst = clashes.order_by("-rows").first()
    leave_id = worst["leave_request_id"]
    example = (
        model._base_manager.filter(leave_request_id=leave_id, status="active")
        .order_by()
        .values_list("pk", flat=True)
        .first()
    )
    raise RuntimeError(
        f"\nMIGRATION ABORTED (INT-02) — cannot add "
        f"uniq_active_coverage_per_leave_request.\n"
        f"  Table   : temporary_coverage_assignment\n"
        f"  Column  : leave_request_id (where status = 'active')\n"
        f"  Rule    : a leave request has at most one active coverage\n"
        f"  Rows    : {count} leave request(s) carry more than one\n"
        f"  Example : leave_request_id = {leave_id!r} has {worst['rows']} "
        f"active coverages, e.g. temporary_coverage_assignment.id = "
        f"{example!r}\n"
        f"  List all: SELECT leave_request_id, count(*), array_agg(id)\n"
        f"            FROM temporary_coverage_assignment WHERE status = "
        f"'active'\n"
        f"            GROUP BY 1 HAVING count(*) > 1;\n"
        f"Each of those leaves has delegated one person's authority to two "
        f"people at once. Revoke the superseded assignment (set status = "
        f"'revoked' with revoked_at/revoked_by_user_id) — keeping the one "
        f"the covering employee actually accepted — then re-run the "
        f"migration. No schema change has been applied."
    )


def check_coverage_windows_ordered(apps, schema_editor):
    """Refuse the check constraint while any window runs backwards."""
    model = apps.get_model("accounts", "TemporaryCoverageAssignment")
    bad = model._base_manager.filter(end_datetime__lt=F("start_datetime")).order_by()
    count = bad.count()
    if not count:
        return
    example = bad.values_list("pk", flat=True).first()
    raise RuntimeError(
        f"\nMIGRATION ABORTED (INT-02) — cannot add coverage_window_ordered.\n"
        f"  Table   : temporary_coverage_assignment\n"
        f"  Column  : start_datetime / end_datetime\n"
        f"  Rule    : end_datetime >= start_datetime\n"
        f"  Rows    : {count} existing row(s) violate it\n"
        f"  Example : temporary_coverage_assignment.id = {example!r}\n"
        f"  List all: SELECT id, leave_request_id, start_datetime, "
        f"end_datetime\n"
        f"            FROM temporary_coverage_assignment\n"
        f"            WHERE end_datetime < start_datetime;\n"
        f"Those delegations can never be live (every authority check tests "
        f"start <= now <= end), so they grant nothing while appearing on the "
        f"coverage pages. Correct the dates from the leave request they "
        f"belong to, then re-run the migration. No schema change has been "
        f"applied."
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0023_leave_attachment_private_storage"),
    ]

    operations = [
        # Both guards run before any DDL. Reverse is a no-op: dropping a
        # constraint cannot fail on data, so there is nothing to verify on
        # the way back.
        migrations.RunPython(
            check_one_active_coverage_per_leave, migrations.RunPython.noop
        ),
        migrations.RunPython(check_coverage_windows_ordered, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="temporarycoverageassignment",
            constraint=models.UniqueConstraint(
                condition=Q(("status", "active")),
                fields=("leave_request",),
                name="uniq_active_coverage_per_leave_request",
            ),
        ),
        migrations.AddConstraint(
            model_name="temporarycoverageassignment",
            constraint=models.CheckConstraint(
                condition=Q(("end_datetime__gte", F("start_datetime"))),
                name="coverage_window_ordered",
            ),
        ),
    ]
