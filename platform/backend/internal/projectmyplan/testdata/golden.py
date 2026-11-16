"""Write golden.json: the Special Projects My Plan (/projects/my-plan) as the
existing feed reads it, over project work the development seed does not
hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/golden.json \\
    python manage.py shell < platform/backend/internal/projectmyplan/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gsp", copies of seed work made project work this week and month:
the coordinator's own school visit, training and cluster meeting, a visit
someone else runs, partner work assigned and verified, work returned,
rescheduled, overdue, completed without accepted evidence and awaiting IA,
one cancelled, one in another year, with cost lines and an advance for some.
It asks the page of the coordinator with each period, project, status,
search and partner, and of the readers it serves and refuses; writes the
rows and the answers to GOLDEN_OUT and deletes the rows. Dates sit around
the day it was written, so internal/integration/project_my_plan_test.go
compares within half an hour.
"""

import json
import os
from datetime import datetime, time, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone as dj_timezone

from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/projects/my-plan"
TABLES = ("advance_request", "activity_schedule_cost_line", "activity")
TODAY = dj_timezone.localdate()
NOW = dj_timezone.now()
ZONE = dj_timezone.get_current_timezone()


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
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', ["gsp%"])


def at(day):
    return datetime.combine(day, time(9), tzinfo=ZONE).isoformat()


def file_rows():
    with connection.cursor() as cursor:

        def base(kind, delivery):
            return one(
                cursor,
                "SELECT id FROM activity WHERE activity_type = %s AND delivery_type = %s "
                "AND deleted_at IS NULL ORDER BY id LIMIT 1",
                [kind, delivery],
            )

        visit = base("school_visit", "staff")
        meeting = base("cluster_meeting", "staff")
        partner_work = base("partner_activity", "partner")
        line = one(
            cursor,
            "SELECT id FROM activity_schedule_cost_line WHERE activity_id = %s "
            "ORDER BY id LIMIT 1",
            [visit],
        )
        advance = one(cursor, "SELECT id FROM advance_request ORDER BY id LIMIT 1")
        projects = []
        cursor.execute(
            "SELECT id FROM project WHERE deleted_at IS NULL ORDER BY name LIMIT 2"
        )
        projects = [r[0] for r in cursor.fetchall()]
        coordinator = one(
            cursor,
            'SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id '
            "WHERE u.email = 'coordinator@edify.org'",
        )
        other = one(
            cursor,
            'SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id '
            "WHERE u.email = 'cceo4@edify.org'",
        )
        partner = one(
            cursor,
            "SELECT id FROM partner WHERE deleted_at IS NULL ORDER BY id LIMIT 1",
        )
        fy = str(TODAY.year + 1 if TODAY.month >= 10 else TODAY.year)
        n = {"i": 0}

        def work(src, key, day, **fields):
            n["i"] += 1
            when = at(day)
            clone(
                cursor,
                "activity",
                src,
                {
                    "id": key,
                    "fy": fy,
                    "fiscal_year": fy,
                    "project_id": projects[0],
                    "responsible_staff_id": coordinator,
                    "status": "scheduled",
                    "planned_date": when,
                    "scheduled_date": when,
                    "planned_date_before_completion": None,
                    "actual_delivery_date": None,
                    "reschedule_count": 0,
                    "evidence_status": "none",
                    "activity_purpose_text": f"Golden project purpose {n['i']:02d} "
                    "that runs past the fifty-two character cut on the table",
                    "paired_school_visit_id": None,
                    "daily_visit_batch_id": None,
                    "created_at": (NOW - timedelta(hours=40 - n["i"])).isoformat(),
                    **fields,
                },
            )

        work(visit, "gspV1", TODAY)
        work(visit, "gspV2", TODAY + timedelta(days=1), status="returned_by_pl")
        work(visit, "gspV3", TODAY, responsible_staff_id=other)
        work(visit, "gspV4", TODAY + timedelta(days=2), reschedule_count=2)
        work(
            visit,
            "gspV5",
            TODAY,
            status="completed",
            evidence_status="uploaded",
            actual_delivery_date=at(TODAY),
            planned_date_before_completion=at(TODAY + timedelta(days=3)),
        )
        work(visit, "gspV6", TODAY, status="awaiting_ia_verification")
        work(visit, "gspV7", TODAY - timedelta(days=20), status="scheduled")
        work(visit, "gspV8", TODAY, status="cancelled")
        work(
            visit,
            "gspV9",
            TODAY,
            fy=str(int(fy) - 1),
            fiscal_year=str(int(fy) - 1),
        )
        work(
            visit,
            "gspT1",
            TODAY + timedelta(days=1),
            activity_type="in_school_training",
            teachers_attended=12,
            leaders_attended=3,
            focus_intervention="literacy",
            project_id=projects[-1],
        )
        work(meeting, "gspM1", TODAY + timedelta(days=2))
        work(
            partner_work,
            "gspP1",
            TODAY,
            status="assigned_to_partner",
            assigned_partner_id=partner,
        )
        work(
            partner_work,
            "gspP2",
            TODAY + timedelta(days=1),
            status="ia_verified",
            evidence_status="accepted",
            assigned_partner_id=partner,
        )
        for i, (activity, status) in enumerate(
            (
                ("gspV1", "confirmed_for_advance"),
                ("gspV2", "pending_responsible_confirmation"),
                ("gspV5", "disbursed"),
            )
        ):
            clone(
                cursor,
                "activity_schedule_cost_line",
                line,
                {
                    "id": f"gspL{i}",
                    "activity_id": activity,
                    "cost_setting_key": f"golden_gspL{i}",
                },
            )
            clone(
                cursor,
                "advance_request",
                advance,
                {
                    "id": f"gspR{i}",
                    "activity_id": activity,
                    "budget_line_id": f"gspL{i}",
                    "status": status,
                },
            )
        clone(
            cursor,
            "activity_schedule_cost_line",
            line,
            {"id": "gspL9", "activity_id": "gspT1", "cost_setting_key": "golden_gspL9"},
        )
        return {"projects": projects, "partner": partner, "fy": fy}


def dump_rows():
    out = {}
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(
                f'SELECT row_to_json(t)::text FROM "{table}" t WHERE id LIKE %s ORDER BY id',
                ["gsp%"],
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
    filed = file_rows()
    rows = dump_rows()
    coordinator_asks = [
        {},
        {"period": "month"},
        {"period": "quarter"},
        {"period": "fy"},
        {"period": "fy", "project": filed["projects"][0]},
        {"period": "month", "status": "returned"},
        {"period": "month", "status": "review"},
        {"period": "month", "status": "cancelled"},
        {"period": "month", "q": "golden project purpose 01"},
        {"period": "month", "partner": filed["partner"]},
        {"period": "month", "activity_type": "school_visit"},
        {"q": "nothing matches this"},
        {"fy": str(int(filed["fy"]) - 1)},
    ]
    readers = {
        "coordinator@edify.org": coordinator_asks,
        "admin@edify.org": [{}, {"period": "month"}],
        "cd@edify.org": [{"period": "month"}],
        "pl1@edify.org": [{}],
        "cceo1@edify.org": [{}],
        "accountant@edify.org": [{}],
        "partner@edify.org": [{}],
    }
    for email, queries in readers.items():
        reader = User.objects.get(email=email)
        for query in queries:
            answers.append(ask(reader, query))
finally:
    clear()
with open(os.environ["GOLDEN_OUT"], "w") as handle:
    json.dump(
        {
            "today": TODAY.isoformat(),
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
