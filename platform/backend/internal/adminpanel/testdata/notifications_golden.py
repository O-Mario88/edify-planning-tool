"""Write the Notification & Alert Logs golden:
/admin-panel/notifications-mgmt (extended_views.admin_notifications_mgmt_view,
pages/admin/notifications_mgmt.html) as the existing feed reads it.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/adminpanel/testdata/notifications_golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gnmg", fifty-one notifications dated tomorrow (so the page's fifty
are all of them, and rows written meanwhile stay older): read and unread,
with and without words and a role, one to someone no longer known; asks the
log of the readers who open it and some who do not, writes the answers with
the rows as the database held them (`tables`), and deletes the rows.
internal/integration/admin_notifications_test.go files them again and asks
Go.
"""

import json
import os
from datetime import datetime, time, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("notifications_golden.py runs only against a _test database")

User = get_user_model()
P = "gnmg"
PAGE = "/admin-panel/notifications-mgmt"
READERS = ("admin@edify.org", "ia@edify.org", "cd@edify.org")
TABLES = ("notification",)


def clear():
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])


def file_rows():
    from apps.notifications.models import Notification

    people = [
        User.objects.get(email=e).id
        for e in ("cceo1@edify.org", "pl1@edify.org", "partner@edify.org")
    ] + ["gone-user-id"]
    roles = ("CCEO", "Program Lead", "PartnerFieldOfficer", None)
    Notification.objects.bulk_create(
        [
            Notification(
                id=f"{P}{n:02d}",
                recipient_id=people[n % 4],
                recipient_role=roles[n % 4],
                title=f"Golden notice {n}",
                body=None if n % 3 == 0 else "Kasawo Hill Primary needs a date",
                category="general",
                priority=("normal", "high", "low")[n % 3],
                status="read" if n % 2 else "unread",
            )
            for n in range(51)
        ]
    )
    start = timezone.make_aware(
        datetime.combine(timezone.localdate() + timedelta(days=1), time.min)
    )
    for n in range(51):
        Notification.objects.filter(id=f"{P}{n:02d}").update(
            created_at=start + timedelta(minutes=10 * n)
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
    os.environ["WEB_QUERIES"] = json.dumps([{}, {"logs_page": "2"}])
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
