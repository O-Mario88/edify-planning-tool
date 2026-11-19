"""Write the Today goldens: /today (today_views.today_page) as the existing
feed reads it, for the Admin (whose desk it is) and for readers it sends
elsewhere or refuses.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/plain.json GOLDEN_OUT_FILED=/path/to/filed.json \\
    python manage.py shell < platform/backend/internal/todaypage/testdata/golden.py

Only against a database whose name ends in "_test". The first golden asks
the page as the database stands. The second files, every id starting
"gtdy", the Admin's snooze of their one To-Do until tomorrow, a snooze
that ended today, another reader's snooze, and two decisions the Admin
cleared from Today today and one yesterday; asks again, writes the answers
with the rows (`tables`) and deletes the rows.
internal/integration/today_test.go files them again and asks Go.
"""

import json
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from apps.command_center.models import TodayActionRecord, TodoSnooze

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
P = "gtdy"
PAGE = "/today"
READERS = (
    "admin@edify.org",
    "cceo1@edify.org",
    "ia@edify.org",
    "hr@edify.org",
    "accountant@edify.org",
    "cd@edify.org",
)
TABLES = ("command_center_todo_snooze", "command_center_today_action")


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])  # noqa: S608  # nosec B608


def file_rows():
    admin = User.objects.get(email="admin@edify.org")
    cceo = User.objects.get(email="cceo1@edify.org")
    today = timezone.localdate()
    for n, (user, todo, until) in enumerate(
        (
            (admin, "partner-user-setup", today + timedelta(days=1)),
            (admin, "cost-catalogue-missing-rates", today),
            (cceo, "partner-user-setup", today + timedelta(days=7)),
        )
    ):
        TodoSnooze.objects.create(
            id=f"{P}s{n}",
            user_id=str(user.id),
            todo_id=todo,
            title="Golden",
            until=until,
        )
    for n, days in enumerate((0, 0, 1)):
        record = TodayActionRecord.objects.create(
            id=f"{P}a{n}",
            user_id=str(admin.id),
            todo_id=f"golden-{n}",
            kind="weekly_receipt",
            operation="confirm",
            record_id=f"golden-{n}",
        )
        TodayActionRecord.objects.filter(id=record.id).update(
            created_at=timezone.now() - timedelta(days=days)
        )


def table_rows(table):
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT row_to_json(t)::text FROM "{table}" t WHERE id LIKE %s ORDER BY id',  # noqa: S608  # nosec B608
            [P + "%"],
        )
        return [json.loads(r[0]) for r in cursor.fetchall()]


def ask(out_path):
    os.environ["GOLDEN_OUT"] = out_path
    oracle = os.path.join(
        settings.BASE_DIR, "platform/backend/internal/webpages/testdata/web_page.py"
    )
    with open(oracle, encoding="utf-8") as fh:
        exec(compile(fh.read(), oracle, "exec"), {"__name__": "__main__"})  # noqa: S102  # nosec B102
    with open(out_path, encoding="utf-8") as fh:
        return json.load(fh)


plain_path = os.environ["GOLDEN_OUT"]
filed_path = os.environ["GOLDEN_OUT_FILED"]
os.environ["WEB_PATH"] = PAGE
os.environ["WEB_READERS"] = ",".join(READERS)
os.environ["WEB_QUERIES"] = json.dumps([{}])
clear()
try:
    ask(plain_path)
    file_rows()
    filed = ask(filed_path)
    filed["tables"] = {table: table_rows(table) for table in TABLES}
    with open(filed_path, "w", encoding="utf-8") as fh:
        json.dump(filed, fh, indent=1, sort_keys=True, ensure_ascii=False)
    print(f"filed {sum(len(v) for v in filed['tables'].values())} rows")
finally:
    clear()
