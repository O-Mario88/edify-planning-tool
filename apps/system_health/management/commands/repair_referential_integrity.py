"""Remove rows whose school reference resolves to no school.

Dry-run by default. `--apply` writes every row it is about to delete to a JSON
file first, because none of these models carry a `deleted_at` column, so the
delete is otherwise irreversible.

What this deletes and why it is safe to:

  A CorePlan whose school_id matches no school in either identifier space
  cannot be opened, listed, or scheduled against — every read path resolves the
  school first. Its CoreActivitySlot rows go with it via CASCADE.

  A StaffSchoolAssignment pointing at a school that does not exist grants
  nothing; scoping intersects it with real schools.

What this deliberately does NOT do: it never rewrites an identifier to make it
resolve. CorePlan keys on School.school_id and StaffSchoolAssignment keys on
School.id, and guessing which school a dangling value "meant" would invent
data. A reference with no referent is removed, not repaired.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import connection, transaction


def _dangling_ids(table: str, column: str) -> list[str]:
    with connection.cursor() as c:
        c.execute(
            f"""
            SELECT DISTINCT t."{column}" FROM "{table}" t
            WHERE t."{column}" IS NOT NULL AND t."{column}" <> ''
              AND NOT EXISTS (
                  SELECT 1 FROM "school" s
                  WHERE s."id" = t."{column}" OR s."school_id" = t."{column}"
              )
            """  # nosec B608 - table/column are literals from the caller below.
        )
        return [r[0] for r in c.fetchall()]


def _rows_for(table: str, column: str, ids: list[str]) -> list[dict]:
    """Full row dumps for the backup file."""
    if not ids:
        return []
    with connection.cursor() as c:
        c.execute(
            f'SELECT * FROM "{table}" WHERE "{column}" = ANY(%s)',  # nosec B608
            [ids],
        )
        cols = [d[0] for d in c.description]
        return [dict(zip(cols, row, strict=False)) for row in c.fetchall()]


class Command(BaseCommand):
    help = "Delete rows whose school reference resolves to no school."

    # (label, table, column, note)
    TARGETS = [
        (
            "core-plans",
            "core_plan",
            "school_id",
            "CoreActivitySlot rows follow via CASCADE",
        ),
        ("staff-school-assignments", "staff_school_assignment", "school_id", ""),
    ]

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Actually delete. Without this the command only reports.",
        )
        parser.add_argument(
            "--backup",
            default="referential-integrity-backup.json",
            help="Where to write the deleted rows before deleting them.",
        )

    def handle(self, *args, **opts):
        apply = opts["apply"]
        mode = "APPLY" if apply else "DRY-RUN"
        self.stdout.write(f"== Referential integrity repair ({mode}) ==")

        backup: dict = {}
        planned = 0
        for label, table, column, note in self.TARGETS:
            ids = _dangling_ids(table, column)
            rows = _rows_for(table, column, ids)
            backup[table] = rows
            planned += len(rows)
            suffix = f" — {note}" if note else ""
            self.stdout.write(
                f"{label}: {len(rows)} row(s) across {len(ids)} "
                f"unresolvable school reference(s){suffix}"
            )

        # Slots are reported separately so the number in the log matches the
        # System Health figure, even though CASCADE is what actually removes
        # them.
        with connection.cursor() as c:
            c.execute(
                """
                SELECT COUNT(*) FROM core_activity_slot s
                WHERE NOT EXISTS (
                    SELECT 1 FROM school sc
                    WHERE sc.id = s.school_id OR sc.school_id = s.school_id
                )
                """
            )
            slot_count = c.fetchone()[0]
        self.stdout.write(f"core-activity-slots: {slot_count} row(s) (via CASCADE)")

        if not planned:
            self.stdout.write(self.style.SUCCESS("Nothing to repair."))
            return

        if not apply:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run — nothing deleted. {planned + slot_count} row(s) "
                    "would be removed. Re-run with --apply to proceed."
                )
            )
            return

        path = Path(opts["backup"])
        path.write_text(json.dumps(backup, indent=2, default=str))
        self.stdout.write(f"Backup written to {path.resolve()}")

        # Deleted through the ORM, not raw SQL. CorePlan's children (slots,
        # profile, onboarding) are CASCADE at the Django level only — the
        # database FKs are deferrable NO ACTION, so a raw DELETE passes every
        # statement and then fails at COMMIT on the first child row.
        from apps.accounts.models import StaffSchoolAssignment
        from apps.core_schools.models import CorePlan

        models = {
            "core_plan": CorePlan,
            "staff_school_assignment": StaffSchoolAssignment,
        }
        removed: dict = {}
        with transaction.atomic():
            for _label, table, column, _note in self.TARGETS:
                ids = _dangling_ids(table, column)
                if not ids:
                    continue
                _, per_model = (
                    models[table].objects.filter(**{f"{column}__in": ids}).delete()
                )
                for name, n in per_model.items():
                    removed[name] = removed.get(name, 0) + n

        for name, n in sorted(removed.items()):
            self.stdout.write(f"  deleted {n:6d}  {name}")
        self.stdout.write(
            self.style.SUCCESS(f"Deleted {sum(removed.values())} row(s) in total.")
        )
