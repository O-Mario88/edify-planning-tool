"""Write golden.json: the Fund Disbursement Dashboard (/disbursements) as the
existing feed reads it, over money the development seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/golden.json \\
    python manage.py shell < platform/backend/internal/disbursements/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gdb", copies of stored activities and their cost lines planned
this November; monthly fund plans in each queue state (a draft left out, a
Special Project plan, one disbursed today, one returned, one closed, one
from October); weekly advances in each state (one with accountability
waiting, one not requested, one from October); the advance ledger behind
the month's figures (a held plan's line, a reimbursement claim); partner
work verified and awaiting payment (and some already paid); and a partner
payment. Every money-moving time sits a minute before the file is written,
so the answers hold for half an hour. It asks the page of the Accountant
and the Admin with each filter, each item and other months and years, and
of readers it refuses (and, before filing anything, of a month whose queue
is empty), writes the rows and the answers to GOLDEN_OUT and deletes the
rows. internal/integration/disbursements_test.go files the
same rows and compares.
"""

import json
import os
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone as dj_timezone

from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/disbursements"
NOW = dj_timezone.now()
JUST_NOW = NOW - timedelta(minutes=1)
TABLES = (
    "partner_payment",
    "advance_request",
    "weekly_fund_request_line",
    "weekly_fund_request",
    "fund_request_item",
    "fund_request",
    "activity_schedule_cost_line",
    "activity",
)


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"DELETE FROM {table} WHERE id LIKE 'gdb%%'")


def clone(cursor, table, base_id, overrides):
    cursor.execute(
        f'INSERT INTO "{table}" SELECT (json_populate_record(NULL::"{table}", '
        "(row_to_json(t)::jsonb || %s::jsonb)::json)).* "
        f'FROM "{table}" t WHERE id = %s',
        [json.dumps(overrides, default=str), base_id],
    )


def insert(cursor, table, row):
    """File one row through its model, so the model's defaults apply, then
    stamp its times."""
    from django.apps import apps

    model = next(m for m in apps.get_models() if m._meta.db_table == table)
    data = dict(row)
    created = data.pop("created_at", JUST_NOW)
    model.objects.create(**data)
    cursor.execute(
        f'UPDATE "{table}" SET created_at = %s, updated_at = %s WHERE id = %s',
        [created, JUST_NOW, data["id"]],
    )


def file_rows():
    with connection.cursor() as cursor:

        def one(sql, args=()):
            cursor.execute(sql, args)
            row = cursor.fetchone()
            return row[0] if row else None

        def user(email):
            return one('SELECT id FROM "user" WHERE email = %s', [email])

        cceo, cceo1, coordinator = (
            user("cceo@edify.org"),
            user("cceo1@edify.org"),
            user("coordinator@edify.org"),
        )
        # One plan an owner a month, and one advance an owner a week.
        other = {k: user(f"cceo{k}@edify.org") for k in (2, 3, 10, 11, 12, 13)}
        partner = one("SELECT id FROM partner ORDER BY id LIMIT 1")

        def base(activity_type, delivery_type):
            return one(
                "SELECT a.id FROM activity a WHERE a.activity_type = %s AND a.delivery_type = %s "
                "AND a.deleted_at IS NULL AND EXISTS (SELECT 1 FROM activity_schedule_cost_line l "
                "WHERE l.activity_id = a.id) ORDER BY a.id LIMIT 1",
                [activity_type, delivery_type],
            )

        lines = {}
        n = 0

        def activity(key, activity_type, delivery_type, day, **fields):
            nonlocal n
            src = base(activity_type, delivery_type)
            new = f"gdbA{key}"
            clone(
                cursor,
                "activity",
                src,
                {
                    "id": new,
                    "fy": "2027",
                    "quarter": "Q2",
                    "planned_month": 11,
                    "status": "scheduled",
                    "planned_date": f"2026-11-{day:02d}T09:00:00+03:00",
                    "scheduled_date": f"2026-11-{day:02d}T09:00:00+03:00",
                    "paired_school_visit_id": None,
                    "daily_visit_batch_id": None,
                    "created_at": (JUST_NOW - timedelta(days=int(key))).isoformat(),
                    **fields,
                },
            )
            cursor.execute(
                "SELECT id FROM activity_schedule_cost_line WHERE activity_id = %s ORDER BY id",
                [src],
            )
            ids = []
            for (line_id,) in cursor.fetchall():
                n += 1
                lid = f"gdbL{n:03d}"
                clone(
                    cursor,
                    "activity_schedule_cost_line",
                    line_id,
                    {
                        "id": lid,
                        "activity_id": new,
                        "fiscal_year": "2027",
                        "month": 11,
                        "quarter": "Q2",
                        "planned_date": f"2026-11-{day:02d}",
                    },
                )
                ids.append(lid)
            lines[key] = ids
            return new

        activity("01", "school_visit", "staff", 4)
        activity("02", "cluster_meeting", "staff", 5)
        activity("03", "ssa_activity", "staff", 6)
        activity("04", "cluster_meeting", "staff", 12)
        activity("05", "school_visit", "staff", 13)
        activity("06", "school_visit", "staff", 14, status="cancelled")
        partner_visit = activity(
            "07",
            "school_visit",
            "partner",
            9,
            status="ia_verified",
            payment_status="none",
            assigned_partner_id=partner,
            salesforce_activity_id="SF-GDB-07",
        )
        activity(
            "08",
            "partner_activity",
            "partner",
            10,
            status="ia_verified",
            payment_status="ia_confirmed",
            assigned_partner_id=partner,
            salesforce_activity_id=None,
        )
        activity(
            "09",
            "school_visit",
            "partner",
            11,
            status="ia_verified",
            payment_status="paid",
            assigned_partner_id=partner,
        )
        october = activity("10", "school_visit", "staff", 20, planned_month=10)
        cursor.execute(
            "UPDATE activity_schedule_cost_line SET month = 10, planned_date = '2026-10-20' "
            "WHERE activity_id = %s",
            [october],
        )

        def amount(*keys):
            cursor.execute(
                "SELECT COALESCE(SUM(amount), 0) FROM activity_schedule_cost_line WHERE id = ANY(%s)",
                [[lid for k in keys for lid in lines[k]]],
            )
            return cursor.fetchone()[0]

        def plan(key, status, owner, role, keys, month=11, **fields):
            fid = f"gdbF{key}"
            ids = [lid for k in keys for lid in lines[k]]
            insert(
                cursor,
                "fund_request",
                {
                    "id": fid,
                    "fy": "2027",
                    "period": "monthly",
                    "period_key": f"2027-M{month}",
                    "scope": "own",
                    "submitted_by_user_id": owner,
                    "submitted_by_role": role,
                    "total_amount": amount(*keys) + int(key),
                    "activity_count": len(keys),
                    "status": status,
                    **fields,
                },
            )
            for i, lid in enumerate(ids):
                cursor.execute(
                    "SELECT activity_id, amount FROM activity_schedule_cost_line WHERE id = %s",
                    [lid],
                )
                act, amt = cursor.fetchone()
                insert(
                    cursor,
                    "fund_request_item",
                    {
                        "id": f"gdbI{key}{i:02d}",
                        "activity_id": act,
                        "activity_schedule_cost_line_id": lid,
                        "amount": amt,
                        "period": "monthly",
                        "period_key": f"2027-M{month}",
                        "added_after_generation": False,
                        "fund_request_id": fid,
                    },
                )

        def days_ago(d):
            return JUST_NOW - timedelta(days=d)

        plan("01", "sent_to_accountant", cceo1, "CCEO", ["01", "02"])
        plan("02", "submitted_to_pl", coordinator, "ProjectCoordinator", ["04"])
        plan(
            "03",
            "held",
            cceo,
            "CCEO",
            ["05"],
            held_at=days_ago(1),
            held_reason="Cash not available",
        )
        plan(
            "04",
            "disbursed",
            other[2],
            "CCEO",
            ["02"],
            disbursed_at=JUST_NOW,
            disbursed_amount=150000,
            disburse_method="Mobile Money",
            disburse_reference="MM-77",
            accountability_submitted_at=JUST_NOW,
        )
        plan("05", "disbursed", other[3], "CCEO", ["03"], disbursed_at=days_ago(9))
        plan(
            "06",
            "returned_by_accountant",
            other[10],
            "CCEO",
            ["01"],
            reviewed_at=days_ago(2),
            review_note="Amount mismatch",
        )
        plan("07", "closed", other[11], "CCEO", ["03"])
        plan("08", "draft", other[12], "CCEO", ["01"])
        plan(
            "09",
            "disbursed",
            other[13],
            "ProjectCoordinator",
            ["10"],
            month=10,
            disbursed_at=days_ago(30),
            accountability_submitted_at=days_ago(20),
            accountability_netsuite_id="NS-9",
            accountability_reviewed_at=days_ago(10),
        )

        def week(key, status, owner, start, keys, **fields):
            wid = f"gdbW{key}"
            ids = [lid for k in keys for lid in lines[k]]
            insert(
                cursor,
                "weekly_fund_request",
                {
                    "id": wid,
                    "fy": "2027",
                    "week_start_date": start,
                    "week_end_date": start + timedelta(days=6),
                    "responsible_user": owner,
                    "responsible_role": "CCEO",
                    "total_amount": amount(*keys) + 100 * int(key),
                    "status": status,
                    "funding_source": "advance",
                    **fields,
                },
            )
            for i, lid in enumerate(ids):
                cursor.execute(
                    "SELECT COALESCE(line_item_type, cost_setting_key), label, quantity, unit_cost, amount "
                    "FROM activity_schedule_cost_line WHERE id = %s",
                    [lid],
                )
                kind, label, qty, unit, amt = cursor.fetchone()
                insert(
                    cursor,
                    "weekly_fund_request_line",
                    {
                        "id": f"gdbS{key}{i:02d}",
                        "line_item_type": kind,
                        "description": f"{label} (week {key})",
                        "quantity": qty + 1,
                        "unit_cost": unit,
                        "total_cost": amt + 1000,
                        "currency": "UGX",
                        "activity_budget_line_id": lid,
                        "weekly_fund_request_id": wid,
                    },
                )
            return ids

        week(
            "01",
            "confirmed_for_advance",
            cceo,
            date(2026, 11, 2),
            ["03"],
            confirmed_at=days_ago(3),
        )
        w2 = week(
            "02",
            "disbursed",
            cceo1,
            date(2026, 11, 9),
            ["02"],
            disbursed_at=days_ago(4),
            disbursed_amount=90000,
        )
        week("03", "accounted", other[2], date(2026, 11, 2), ["01"])
        week(
            "04",
            "returned_by_accountant",
            cceo1,
            date(2026, 11, 16),
            ["05"],
            returned_at=days_ago(1),
        )
        week("05", "not_requested", cceo, date(2026, 11, 16), ["04"])
        week(
            "06",
            "pending_responsible_confirmation",
            coordinator,
            date(2026, 11, 23),
            ["04"],
        )
        week("07", "confirmed_for_advance", cceo, date(2026, 10, 19), ["10"])

        def advance(key, line_id, status, **fields):
            cursor.execute(
                "SELECT activity_id, amount, responsible_user FROM activity_schedule_cost_line WHERE id = %s",
                [line_id],
            )
            act, amt, owner = cursor.fetchone()
            insert(
                cursor,
                "advance_request",
                {
                    "id": f"gdbR{key}",
                    "responsible_user_id": fields.pop("owner", owner),
                    "fy": "2027",
                    "quarter": "Q2",
                    "month": fields.pop("month", 11),
                    "amount": amt,
                    "status": status,
                    "advance_type": "activity",
                    "activity_id": act,
                    "budget_line_id": line_id,
                    "created_at": JUST_NOW - timedelta(hours=int(key)),
                    **fields,
                },
            )

        advance("01", lines["01"][0], "draft_from_schedule")
        advance("02", lines["01"][1], "returned", last_note="Wrong period")
        advance("03", lines["05"][0], "confirmed_for_advance")
        advance(
            "04",
            w2[0],
            "accountability_pending",
            disbursed_amount=40000,
            accounted_amount=35000,
            returned_amount=5000,
            accountability_netsuite_id="NS-204",
            accountability_submitted_at=days_ago(1),
            last_note="Fewer participants came",
        )
        advance(
            "05",
            lines["02"][1],
            "accounted",
            disbursed_amount=20000,
            accounted_amount=18000,
            accountability_reviewed_at=days_ago(1),
        )
        advance(
            "06",
            lines["03"][0],
            "reimbursement_submitted",
            owner=cceo1,
            accounted_amount=47000,
            accountability_submitted_at=days_ago(2),
        )
        advance("07", lines["04"][0], "pending_responsible_confirmation")
        advance("08", lines["10"][0], "disbursed", month=10, disbursed_amount=5)

        insert(
            cursor,
            "partner_payment",
            {
                "id": "gdbP01",
                "partner_name": "Literacy Uganda",
                "amount_paid": 310000,
                "payment_method": "Bank Transfer",
                "payment_reference": "BT-1",
                "payment_date": days_ago(3),
                "paid_by": cceo,
                "activity_id": partner_visit,
                "payment_type": "partner",
            },
        )


def dump_rows():
    out = {}
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM {table} t WHERE id LIKE 'gdb%%' ORDER BY id"
            )
            out[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return out


def item_keys():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT 'fr:' || id FROM fund_request WHERE id LIKE 'gdb%%' "
            "UNION ALL SELECT 'wfr:' || id FROM weekly_fund_request WHERE id LIKE 'gdb%%' "
            "UNION ALL SELECT 'act:' || id FROM activity WHERE id LIKE 'gdb%%' "
            "UNION ALL SELECT 'adv:' || id FROM advance_request WHERE id LIKE 'gdb%%' ORDER BY 1"
        )
        return [r[0] for r in cursor.fetchall()]


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
# Asked before any row is filed: a month with nothing in its queue.
accountant = User.objects.get(email="accountant@edify.org")
empty_answers = [ask(accountant, q) for q in ({}, {"fy": "2026", "month": "5"})]
try:
    file_rows()
    rows = dump_rows()
    asked = [{}]
    asked += [{"item": key} for key in item_keys()]
    asked += [{"item": "fr:nobody"}]
    asked += [
        {"status": s}
        for s in (
            "Pending Approval",
            "Pending Disbursement",
            "Held",
            "Disbursed",
            "Awaiting Reconciliation",
            "Returned",
            "Closed",
            "Nothing",
        )
    ]
    asked += [
        {"status": "Returned", "item": "fr:gdbF01"},
        {"q": "paul"},
        {"q": "special"},
        {"q": "nov 2"},
        {"q": "zzz"},
        {"month": "10"},
        {"month": "12"},
        {"fy": "2026"},
        {"fy": "2026", "month": "4"},
        {"fy": "2026", "month": "3", "status": "Pending Approval"},
        {"fy": "2025"},
        {"fy": "2028", "month": "1"},
    ]
    readers = {
        "accountant@edify.org": asked,
        "admin@edify.org": [{}, {"item": "wfr:gdbW02"}],
        "pl1@edify.org": [{}],
        "cceo@edify.org": [{}],
        "cd@edify.org": [{}],
    }
    for email, qs in readers.items():
        reader = User.objects.get(email=email)
        for query in qs:
            answers.append(ask(reader, query))
finally:
    clear()
with open(os.environ["GOLDEN_OUT"], "w") as handle:
    json.dump(
        {
            "today": dj_timezone.localdate().isoformat(),
            "written": NOW.isoformat(),
            "rows": rows,
            "answers": answers,
            "empty_answers": empty_answers,
        },
        handle,
        ensure_ascii=False,
        indent=1,
        default=str,
    )
print(f"{len(answers)} pages asked")
