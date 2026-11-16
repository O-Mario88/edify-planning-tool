"""Write pricing_oracle.json: every live activity priced as the existing single
cost writer prices it (apps.activities.services._costing_input, then
apps.budget.costing_service.calculate_dual), for Go's internal/pricing to
price the same way.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    ORACLE_OUT=/path/to/pricing_oracle.json \\
    python manage.py shell < platform/backend/internal/pricing/testdata/oracle.py

Only against a database whose name ends in "_test". It files, every id
starting "gpr", copies of the published operational card's rows: a newer
operational card in force from 10 to 20 April 2026 only (with a
material-difference threshold, one rate below its approved minimum, one rate
left out, and a cost linked to one governed activity), and a published
regional reference card with dearer rates (one left out). It prices every
live activity, writes the rows and the answers to ORACLE_OUT and deletes the
rows. internal/integration/pricing_oracle_test.go files the same rows and
prices each activity with Go.
"""

import json
import os

from django.conf import settings
from django.db import connection
from django.utils import timezone as dj_timezone

from apps.activities.models import Activity
from apps.activities.services import _costing_input
from apps.budget.costing_service import active_catalogue, calculate_dual
from apps.core.exceptions import BadRequest

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("oracle.py runs only against a _test database")

#: Children first.
TABLES = ("cost_setting", "cost_catalogue")


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"DELETE FROM \"{table}\" WHERE id LIKE 'gpr%%'")  # noqa: S608  # nosec B608


def clone(cursor, table, base_id, overrides):
    cursor.execute(
        f'INSERT INTO "{table}" SELECT (json_populate_record(NULL::"{table}", '  # noqa: S608  # nosec B608
        f'(row_to_json(t)::jsonb || %s::jsonb)::json)).* FROM "{table}" t WHERE id = %s',
        [json.dumps(overrides), base_id],
    )


def file_rows():
    live = active_catalogue()
    if live is None:
        raise SystemExit("no published operational card on this database")
    with connection.cursor() as cursor:
        clone(
            cursor,
            "cost_catalogue",
            live.id,
            {
                "id": "gprcop",
                "fy": "2028",
                "version": 1,
                "effective_from": "2026-04-10",
                "effective_to": "2026-04-20",
                "material_difference_threshold_bps": 500,
            },
        )
        clone(
            cursor,
            "cost_catalogue",
            live.id,
            {
                "id": "gprcref",
                "kind": "reference",
                "fy": "2027",
                "version": 9,
                "effective_from": None,
                "effective_to": None,
            },
        )
        cursor.execute(
            "SELECT id, key FROM cost_setting WHERE catalogue_id = %s ORDER BY key, id",
            [live.id],
        )
        rows = cursor.fetchall()
        cursor.execute(
            "SELECT id FROM activity_catalogue_item WHERE status = 'active' ORDER BY display_name, id LIMIT 1"
        )
        item = cursor.fetchone()[0]
        for n, (setting_id, key) in enumerate(rows):
            if key != "lunch_per_day":
                op = {"id": f"gprsop{n:03d}", "catalogue_id": "gprcop"}
                if key == "primary_transport_per_day":
                    op.update(unit_cost=55000, approved_minimum=60000)
                clone(cursor, "cost_setting", setting_id, op)
            if key != "group_training_venue_cost":
                cursor.execute(
                    "SELECT unit_cost FROM cost_setting WHERE id = %s", [setting_id]
                )
                unit = cursor.fetchone()[0] or 0
                clone(
                    cursor,
                    "cost_setting",
                    setting_id,
                    {
                        "id": f"gprsref{n:03d}",
                        "catalogue_id": "gprcref",
                        "unit_cost": unit * 2 + 1000,
                    },
                )
        cursor.execute(
            """INSERT INTO cost_setting (id, created_at, updated_at, key, label, unit_cost, version, unit,
               catalogue_id, catalogue_item_id)
               VALUES ('gprslink', now(), now(), 'activity:gpr:snacks', 'Golden snacks', 7000, 1, 'per day',
                       'gprcop', %s)""",
            [item],
        )


def dump_rows():
    rows = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM \"{table}\" t WHERE id LIKE 'gpr%%' ORDER BY id"  # noqa: S608  # nosec B608
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


def priced(cost):
    if cost is None:
        return None
    return {
        "amount": int(cost.amount),
        "cost_missing": cost.cost_missing,
        "missing_items": list(cost.missing_items),
        "lines": [
            {
                "label": line.label,
                "key": line.key,
                "unit": line.unit,
                "qty": line.qty,
                "amount": line.amount,
                "missing": line.missing,
            }
            for line in cost.lines
        ],
    }


def answer(activity):
    try:
        dual = calculate_dual(_costing_input(activity, {}))
    except BadRequest as exc:
        return {"id": activity.id, "error": str(exc)}
    return {
        "id": activity.id,
        "operational": priced(dual["operational"]),
        "reference": priced(dual["reference"]),
        "warnings": dual["warnings"],
        "missing": dual["missingConfiguration"],
        "viability": dual["viability"],
        "canSchedule": dual["canSchedule"],
        "cards": [
            dual["operationalCard"].id if dual["operationalCard"] else None,
            dual["referenceCard"].id if dual["referenceCard"] else None,
        ],
    }


def main():
    clear()
    try:
        file_rows()
        rows = dump_rows()
        answers = [
            answer(activity)
            for activity in Activity.objects.filter(deleted_at__isnull=True).order_by(
                "id"
            )
        ]
    finally:
        clear()
    with open(os.environ["ORACLE_OUT"], "w") as handle:
        json.dump(
            {
                "today": dj_timezone.localdate().isoformat(),
                "rows": rows,
                "activities": answers,
            },
            handle,
            ensure_ascii=False,
            default=str,
        )
    print(f"{len(answers)} activities priced")


main()
