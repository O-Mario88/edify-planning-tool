"""Write cce_leadership_golden.json: the CCE leadership registers as the
existing application answers them over records the seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/cce_leadership_golden.json \\
    python manage.py shell < platform/backend/internal/ccelead/testdata/golden.py

Only against a database whose name ends in "_test". It files monthly reports
there, every id starting "gcl" (the Regional Lead's in every status, one
reviewed, another author's, other countries, enough for a reader of all of
them to page), asks the app's feed as five accounts, writes the rows and the
answers to GOLDEN_OUT and deletes the rows.
internal/integration/cce_leadership_test.go files the same rows and compares.
"""

import json
import os
from datetime import date, datetime, timedelta, timezone

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone as dj_timezone

from apps.cce_leadership.models import RegionalCceReport
from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
TABLES = ("cce_regional_report",)
PATHS = ("/cce-leadership/reports",)


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"DELETE FROM {table} WHERE id LIKE 'gcl%%'")  # noqa: S608  # nosec B608


def file_rows():
    lead = User.objects.get(email="regional-lead@edify.org")
    rvp = User.objects.get(email="rvp@edify.org")
    at = datetime(2026, 10, 9, 14, 0, tzinfo=timezone.utc)
    statuses = ["draft", "submitted", "acknowledged", "returned"]
    for i in range(6):
        period = date(2026, 4 + i, 1)
        status = statuses[i % 4]
        RegionalCceReport.objects.create(
            id=f"gcl{i:03d}",
            author_id=lead.id,
            period=period,
            fy="2026",
            countries=[["Uganda"], ["Uganda", "Kenya"], ["Kenya"]][i % 3],
            status=status,
            submitted_at=None if status == "draft" else at - timedelta(days=30 * i),
            reviewed_by_id=rvp.id if status in ("acknowledged", "returned") else None,
            reviewed_at=at if status in ("acknowledged", "returned") else None,
        )
    for i in range(52):
        RegionalCceReport.objects.create(
            id=f"gcl{100 + i:03d}",
            author_id=f"other-author-{i % 3}",
            period=date(2020 + i // 12, 1 + i % 12, 1),
            fy="2025",
            countries=["Rwanda"] if i % 5 == 0 else ["Uganda"],
            status=statuses[i % 4],
            submitted_at=None if i % 4 == 0 else at - timedelta(days=i),
        )


def dump_rows():
    rows = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM {table} t WHERE id LIKE 'gcl%%' ORDER BY id"  # noqa: S608  # nosec B608
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


QUESTIONS = {
    "regional-lead@edify.org": [{}],
    "rvp@edify.org": [{}, {"register_page": "2"}],
    "admin@edify.org": [{}, {"register_page": "2"}, {"register_page": "x"}],
    "ia@edify.org": [{}],
    "cd@edify.org": [{}],
}


def main():
    clear()
    try:
        file_rows()
        rows = dump_rows()
        answers = []
        for email, asked in QUESTIONS.items():
            user = User.objects.get(email=email)
            for path in PATHS:
                for query in asked:
                    status, body = read_page(user, path, query)
                    answers.append(
                        {
                            "email": email,
                            "path": path,
                            "query": query,
                            "status": status,
                            "body": body,
                        }
                    )
    finally:
        clear()
    with open(os.environ["GOLDEN_OUT"], "w") as handle:
        json.dump(
            {
                "today": dj_timezone.localdate().isoformat(),
                "rows": rows,
                "answers": answers,
            },
            handle,
            ensure_ascii=False,
            indent=1,
            default=str,
        )
    print(f"{len(answers)} answers written")


main()
