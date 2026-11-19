"""Write the Unmatched SSA queue's golden: /ssa/unmatched
(extended_views.unmatched_ssa_queue_view over
unmatched_service.get_unmatched_queue, pages/admin/unmatched_ssa_queue.html)
as the existing feed reads it.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/iapages/testdata/unmatched_golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gunm", two upload batches by Impact Assessment and ninety rows
under them: pending (so the queue runs to a second page) and held, some with
a suggested school and its confidence, some with no name or district, and
matched and ignored ones the default filter leaves out. It asks the queue of
the readers who open it and some who do not, with each filter and page,
writes the answers with the rows as the database held them (`tables`), and
deletes the rows. internal/integration/ssa_unmatched_test.go files them
again and asks Go.
"""

import json
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("unmatched_golden.py runs only against a _test database")

User = get_user_model()
P = "gunm"
PAGE = "/ssa/unmatched"
READERS = (
    "ia@edify.org",
    "admin@edify.org",
    "cd@edify.org",
    "cceo1@edify.org",
    "hr@edify.org",
)
#: The tables filed, in the order they are filed (cleared in reverse).
TABLES = ("ssa_import_batch", "unmatched_ssa_record")


def clear():
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])


def file_rows(now):
    from apps.schools.models import School, SSAImportBatch, UnmatchedSSARecord

    ia = User.objects.get(email="ia@edify.org")
    batches = [
        SSAImportBatch.objects.create(
            id=P + key, file_name=name, uploaded_by=ia.id, status="completed"
        )
        for key, name in (("b1", "ssa-term-two.xlsx"), ("b2", "ssa-mukono-late.xlsx"))
    ]
    schools = list(School.objects.filter(deleted_at__isnull=True).order_by("id")[:10])
    rows = []
    for n in range(90):
        status = ("pending", "pending", "hold", "matched", "ignored")[n % 5]
        suggested = schools[n % 10] if n % 3 == 0 else None
        rows.append(
            UnmatchedSSARecord(
                id=f"{P}r{n:02d}",
                batch=batches[n % 2],
                school_id=f"SSA-{1200 + n}",
                school_name_raw=None if n % 11 == 4 else f"St. Unmatched School {n}",
                district_raw=None
                if n % 13 == 5
                else ("Mukono", "Kayunga", "Buikwe")[n % 3],
                date_of_ssa=f"2026-0{n % 9 + 1}-1{n % 9}",
                reason="School ID not found in directory",
                status=status,
                suggested_school=suggested,
                match_confidence=round(0.3 + (n % 7) / 10, 2) if suggested else None,
            )
        )
    UnmatchedSSARecord.objects.bulk_create(rows)
    for n, row in enumerate(rows):
        UnmatchedSSARecord.objects.filter(id=row.id).update(
            created_at=now - timedelta(days=n % 20, minutes=n)
        )
    for n, batch in enumerate(batches):
        SSAImportBatch.objects.filter(id=batch.id).update(
            created_at=now - timedelta(days=n + 1)
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
    today = timezone.localdate()
    tables = {table: table_rows(table) for table in TABLES}
    os.environ["WEB_PATH"] = PAGE
    os.environ["WEB_READERS"] = ",".join(READERS)
    os.environ["WEB_QUERIES"] = json.dumps(
        [
            {},
            {"page": "2"},
            {"page": "x"},
            {"status": "hold"},
            {"status": "ignored"},
            {"batch": P + "b2"},
            {"district": "kay"},
            {"school_id": "123"},
            {"min_confidence": "0.6"},
            {"date_from": (today - timedelta(days=5)).isoformat()},
            {"date_to": (today - timedelta(days=10)).isoformat(), "status": "pending"},
        ]
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
