"""Write the Verification Notifications golden: /ia/notifications/
(ia_views.ia_notifications_view, pages/ia/notifications.html) as the
existing feed reads it.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/iapages/testdata/notifications_golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gian", fifty-two notices to Impact Assessment under the three
verification categories (so the page's fifty are a cut), one with a link and
one without words, one under another category and one to someone else; it
asks the page of the readers who open it and some who do not, writes the
answers with the rows as the database held them (`tables`), and deletes the
rows. internal/integration/ia_notifications_test.go files them again and
asks Go.
"""

import json
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("notifications_golden.py runs only against a _test database")

User = get_user_model()
P = "gian"
PAGE = "/ia/notifications/"
READERS = ("ia@edify.org", "admin@edify.org", "cd@edify.org", "cceo1@edify.org")
TABLES = ("notification",)


def clear():
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])


def file_rows(now):
    from apps.notifications.models import Notification

    ia = User.objects.get(email="ia@edify.org")
    other = User.objects.get(email="cd@edify.org")
    rows = []
    for n in range(52):
        rows.append(
            Notification(
                id=f"{P}{n:02d}",
                recipient_id=ia.id,
                title=f"Completion {n} submitted for verification",
                body="Kasawo Hill Primary · School Visit" if n % 3 else "",
                category=("verification", "ssa", "ia")[n % 3],
                target_route=f"/ia/verification/?activity=gian{n:02d}"
                if n % 2
                else None,
            )
        )
    rows.append(
        Notification(
            id=P + "general",
            recipient_id=ia.id,
            title="Leave approved",
            category="general",
        )
    )
    rows.append(
        Notification(
            id=P + "elsewhere",
            recipient_id=other.id,
            title="Returned by IA",
            category="ia",
        )
    )
    Notification.objects.bulk_create(rows)
    # Each a whole number of hours apart, newest first.
    for n, row in enumerate(rows):
        Notification.objects.filter(id=row.id).update(
            created_at=now - timedelta(hours=n * 7 + 1)
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
    os.environ["WEB_QUERIES"] = "[{}]"
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
