"""Write golden.json: the Finance Approval History page
(/accounts/approval-history/) as the existing feed reads it, over weekly
fund requests the development seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/golden.json \\
    python manage.py shell < platform/backend/internal/approvalhistory/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gah", weekly requests in every stage of the chain (awaiting the
owner, confirmed, approved, disbursed, accounted, returned by the
accountant, returned, rejected), fifty in all, each in its own week after
the seed's and one of them owned by no account, so the first page is theirs
alone. It asks that page of the readers it serves, and of readers it refuses;
writes the rows and the answers to GOLDEN_OUT and deletes the rows.
internal/integration/approval_history_test.go files the same rows and
compares.
"""

import json
import os
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction

from apps.fund_requests.models import WeeklyFundRequest
from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/accounts/approval-history/"
STATUSES = (
    "pending_responsible_confirmation",
    "confirmed_for_advance",
    "approved",
    "disbursed",
    "accounted",
    "returned_by_accountant",
    "returned",
    "rejected",
)


def clear():
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM weekly_fund_request WHERE id LIKE 'gah%%'")


def file_rows():
    """Fifty requests, each in its own week after the seed's, so the first
    page is theirs alone: the seed's requests all fall in one week, and
    requests of the same week come in the order the rows happen to lie in
    the table, which no run can promise."""
    owner = User.objects.get(email="cceo3@edify.org").id
    monday = date(2027, 1, 4)
    for i in range(49):
        week = monday + timedelta(weeks=i)
        WeeklyFundRequest.objects.create(
            id=f"gah{i:02d}",
            fy="2027",
            week_start_date=week,
            week_end_date=week + timedelta(days=6),
            responsible_user=owner,
            responsible_role="CCEO",
            total_amount=150000 + 1000 * i,
            status=STATUSES[i % len(STATUSES)],
        )
    WeeklyFundRequest.objects.create(
        id="gahnobody",
        fy="2028",
        week_start_date=date(2028, 1, 3),
        week_end_date=date(2028, 1, 9),
        responsible_user="gah-no-account",
        responsible_role="CCEO",
        total_amount=5000,
        status="approved",
    )


def dump_rows():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT row_to_json(t)::text FROM weekly_fund_request t WHERE id LIKE 'gah%%' ORDER BY id"
        )
        return {"weekly_fund_request": [json.loads(r[0]) for r in cursor.fetchall()]}


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
        "accountant@edify.org": [
            {},
            {"requests_page": "1"},
            {"requests_page": "x"},
            {"requests_page": "0"},
        ],
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
