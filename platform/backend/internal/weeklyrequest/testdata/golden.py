"""Write golden.json: the Weekly Advance Request (/fund-requests/weekly) as the
existing feed reads it, over the development seed's weekly requests and four
the seed lacks.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/golden.json \\
    python manage.py shell < platform/backend/internal/weeklyrequest/testdata/golden.py

Only against a database whose name ends in "_test". The seed's requests are
all drafts: it files four more of the officer's, every id starting "gwr", in
May 2026 (one submitted to the Program Lead, one returned with a reason and
self-funded, one approved and at the Accountant, one submitted to the Country
Director), cloned from their 6 April request and its lines, and deletes them
afterwards. The seed's requests sit in March and April 2026 (FY 2026): it asks the officer
who holds them about each of their weeks and with each request-type and
status filter, their supervisor and the country readers about the same week
and the officer as the staff filter, and readers whose own week holds no
work about today (the page writes a missing request on open only for a
reader's own scheduled week, which Go hands on). Dates sit around the day it
was written, so internal/integration/weekly_request_test.go compares within
half an hour.
"""

import json
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone as dj_timezone

from apps.core.scoping import resolve_user_scope
from apps.mobile_feed.views import read_page
from apps.accounts.models import StaffProfile

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/fund-requests/weekly"
OFFICER = "cceo@edify.org"


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


officer = User.objects.get(email=OFFICER)
officer_staff = (
    StaffProfile.objects.filter(user_id=officer.id).values_list("id", flat=True).first()
)
supervisor = None
for lead in User.objects.filter(active_role="Program Lead").order_by("email"):
    if officer_staff in (resolve_user_scope(lead).supervised_staff_ids or []):
        supervisor = lead
        break

TABLES = ("weekly_fund_request_line", "weekly_fund_request")
FILED = {
    "gwr1": ("2026-05-04", {"status": "submitted_to_pl"}),
    "gwr2": (
        "2026-05-11",
        {
            "status": "returned_by_pl",
            "return_reason": "The venue cost is double counted.",
            "funding_source": "self_fund",
        },
    ),
    "gwr3": ("2026-05-18", {"status": "confirmed_for_advance"}),
    "gwr4": ("2026-05-25", {"status": "submitted_to_cd"}),
}


def clone(cursor, table, base_id, overrides):
    cursor.execute(
        f'INSERT INTO "{table}" SELECT (json_populate_record(NULL::"{table}", '
        "(row_to_json(t)::jsonb || %s::jsonb)::json)).* "
        f'FROM "{table}" t WHERE id = %s',
        [json.dumps(overrides, default=str), base_id],
    )


def clear():
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM weekly_fund_request_line WHERE id LIKE 'gwr%%'")
        cursor.execute("DELETE FROM weekly_fund_request WHERE id LIKE 'gwr%%'")


def file_rows():
    import datetime as dt

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM weekly_fund_request WHERE responsible_user = %s AND week_start_date = '2026-04-06'",
            [officer.id],
        )
        base = cursor.fetchone()[0]
        cursor.execute(
            "SELECT id FROM weekly_fund_request_line WHERE weekly_fund_request_id = %s ORDER BY id",
            [base],
        )
        lines = [r[0] for r in cursor.fetchall()]
        for key, (monday, fields) in FILED.items():
            start = dt.date.fromisoformat(monday)
            clone(
                cursor,
                "weekly_fund_request",
                base,
                {
                    "id": key,
                    "week_start_date": monday,
                    "week_end_date": (start + dt.timedelta(days=6)).isoformat(),
                    **fields,
                },
            )
            for i, line in enumerate(lines):
                clone(
                    cursor,
                    "weekly_fund_request_line",
                    line,
                    {"id": f"{key}L{i}", "weekly_fund_request_id": key},
                )


def dump_rows():
    out = {}
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(
                f'SELECT row_to_json(t)::text FROM "{table}" t WHERE id LIKE %s ORDER BY id',
                ["gwr%"],
            )
            out[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return out


week = {"fy": "2026", "month": "April", "week": "2026-04-06"}
answers = []
clear()
file_rows()
rows = dump_rows()
for query in (
    week,
    {"fy": "2026", "month": "March", "week": "2026-03-30"},
    {"fy": "2026", "month": "April", "week": "2026-04-20"},
    {**week, "request_type": "school visits"},
    {**week, "request_type": "admin budget"},
    {"fy": "2026", "month": "April"},
):
    answers.append(ask(officer, query))
readers = [supervisor] if supervisor else []
readers += [
    User.objects.get(email=e)
    for e in ("cd@edify.org", "accountant@edify.org", "admin@edify.org", "ia@edify.org")
]
for reader in readers:
    answers.append(ask(reader, {**week, "staff": officer.id}))
    answers.append(ask(reader, week))
for email in ("cd@edify.org", "accountant@edify.org"):
    answers.append(ask(User.objects.get(email=email), {}))
for key, (monday, _fields) in FILED.items():
    query = {"fy": "2026", "month": "May", "week": monday}
    answers.append(ask(officer, query))
    for reader in readers:
        answers.append(ask(reader, {**query, "staff": officer.id}))
answers.append(ask(officer, {"fy": "2026", "month": "May"}))
clear()

with open(os.environ["GOLDEN_OUT"], "w") as handle:
    json.dump(
        {"written": dj_timezone.now().isoformat(), "rows": rows, "answers": answers},
        handle,
        ensure_ascii=False,
        indent=1,
        default=str,
    )
print(
    f"{len(answers)} pages asked; supervisor {supervisor.email if supervisor else None}"
)
