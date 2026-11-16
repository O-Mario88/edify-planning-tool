"""Write my_performance_golden.json: Priorities (/my-performance) as the
existing application answers it.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/my_performance_golden.json \\
    python manage.py shell < platform/backend/internal/myperformance/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gmp", a development item and a spiritual commitment with an agreed
behaviour, a reflection and a manager's observation on a Programme Lead's
review, and asks the app's feed as every role that may open the page, on
each tab and for the year before (no cycle, no review). It writes the rows
and the answers to GOLDEN_OUT and deletes the rows.
internal/integration/my_performance_test.go files the same rows and compares.
"""

import json
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone as dj_timezone

from apps.core.fy import get_operational_fy
from apps.hr.models import DevelopmentPlanItem, PerformanceReview, ValueCommitment
from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/my-performance"
PRIORITIES_PATH = "/priorities"
TABLES = ("hr_development_plan_item", "hr_value_commitment")
READERS = [
    "cceo1@edify.org",
    "pl1@edify.org",
    "admin@edify.org",
    "ia@edify.org",
    "cd@edify.org",
    "hr@edify.org",
    "accountant@edify.org",
    "coordinator@edify.org",
    "rvp@edify.org",
]


def clear():
    DevelopmentPlanItem.objects.filter(id__startswith="gmp").delete()
    ValueCommitment.objects.filter(id__startswith="gmp").delete()


def file_rows(fy):
    review = PerformanceReview.objects.get(
        staff__user__email="pl1@edify.org", fy=fy, review_type="annual_priorities"
    )
    DevelopmentPlanItem.objects.bulk_create(
        [
            DevelopmentPlanItem(
                id="gmpd1", review=review, description="Golden coaching course"
            )
        ]
    )
    ValueCommitment.objects.bulk_create(
        [
            ValueCommitment(
                id="gmpv1",
                review=review,
                kind="spiritual",
                value_name="Golden devotion",
                agreed_behaviour="Pray with the team weekly",
                employee_reflection="Going well",
                manager_evidence="Seen at every meeting",
            )
        ]
    )


def dump_rows():
    rows = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM \"{table}\" t WHERE id LIKE 'gmp%%' ORDER BY id"  # noqa: S608  # nosec B608
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


def main():
    fy = get_operational_fy()
    queries = [
        {},
        {"tab": "values"},
        {"tab": "spiritual"},
        {"tab": "development"},
        {"fy": str(int(fy) - 1)},
    ]
    clear()
    try:
        file_rows(fy)
        rows = dump_rows()
        answers = []
        for email in READERS:
            user = User.objects.get(email=email)
            # The same page behind the Priorities door, with its own gate.
            for path in (PATH, PRIORITIES_PATH):
                for query in queries:
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
