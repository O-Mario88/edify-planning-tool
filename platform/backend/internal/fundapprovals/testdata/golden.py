"""Write golden.json: Fund Approvals (/fund-approvals) as the existing feed
reads it, over a team's week of fund plans the development seed does not
hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/golden.json \\
    python manage.py shell < platform/backend/internal/fundapprovals/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gfa", copies of stored activities and their cost lines for the
first Program Lead's five officers in the weeks of 23 and 30 November
(partner-delivered work, provider-paid transport and accommodation, a
multi-day meeting, work with no cost rate, a cancelled visit), each
officer's weekly request in its own state (awaiting the Lead, awaiting with
an issue, at the Accountant, returned, not yet sent, disbursed), the Lead's
own request waiting on the Country Director, and the audit rows of an
approval today and a return yesterday. Every time sits a minute before the
file is written, so the answers hold for half an hour. It asks the page of
the Lead with each filter, officer, sort and week, of the Country Director
and the Admin, and of readers it refuses; writes the rows and the answers
to GOLDEN_OUT and deletes the rows. internal/integration/
fund_approvals_test.go files the same rows and compares.
"""

import json
import os
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone as dj_timezone

from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/fund-approvals"
NOW = dj_timezone.now()
JUST_NOW = NOW - timedelta(minutes=1)
WEEK = date(2026, 11, 23)
NEXT_WEEK = date(2026, 11, 30)
TABLES = (
    "audit_log",
    "weekly_fund_request_line",
    "weekly_fund_request",
    "activity_schedule_cost_line",
    "activity",
)


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"DELETE FROM {table} WHERE id LIKE 'gfa%%'")


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
    if table == "audit_log":
        cursor.execute(
            f'UPDATE "{table}" SET created_at = %s WHERE id = %s', [created, data["id"]]
        )
    else:
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

        def officer(email):
            cursor.execute(
                'SELECT sp.id, u.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id WHERE u.email = %s',
                [email],
            )
            return cursor.fetchone()

        def base(activity_type, delivery_type):
            return one(
                "SELECT a.id FROM activity a WHERE a.activity_type = %s AND a.delivery_type = %s "
                "AND a.deleted_at IS NULL AND EXISTS (SELECT 1 FROM activity_schedule_cost_line l "
                "WHERE l.activity_id = a.id) ORDER BY a.id LIMIT 1",
                [activity_type, delivery_type],
            )

        # One school an officer, from different districts where the seed has
        # them, so each officer's district is the one all their work is in.
        cursor.execute(
            "SELECT DISTINCT ON (district_id) id FROM school WHERE deleted_at IS NULL "
            "AND district_id IS NOT NULL AND region_id IS NOT NULL ORDER BY district_id, id LIMIT 5"
        )
        spread = [r[0] for r in cursor.fetchall()]
        while len(spread) < 5:
            spread.append(spread[-1])
        team = {
            "a": officer("cceo@edify.org"),
            "b": officer("cceo8@edify.org"),
            "c": officer("cceo4@edify.org"),
            "d": officer("cceo12@edify.org"),
            "e": officer("cceo16@edify.org"),
            "lead": officer("pl1@edify.org"),
        }
        n = {"act": 0, "line": 0}
        made = {}

        def activity(owner, activity_type, delivery, day, school, **fields):
            n["act"] += 1
            key = f"gfaA{n['act']:02d}"
            src = base(activity_type, delivery)
            planned = datetime.combine(day, time(9)).isoformat() + "+03:00"
            line_fields = fields.pop("line_fields", {})
            clone(
                cursor,
                "activity",
                src,
                {
                    "id": key,
                    "fy": "2027",
                    "quarter": "Q2",
                    "planned_month": day.month,
                    "status": "scheduled",
                    "planned_date": planned,
                    "scheduled_date": planned,
                    "end_date": None,
                    "responsible_staff_id": team[owner][0],
                    "school_id": school,
                    "paired_school_visit_id": None,
                    "daily_visit_batch_id": None,
                    "cost_missing": False,
                    "created_at": JUST_NOW.isoformat(),
                    **fields,
                },
            )
            cursor.execute(
                "SELECT id FROM activity_schedule_cost_line WHERE activity_id = %s ORDER BY id",
                [src],
            )
            week = day - timedelta(days=day.weekday())
            ids = []
            for i, (line_id,) in enumerate(cursor.fetchall()):
                n["line"] += 1
                lid = f"gfaL{n['line']:03d}"
                clone(
                    cursor,
                    "activity_schedule_cost_line",
                    line_id,
                    {
                        "id": lid,
                        "activity_id": key,
                        "fiscal_year": "2027",
                        "month": day.month,
                        "quarter": "Q2",
                        "planned_date": day.isoformat(),
                        "week_start_date": week.isoformat(),
                        "week_end_date": (week + timedelta(days=6)).isoformat(),
                        "responsible_user": team[owner][1],
                        **line_fields.get(i, {}),
                    },
                )
                ids.append(lid)
            made.setdefault(owner, {}).setdefault(week, []).extend(ids)
            return key

        def two_days(day):
            end = datetime.combine(day + timedelta(days=1), time(17))
            return end.isoformat() + "+03:00"

        a, b, c, d, e = spread[:5]
        # Officer a: a visit (provider-paid transport), a two-day meeting, an
        # SSA visit, partner-delivered work and a cancelled visit.
        activity("a", "school_visit", "staff", WEEK + timedelta(days=1), a)
        activity(
            "a",
            "cluster_meeting",
            "staff",
            WEEK + timedelta(days=2),
            a,
            end_date=two_days(WEEK + timedelta(days=2)),
        )
        activity("a", "ssa_activity", "staff", WEEK + timedelta(days=3), a)
        activity("a", "school_visit", "partner", WEEK + timedelta(days=4), a)
        activity(
            "a",
            "school_visit",
            "staff",
            WEEK + timedelta(days=4),
            a,
            status="cancelled",
        )
        # Officer b: a visit with no cost rate, and a meeting whose hotel
        # Finance booked.
        activity(
            "b", "school_visit", "staff", WEEK + timedelta(days=1), b, cost_missing=True
        )
        activity(
            "b",
            "cluster_meeting",
            "staff",
            WEEK + timedelta(days=2),
            b,
            line_fields={1: {"line_item_type": "accommodation", "vendor_paid": True}},
        )
        activity("c", "cluster_meeting", "staff", WEEK + timedelta(days=1), c)
        activity("c", "ssa_activity", "staff", WEEK + timedelta(days=2), c)
        activity("d", "school_visit", "staff", WEEK + timedelta(days=2), d)
        # A second visit, so the month's visits never cost the same as its
        # SSA visits: two categories that tie are listed in whatever order
        # the database returns their cost lines, on either page.
        activity("d", "school_visit", "staff", WEEK + timedelta(days=2), c)
        activity("e", "ssa_activity", "staff", WEEK + timedelta(days=3), e)
        activity("e", "cluster_meeting", "staff", NEXT_WEEK + timedelta(days=1), e)
        activity("a", "ssa_activity", "staff", NEXT_WEEK + timedelta(days=2), a)
        # The Lead's own work, waiting on the Country Director.
        activity("lead", "cluster_meeting", "staff", WEEK + timedelta(days=2), d)

        def request(key, owner, week, status, **fields):
            wid = f"gfaW{key}"
            cursor.execute(
                "SELECT l.id, COALESCE(l.line_item_type, l.cost_setting_key), l.label, l.quantity, "
                "l.unit_cost, l.amount FROM activity_schedule_cost_line l "
                "JOIN activity a ON a.id = l.activity_id WHERE l.id = ANY(%s) "
                "AND a.delivery_type <> 'partner' AND a.status <> 'cancelled' ORDER BY l.id",
                [made[owner][week]],
            )
            snapshot = cursor.fetchall()
            insert(
                cursor,
                "weekly_fund_request",
                {
                    "id": wid,
                    "fy": "2027",
                    "week_start_date": week,
                    "week_end_date": week + timedelta(days=6),
                    "responsible_user": team[owner][1],
                    "responsible_role": "CCEO",
                    "total_amount": sum(r[5] for r in snapshot) + int(key),
                    "status": status,
                    "funding_source": "advance",
                    **fields,
                },
            )
            for i, (lid, kind, label, qty, unit, amount) in enumerate(snapshot):
                insert(
                    cursor,
                    "weekly_fund_request_line",
                    {
                        "id": f"gfaS{key}{i:02d}",
                        "line_item_type": kind,
                        "description": label,
                        "quantity": qty,
                        "unit_cost": unit,
                        "total_cost": amount,
                        "currency": "UGX",
                        "activity_budget_line_id": lid,
                        "weekly_fund_request_id": wid,
                    },
                )
            return wid

        request("01", "a", WEEK, "submitted_to_pl")
        request("02", "b", WEEK, "submitted_to_pl")
        approved = request("03", "c", WEEK, "confirmed_for_advance")
        sent_back = request(
            "04", "d", WEEK, "returned_by_pl", return_reason="Wrong week"
        )
        request("05", "e", WEEK, "pending_responsible_confirmation")
        request(
            "06",
            "e",
            NEXT_WEEK,
            "disbursed",
            disbursed_at=JUST_NOW - timedelta(days=1),
        )
        request("07", "a", NEXT_WEEK, "submitted_to_pl")
        request("08", "lead", WEEK, "submitted_to_cd")

        lead_user = team["lead"][1]
        for key, action, subject, success, at in (
            ("01", "weekly_fund_request.approve", approved, True, JUST_NOW),
            (
                "02",
                "weekly_fund_request.return",
                sent_back,
                True,
                JUST_NOW - timedelta(days=1),
            ),
            (
                "03",
                "weekly_fund_request.approve",
                approved,
                False,
                JUST_NOW - timedelta(days=3),
            ),
        ):
            insert(
                cursor,
                "audit_log",
                {
                    "id": f"gfaU{key}",
                    "action": action,
                    "subject_kind": "WeeklyFundRequest",
                    "subject_id": subject,
                    "actor_id": lead_user,
                    "success": success,
                    "created_at": at,
                },
            )
        return team


def dump_rows():
    out = {}
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM {table} t WHERE id LIKE 'gfa%%' ORDER BY id"
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
    team = file_rows()
    rows = dump_rows()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT d.name, r.name FROM activity a JOIN school s ON s.id = a.school_id "
            "JOIN district d ON d.id = s.district_id JOIN region r ON r.id = s.region_id "
            "WHERE a.id = 'gfaA01'"
        )
        district, region = cursor.fetchone()
    asked = [{}]
    asked += [{"cceo": team[k][1]} for k in ("a", "b", "c", "d", "e")]
    asked += [{"cceo": "nobody"}]
    asked += [
        {"status": s}
        for s in (
            "Awaiting CCEO Send",
            "Awaiting Approval",
            "Needs Review",
            "At Accountant",
            "Disbursed",
            "Returned",
            "Nothing",
        )
    ]
    asked += [
        {"sort": "name"},
        {"sort": "status"},
        {"sort": "bogus"},
        {"q": "paul"},
        {"q": district[:4]},
        {"q": "zzz"},
        {"district": district},
        {"region": region},
        {"week": NEXT_WEEK.isoformat()},
        {"week": "2026-12-02"},
        {"week": "bogus"},
        {"month": "11"},
        {"month": "12"},
        {"month": "12", "week": WEEK.isoformat()},
        # The seed's own weeks are not asked: their officers' totals tie,
        # and a tie falls to the database's unordered row order, which the
        # other integration tests move between the golden and the asking.
        {"fy": "2028"},
    ]
    readers = {
        "pl1@edify.org": asked,
        "cd@edify.org": [{}, {"week": WEEK.isoformat()}],
        "admin@edify.org": [{"week": WEEK.isoformat()}],
        "cceo@edify.org": [{}],
        "accountant@edify.org": [{}],
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
        },
        handle,
        ensure_ascii=False,
        indent=1,
        default=str,
    )
print(f"{len(answers)} pages asked")
