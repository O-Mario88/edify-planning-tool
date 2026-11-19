"""Write the SSA Upload History golden: /ssa/upload/history/
(ssa_views.ssa_upload_history_view, pages/ssa/upload_history.html) as the
existing feed reads it.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/iapages/testdata/upload_history_golden.py

Only against a database whose name ends in "_test". It files, every id
starting "guph", fifty-five import batches (so the history runs to a second
page) uploaded by Impact Assessment, the Admin and an officer, each with
rows ready, unmatched and refused, one with no file name and one in a
status of two words; asks the history of the readers who open it and some
who do not, with each filter and page, writes the answers with the rows as
the database held them (`tables`), and deletes the rows.
internal/integration/ssa_upload_history_test.go files them again and asks
Go.
"""

import json
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("upload_history_golden.py runs only against a _test database")

User = get_user_model()
P = "guph"
PAGE = "/ssa/upload/history/"
READERS = (
    "ia@edify.org",
    "admin@edify.org",
    "cd@edify.org",
    "pl1@edify.org",
    "cceo1@edify.org",
    "rvp@edify.org",
)
#: The tables filed, in the order they are filed (cleared in reverse).
TABLES = ("ssa_import_batch", "ssa_import_row")


def clear():
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])


def file_rows(now):
    from apps.schools.models import SSAImportBatch, SSAImportRow

    uploaders = [
        User.objects.get(email=e).id
        for e in ("ia@edify.org", "admin@edify.org", "cceo1@edify.org")
    ]
    batches, rows = [], []
    for n in range(55):
        status = ("completed", "staged", "partially_completed")[n % 3]
        batches.append(
            SSAImportBatch(
                id=f"{P}b{n:02d}",
                file_name="" if n == 9 else f"ssa-import-{n:02d}.xlsx",
                uploaded_by=uploaders[n % 3],
                status=status,
                total_rows=n % 7 + 3,
            )
        )
        for k, row_status in enumerate(
            ["ready"] * (n % 4 + 1)
            + ["unmatched"] * (n % 3)
            + ["blocked"] * (n % 5 == 0)
        ):
            rows.append(
                SSAImportRow(
                    id=f"{P}r{n:02d}{k}",
                    batch_id=f"{P}b{n:02d}",
                    row_number=k + 2,
                    school_id=f"{1100 + n}",
                    status=row_status,
                )
            )
    SSAImportBatch.objects.bulk_create(batches)
    SSAImportRow.objects.bulk_create(rows)
    for n, batch in enumerate(batches):
        SSAImportBatch.objects.filter(id=batch.id).update(
            created_at=now - timedelta(hours=n * 5 + 1)
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
        [
            {},
            {"history_page": "2"},
            {"history_page": "x"},
            {"has_blocked": "1"},
            {"mine": "1"},
            {"has_blocked": "1", "mine": "1"},
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
