"""Write golden.json: the Batch Payments Center (/accounts/batch-payments/) as
the existing feed reads it, over payments the development seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/golden.json \\
    python manage.py shell < platform/backend/internal/batchpayments/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gbp", copies of a seed staff visit: confirmed for an advance (at a
school, cluster-wide, with two confirmed advances, already paid, awaiting
confirmation), and partner work (verified and payable, verified and paid,
not yet verified), with their advance requests and budget lines. It asks the page of the
readers it serves with each tab, and of readers it refuses; writes the rows
and the answers to GOLDEN_OUT and deletes the rows.
internal/integration/batch_payments_test.go files the same rows and
compares.
"""

import json
import os
from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction

from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/accounts/batch-payments/"
TABLES = ("advance_request", "activity_schedule_cost_line", "activity")
BASE = datetime(2026, 11, 1, 9, tzinfo=timezone.utc)


def one(cursor, sql, args=()):
    cursor.execute(sql, args)
    row = cursor.fetchone()
    if row is None:
        raise SystemExit(f"golden.py: the seed lacks {sql}")
    return row[0]


def clone(cursor, table, base_id, overrides):
    cursor.execute(
        f'INSERT INTO "{table}" SELECT (json_populate_record(NULL::"{table}", '
        "(row_to_json(t)::jsonb || %s::jsonb)::json)).* "
        f'FROM "{table}" t WHERE id = %s',
        [json.dumps(overrides, default=str), base_id],
    )


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', ["gbp%"])


def file_rows():
    with connection.cursor() as cursor:
        visit = one(
            cursor,
            "SELECT a.id FROM activity a WHERE a.delivery_type = 'staff' "
            "AND a.activity_type = 'school_visit' AND a.deleted_at IS NULL "
            "AND a.school_id IS NOT NULL AND EXISTS (SELECT 1 FROM "
            "activity_schedule_cost_line l WHERE l.activity_id = a.id) "
            "ORDER BY a.id LIMIT 1",
        )
        line = one(
            cursor,
            "SELECT id FROM activity_schedule_cost_line WHERE activity_id = %s "
            "ORDER BY id LIMIT 1",
            [visit],
        )
        advance = one(cursor, "SELECT id FROM advance_request ORDER BY id LIMIT 1")
        partner = one(
            cursor,
            "SELECT id FROM partner WHERE deleted_at IS NULL ORDER BY id LIMIT 1",
        )
        staff = one(
            cursor,
            'SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id '
            "WHERE u.email = 'cceo2@edify.org'",
        )

        def activity(key, n, **fields):
            clone(
                cursor,
                "activity",
                visit,
                {
                    "id": key,
                    "est_cost_cents": 40000 + 1000 * n,
                    "created_at": (BASE + timedelta(hours=n)).isoformat(),
                    "updated_at": (BASE + timedelta(hours=n)).isoformat(),
                    "payment_status": "none",
                    **fields,
                },
            )

        def advance_for(key, activity_id, status):
            # One advance a budget line: each its own copy of the line.
            clone(
                cursor,
                "activity_schedule_cost_line",
                line,
                {
                    "id": key.replace("gbpR", "gbpL"),
                    "activity_id": activity_id,
                    "cost_setting_key": f"golden_{key}",
                },
            )
            clone(
                cursor,
                "advance_request",
                advance,
                {
                    "id": key,
                    "activity_id": activity_id,
                    "budget_line_id": key.replace("gbpR", "gbpL"),
                    "status": status,
                },
            )

        activity("gbpA1", 1)
        advance_for("gbpR1", "gbpA1", "confirmed_for_advance")
        activity(
            "gbpA2",
            2,
            school_id=None,
            cluster_id=None,
            responsible_staff_id=staff,
            activity_type="cluster_meeting",
        )
        advance_for("gbpR2", "gbpA2", "confirmed_for_advance")
        activity("gbpA3", 3, est_cost_cents=0)
        advance_for("gbpR3", "gbpA3", "confirmed_for_advance")
        advance_for("gbpR3b", "gbpA3", "confirmed_for_advance")
        activity("gbpA4", 4, payment_status="paid")
        advance_for("gbpR4", "gbpA4", "confirmed_for_advance")
        activity("gbpA5", 5)
        advance_for("gbpR5", "gbpA5", "pending_responsible_confirmation")
        activity("gbpA6", 6, deleted_at=BASE.isoformat())
        advance_for("gbpR6", "gbpA6", "confirmed_for_advance")
        partner_fields = {
            "delivery_type": "partner",
            "activity_type": "partner_activity",
            "assigned_partner_id": partner,
        }
        activity("gbpP1", 7, status="ia_verified", **partner_fields)
        activity(
            "gbpP2",
            8,
            status="ia_verified",
            payment_status="ia_confirmed",
            **partner_fields,
        )
        activity(
            "gbpP3", 9, status="ia_verified", payment_status="paid", **partner_fields
        )
        activity("gbpP4", 10, status="completed", **partner_fields)


def dump_rows():
    out = {}
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(
                f'SELECT row_to_json(t)::text FROM "{table}" t WHERE id LIKE %s ORDER BY id',
                ["gbp%"],
            )
            out[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return out


def ask(reader, query):
    with transaction.atomic():
        status, body = read_page(reader, PATH, query)
        transaction.set_rollback(True)
    return {
        "email": reader.email,
        "path": PATH,
        "query": query,
        "status": status,
        "body": body,
    }


clear()
answers = []
try:
    file_rows()
    rows = dump_rows()
    readers = {
        "accountant@edify.org": [{}, {"tab": "partners"}],
        "admin@edify.org": [{}],
        "ia@edify.org": [{}],
        "cceo@edify.org": [{}],
        "pl1@edify.org": [{}],
    }
    for email, queries in readers.items():
        reader = User.objects.get(email=email)
        for query in queries:
            answers.append(ask(reader, query))
finally:
    clear()
with open(os.environ["GOLDEN_OUT"], "w") as handle:
    json.dump(
        {"rows": rows, "answers": answers},
        handle,
        ensure_ascii=False,
        indent=1,
        default=str,
    )
print(f"{len(answers)} pages asked")
