"""Write golden.json: the Special Projects Planning (/projects/planning) as
the existing feed reads it, over project work the development seed does not
hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/golden.json \\
    python manage.py shell < platform/backend/internal/projectplanning/testdata/golden.py

Only against a database whose name ends in "_test". Over the seed's 25
school–project pairs it files, every id starting "gpl", this quarter's
project work at some of them (a staff visit this week, partner work
assigned, work returned, overdue and rescheduled work, a cancelled visit, a
training with a cost line) and a handover a partner has not dated. It asks
the page of the coordinator on each tab, page size, page, selection,
project, delivery and activity type, search and quarter, and of the readers
it serves and refuses; writes the rows and the answers to GOLDEN_OUT and
deletes the rows. Dates sit around the day it was written, so
internal/integration/project_planning_test.go compares within half an hour.
"""

import json
import os
from datetime import datetime, time, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone as dj_timezone

from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/projects/planning"
TABLES = ("activity_schedule_cost_line", "partner_assignment", "activity")
TODAY = dj_timezone.localdate()
NOW = dj_timezone.now()
ZONE = dj_timezone.get_current_timezone()
FY = str(get_operational_fy(TODAY))
QUARTER = get_quarter_for_date(TODAY)


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
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', ["gpl%"])


def at(day):
    return datetime.combine(day, time(9), tzinfo=ZONE).isoformat()


def file_rows():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT psa.id, psa.project_id, psa.school_id FROM project_school_assignment psa "
            "JOIN project p ON p.id = psa.project_id ORDER BY p.name, psa.id"
        )
        pairs = cursor.fetchall()
        if len(pairs) < 12:
            raise SystemExit("golden.py: the seed lacks project schools")
        visit = one(
            cursor,
            "SELECT id FROM activity WHERE activity_type = 'school_visit' AND "
            "delivery_type = 'staff' AND deleted_at IS NULL ORDER BY id LIMIT 1",
        )
        partner_work = one(
            cursor,
            "SELECT id FROM activity WHERE activity_type = 'partner_activity' AND "
            "delivery_type = 'partner' AND deleted_at IS NULL ORDER BY id LIMIT 1",
        )
        line = one(
            cursor,
            "SELECT id FROM activity_schedule_cost_line ORDER BY id LIMIT 1",
        )
        handover = one(cursor, "SELECT id FROM partner_assignment ORDER BY id LIMIT 1")
        partner = one(
            cursor,
            "SELECT id FROM partner WHERE deleted_at IS NULL ORDER BY id LIMIT 1",
        )
        n = {"i": 0}

        def work(src, key, pair, day, **fields):
            n["i"] += 1
            clone(
                cursor,
                "activity",
                src,
                {
                    "id": key,
                    "fy": FY,
                    "fiscal_year": FY,
                    "quarter": QUARTER,
                    "project_id": pair[1],
                    "school_id": pair[2],
                    "status": "scheduled",
                    "planned_date": at(day),
                    "scheduled_date": at(day),
                    "reschedule_count": 0,
                    "paired_school_visit_id": None,
                    "daily_visit_batch_id": None,
                    "ssa_collection_expected": False,
                    "created_at": (NOW - timedelta(hours=30 - n["i"])).isoformat(),
                    **fields,
                },
            )

        work(visit, "gplA1", pairs[0], TODAY)
        work(
            partner_work,
            "gplA2",
            pairs[1],
            TODAY + timedelta(days=2),
            status="assigned_to_partner",
            assigned_partner_id=partner,
        )
        work(
            visit, "gplA3", pairs[5], TODAY - timedelta(days=3), status="returned_by_pl"
        )
        work(visit, "gplA4", pairs[6], TODAY - timedelta(days=5))
        work(visit, "gplA5", pairs[7], TODAY + timedelta(days=4), reschedule_count=1)
        work(visit, "gplA6", pairs[8], TODAY, status="cancelled")
        work(
            visit,
            "gplA7",
            pairs[10],
            TODAY + timedelta(days=1),
            activity_type="in_school_training",
            status="awaiting_ia_verification",
        )
        work(
            visit,
            "gplA8",
            pairs[11],
            TODAY + timedelta(days=1),
            ssa_collection_expected=True,
        )
        clone(
            cursor,
            "activity_schedule_cost_line",
            line,
            {
                "id": "gplL1",
                "activity_id": "gplA7",
                "cost_setting_key": "golden_gplL1",
                "amount": 125000,
            },
        )
        clone(
            cursor,
            "partner_assignment",
            handover,
            {
                "id": "gplH1",
                "project_id": pairs[2][1],
                "school_id": pairs[2][2],
                "partner_id": partner,
                "status": "assigned",
                "created_at": NOW.isoformat(),
                "scheduled_date": None,
                "scheduled_activity_id": None,
            },
        )
        return {"pairs": pairs, "partner": partner}


def dump_rows():
    out = {}
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(
                f'SELECT row_to_json(t)::text FROM "{table}" t WHERE id LIKE %s ORDER BY id',
                ["gpl%"],
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
    pairs = filed["pairs"]
    coordinator_asks = [
        {},
        {"tab": "baseline"},
        {"tab": "ready"},
        {"tab": "partner"},
        {"tab": "scheduled"},
        {"per_page": "10"},
        {"per_page": "10", "page": "2"},
        {"per_page": "10", "page": "9"},
        {"selected": pairs[1][0]},
        {"selected": pairs[2][0]},
        {"project": pairs[5][1]},
        {"partner_type": "partner"},
        {"partner_type": "staff"},
        {"partner_type": "unassigned"},
        {"activity_type": "in_school_training"},
        {"q": "primary"},
        {"q": "nothing matches this"},
        {"quarter": "Q3"},
        {"fy": str(int(FY) - 1)},
    ]
    readers = {
        "coordinator@edify.org": coordinator_asks,
        "pl1@edify.org": [{}],
        "admin@edify.org": [{}],
        "cd@edify.org": [{}],
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
