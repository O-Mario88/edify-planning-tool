"""Write the Duplicate Review Queue's golden: /data-quality/duplicates
(extended_views.duplicate_review_view over data_quality.open_issues,
pages/admin/duplicate_review.html) as the existing feed reads it.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/dataquality/testdata/duplicates_golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gdqd", fifty-two open duplicate risks at operating schools (so the
queue runs to a second page), one with no suggested fix, one resolved and
one of another kind; asks the queue of the readers who open it and some who
do not, on each page, writes the answers with the rows as the database held
them (`tables`), and deletes the rows.
internal/integration/data_quality_duplicates_test.go files them again and
asks Go.
"""

import json
import os
from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.utils import timezone

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("duplicates_golden.py runs only against a _test database")

P = "gdqd"
PAGE = "/data-quality/duplicates"
READERS = (
    "ia@edify.org",
    "admin@edify.org",
    "cd@edify.org",
    "cceo1@edify.org",
    "accountant@edify.org",
)
TABLES = ("data_quality_issue",)


def clear():
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])


def file_rows(now):
    from apps.schools.models import DataQualityIssue, School

    schools = list(
        School.objects.filter(
            deleted_at__isnull=True, operational_status__in=("active", "reopened")
        ).order_by("id")[:55]
    )
    rows = [
        DataQualityIssue(
            id=f"{P}{n:02d}",
            school=schools[n],
            issue_type="duplicate_risk",
            suggested_fix=None if n == 7 else f"Compare with {schools[n + 1].name}",
            status="open",
        )
        for n in range(52)
    ]
    rows += [
        DataQualityIssue(
            id=P + "resolved",
            school=schools[52],
            issue_type="duplicate_risk",
            status="resolved",
        ),
        DataQualityIssue(
            id=P + "phone",
            school=schools[53],
            issue_type="missing_phone",
            status="open",
        ),
    ]
    DataQualityIssue.objects.bulk_create(rows)
    for n, row in enumerate(rows):
        DataQualityIssue.objects.filter(id=row.id).update(
            created_at=now - timedelta(minutes=n * 3 + 1)
        )


def table_rows(table):
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT row_to_json(t)::text FROM "{table}" t WHERE id LIKE %s ORDER BY id',
            [P + "%"],
        )
        return [json.loads(r[0]) for r in cursor.fetchall()]


clear()
try:
    file_rows(timezone.now())
    tables = {table: table_rows(table) for table in TABLES}
    os.environ["WEB_PATH"] = PAGE
    os.environ["WEB_READERS"] = ",".join(READERS)
    os.environ["WEB_QUERIES"] = json.dumps(
        [{}, {"issues_page": "2"}, {"issues_page": "x"}, {"issues_page": "9"}]
    )
    oracle = os.path.join(
        settings.BASE_DIR, "platform/backend/internal/webpages/testdata/web_page.py"
    )
    with open(oracle, encoding="utf-8") as fh:
        exec(compile(fh.read(), oracle, "exec"), {"__name__": "__main__"})  # noqa: S102
    with open(os.environ["GOLDEN_OUT"], encoding="utf-8") as fh:
        out = json.load(fh)
    out["tables"] = tables
    with open(os.environ["GOLDEN_OUT"], "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print(f"filed {sum(len(v) for v in tables.values())} rows")
finally:
    clear()
