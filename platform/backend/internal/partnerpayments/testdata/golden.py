"""Write golden.json: the Partner Payment Queue (/accounts/partner-payments/)
as the existing feed reads it, over partner work and invoices the
development seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/golden.json \\
    python manage.py shell < platform/backend/internal/partnerpayments/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gpp", copies of a seed staff visit made partner work: verified and
awaiting payment (at a school, with its 50% advance already paid, cluster-
wide with nobody responsible), verified and paid, and not yet verified, with
their cost lines and the advance payment; and partner invoices confirmed by
the Programme Lead (with and without the partner's document), and one still
with the Programme Lead. It asks the page of the readers it serves, and of
readers it refuses; writes the rows and the answers to GOLDEN_OUT and
deletes the rows. internal/integration/partner_payments_test.go files the
same rows and compares.
"""

import json
import os
from datetime import date, datetime, timedelta, timezone

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction

from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/accounts/partner-payments/"
TABLES = (
    "partner_invoice_item",
    "partner_invoice",
    "partner_payment",
    "activity_schedule_cost_line",
    "activity",
)
BASE = datetime(2026, 11, 2, 9, tzinfo=timezone.utc)


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


def insert(cursor, table, row):
    cols = ", ".join(f'"{c}"' for c in row)
    marks = ", ".join(["%s"] * len(row))
    cursor.execute(
        f'INSERT INTO "{table}" ({cols}) VALUES ({marks})', list(row.values())
    )


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', ["gpp%"])


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
        partners = []
        cursor.execute(
            "SELECT id FROM partner WHERE deleted_at IS NULL ORDER BY id LIMIT 2"
        )
        partners = [r[0] for r in cursor.fetchall()]
        while len(partners) < 2:
            partners.append(partners[-1])

        def activity(key, n, costs, **fields):
            when = (BASE + timedelta(days=n)).isoformat()
            clone(
                cursor,
                "activity",
                visit,
                {
                    "id": key,
                    "title": f"Golden partner work {n}",
                    "delivery_type": "partner",
                    "activity_type": "partner_activity",
                    "assigned_partner_id": partners[n % 2],
                    "status": "ia_verified",
                    "payment_status": "none",
                    "scheduled_date": when,
                    "created_at": when,
                    "updated_at": when,
                    **fields,
                },
            )
            for i, amount in enumerate(costs):
                clone(
                    cursor,
                    "activity_schedule_cost_line",
                    line,
                    {
                        "id": f"gppL{key[4:]}{i}",
                        "activity_id": key,
                        "cost_setting_key": f"golden_{key}_{i}",
                        "amount": amount,
                    },
                )

        activity("gppA1", 1, [60000, 15000])
        activity("gppA2", 2, [80000], payment_status="disbursed")
        activity(
            "gppA3",
            3,
            [50000],
            payment_status="ia_confirmed",
            school_id=None,
            cluster_id=None,
            responsible_staff_id="gpp-nobody",
        )
        activity("gppA4", 4, [90000], payment_status="paid")
        activity("gppA5", 5, [70000], status="scheduled")
        activity("gppA6", 6, [], payment_status="none")
        insert(
            cursor,
            "partner_payment",
            {
                "id": "gppPay1",
                "created_at": BASE,
                "updated_at": BASE,
                "partner_name": "Golden partner",
                "amount_paid": 30000,
                "payment_method": "Bank Transfer",
                "payment_reference": "GOLD-1",
                "payment_date": BASE,
                "paid_by": "golden",
                "notes": None,
                "activity_id": "gppA2",
                "payment_type": "advance",
            },
        )
        submitter = User.objects.get(email="partner@edify.org").id

        def invoice(key, n, status, stored, items):
            insert(
                cursor,
                "partner_invoice",
                {
                    "id": key,
                    "created_at": BASE + timedelta(hours=n),
                    "updated_at": BASE + timedelta(hours=n),
                    "partner_id": partners[n % 2],
                    "invoice_type": "clearance" if n % 2 else "advance",
                    "period_kind": "month",
                    "period_start": date(2026, 10, 1),
                    "period_end": date(2026, 10, 31),
                    "system_total": 120000 + n,
                    "entered_total": 125000 + n,
                    "payable_amount": 62500 + n,
                    "stored_name": stored,
                    "original_name": "invoice.pdf",
                    "mime_type": "application/pdf",
                    "file_size": 1000,
                    "status": status,
                    "submitted_by": submitter,
                    "pl_confirmed_by": None,
                    "pl_confirmed_at": None,
                    "pl_note": "",
                    "program_lead_staff_id": None,
                },
            )
            for i, act in enumerate(items):
                insert(
                    cursor,
                    "partner_invoice_item",
                    {
                        "id": f"{key}i{i}",
                        "created_at": BASE,
                        "updated_at": BASE,
                        "instalment": "advance",
                        "planned_amount": 1000,
                        "payable_amount": 500,
                        "category": "general",
                        "activity_id": act,
                        "invoice_id": key,
                        "payment_id": None,
                    },
                )

        invoice("gppI1", 2, "confirmed_by_pl", "invoices/gppI1.pdf", ["gppA1"])
        invoice("gppI2", 1, "confirmed_by_pl", "", ["gppA2", "gppA6"])
        invoice("gppI3", 3, "submitted_to_pl", "invoices/gppI3.pdf", ["gppA3"])


def dump_rows():
    out = {}
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(
                f'SELECT row_to_json(t)::text FROM "{table}" t WHERE id LIKE %s ORDER BY id',
                ["gpp%"],
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
        "accountant@edify.org": [{}],
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
