"""Write the School Upload History golden: /admin-panel/school-upload-history
(extended_views.admin_school_upload_history_view,
pages/admin/school_upload_history.html) as the existing feed reads it.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/adminpanel/testdata/upload_history_golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gaup", fifty-two upload batches (the page lists the newest fifty)
by Impact Assessment, the Admin, an officer and someone no longer known, in
every status, some with an error summary and some named only by their
original file; asks the history of the readers who open it and some who do
not, writes the answers with the rows as the database held them (`tables`),
and deletes the rows. internal/integration/admin_upload_history_test.go
files them again and asks Go.
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
P = "gaup"
PAGE = "/admin-panel/school-upload-history"
READERS = ("admin@edify.org", "ia@edify.org", "cd@edify.org", "cceo1@edify.org")
TABLES = ("upload_batch",)


def clear():
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])


def file_rows(now):
    from apps.schools.models import UploadBatch

    uploaders = [
        User.objects.get(email=e).id
        for e in ("ia@edify.org", "admin@edify.org", "cceo1@edify.org")
    ] + ["gone-user-id"]
    statuses = ("completed", "imported", "failed", "validated", "uploaded", "rejected")
    batches = []
    for n in range(52):
        batches.append(
            UploadBatch(
                id=f"{P}{n:02d}",
                source=("manual", "upload_center", "salesforce")[n % 3],
                file_name=None if n % 7 == 3 else f"schools-{n:02d}.xlsx",
                original_file_name=f"Original {n}.xlsx",
                uploaded_by=uploaders[n % 4],
                upload_type=("schools", "ssa")[n % 2],
                total_rows=n + 10,
                created_rows=n,
                updated_rows=n % 5,
                failed_rows=n % 3,
                status=statuses[n % 6],
                error_summary="Row 4: district not found" if n % 5 == 2 else None,
            )
        )
    UploadBatch.objects.bulk_create(batches)
    for n, batch in enumerate(batches):
        UploadBatch.objects.filter(id=batch.id).update(
            created_at=now - timedelta(hours=n * 9 + 1)
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
    os.environ["WEB_QUERIES"] = json.dumps([{}, {"batches_page": "2"}])
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
