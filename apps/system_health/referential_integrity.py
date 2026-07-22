"""Detect references to schools and staff that no longer resolve.

Several tables carry a school or staff identifier in a plain CharField rather
than a ForeignKey. That was a deliberate call — CorePlan keys on the school's
business key (School.school_id) rather than its primary key, and
Activity.responsible_staff_id holds either a StaffProfile id or a User id — but
the cost is that the database cannot reject a dangling reference. Nothing has
ever noticed one either, so a row pointing at a school that was never imported
looks exactly like a row pointing at a real one until a page tries to render it.

This module is the missing detection. It is read-only and reports counts; the
repair lives in `manage.py repair_referential_integrity`, which is dry-run by
default.

A note on identifier spaces, because it is easy to "fix" this the wrong way:

  CorePlan.school_id and CoreActivitySlot.school_id hold School.school_id (the
  business key, e.g. "S-1042"), NOT School.id. apps/planning/checks.py looks
  plans up by `school.school_id`, and that is the contract. Rewriting these to
  primary keys would break every existing lookup.

  StaffSchoolAssignment.school_id holds School.id (the cuid primary key).

So a reference is only dangling if it resolves in neither space.
"""

from __future__ import annotations

from django.db import connection

# (label, table, column, human description of what the column should hold)
_SCHOOL_REFS = [
    ("corePlan", "core_plan", "school_id", "School.school_id (business key)"),
    (
        "coreActivitySlot",
        "core_activity_slot",
        "school_id",
        "School.school_id (business key)",
    ),
    (
        "staffSchoolAssignment",
        "staff_school_assignment",
        "school_id",
        "School.id (primary key)",
    ),
    ("activity", "activity", "school_id", "School.id (primary key)"),
    ("ssaRecord", "ssa_record", "school_id", "School.id (primary key)"),
]


def _count_dangling(table: str, column: str) -> tuple[int, int]:
    """(dangling rows, distinct dangling identifiers) for one table/column.

    Accepts a match in EITHER identifier space. A row is only counted when the
    value resolves to no school at all — this check exists to find references
    with no referent, not to police which identifier a table chose.
    """
    with connection.cursor() as c:
        c.execute(
            f"""
            SELECT COUNT(*), COUNT(DISTINCT t."{column}")
            FROM "{table}" t
            WHERE t."{column}" IS NOT NULL
              AND t."{column}" <> ''
              AND NOT EXISTS (
                  SELECT 1 FROM "school" s
                  WHERE s."id" = t."{column}" OR s."school_id" = t."{column}"
              )
            """  # nosec B608 - table/column come from _SCHOOL_REFS above.
        )
        rows, distinct = c.fetchone()
    return rows or 0, distinct or 0


def _table_exists(table: str) -> bool:
    with connection.cursor() as c:
        c.execute("SELECT to_regclass(%s)", [f"public.{table}"])
        return c.fetchone()[0] is not None


def dangling_school_references() -> dict:
    """Report every table holding school references that resolve to nothing."""
    checks = []
    total = 0
    for label, table, column, expects in _SCHOOL_REFS:
        if not _table_exists(table):
            continue
        rows, distinct = _count_dangling(table, column)
        total += rows
        checks.append(
            {
                "key": label,
                "table": table,
                "column": column,
                "expects": expects,
                "danglingRows": rows,
                "danglingIds": distinct,
                "clean": rows == 0,
            }
        )
    return {
        "clean": total == 0,
        "totalDanglingRows": total,
        "checks": checks,
    }


def referential_integrity() -> dict:
    """Entry point for the System Health report."""
    try:
        return dangling_school_references()
    except Exception as exc:  # noqa: BLE001 — the health page must render regardless
        return {
            "clean": None,
            "totalDanglingRows": None,
            "checks": [],
            "error": str(exc),
        }
