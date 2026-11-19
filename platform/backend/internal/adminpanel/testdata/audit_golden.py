"""Write the Audit Log's golden: /admin-panel/audit-log
(extended_views.audit_log_view, pages/admin/audit_log.html) as the existing
feed reads it.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/adminpanel/testdata/audit_golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gaud", a hundred and one audit rows dated tomorrow, a quarter of an
hour apart from midnight (so the page's hundred are all of them, past noon
and at whole hours, and rows written meanwhile by the suite stay older). The
rows carry no sequence number, so they stand outside the audit chain. It
asks the log of the readers who open it and some who do not, on each page,
writes the answers with the rows as the database held them (`tables`), and
deletes the rows. internal/integration/admin_audit_log_test.go files them
again and asks Go.
"""

import json
import os
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import connection
from django.utils import timezone

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("audit_golden.py runs only against a _test database")

P = "gaud"
PAGE = "/admin-panel/audit-log"
READERS = ("admin@edify.org", "ia@edify.org", "cd@edify.org", "cceo1@edify.org")
TABLES = ("audit_log",)
ACTIONS = ("school.updated", "activity.completed", "user.signed_in", "partner.assigned")


def clear():
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])


def file_rows():
    from apps.audit.models import AuditLog

    tomorrow = timezone.localdate() + timedelta(days=1)
    start = timezone.make_aware(datetime.combine(tomorrow, time.min))
    AuditLog.objects.bulk_create(
        [
            AuditLog(id=f"{P}{n:03d}", action=ACTIONS[n % 4], success=True)
            for n in range(101)
        ]
    )
    # created_at is set on create; each row is dated after.
    for n in range(101):
        AuditLog.objects.filter(id=f"{P}{n:03d}").update(
            created_at=start + timedelta(minutes=15 * n)
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
    file_rows()
    tables = {table: table_rows(table) for table in TABLES}
    os.environ["WEB_PATH"] = PAGE
    os.environ["WEB_READERS"] = ",".join(READERS)
    os.environ["WEB_QUERIES"] = json.dumps([{}, {"logs_page": "2"}, {"logs_page": "x"}])
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
