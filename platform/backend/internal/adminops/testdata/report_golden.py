"""Write the Report a Problem golden: /support
(admin_ops.views.report_problem_view, pages/admin_ops/report_problem.html)
as the existing feed reads it.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/adminops/testdata/report_golden.py

Only against a database whose name ends in "_test". It files, every id
starting "garp", twenty-two tickets a CCEO reported (more than the page's
twenty; every status, some resolved with words) and one someone else
reported, dated tomorrow so rows written meanwhile stay older; asks the page
of the reporter and of readers with none, writes the answers with the rows
(`tables`) and deletes the rows. internal/integration/admin_report_test.go
files them again and asks Go.
"""

import json
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from apps.admin_ops.models import TicketStatus

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("report_golden.py runs only against a _test database")

User = get_user_model()
P = "garp"
PAGE = "/support"
READERS = ("cceo1@edify.org", "pl1@edify.org", "partner@edify.org", "admin@edify.org")
TABLES = ("admin_support_ticket",)


def clear():
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM admin_support_ticket WHERE id LIKE %s", [P + "%"])


def file_rows():
    reporter = User.objects.get(email="cceo1@edify.org")
    other = User.objects.get(email="pl1@edify.org")
    statuses = [value for value, _ in TicketStatus.choices]
    start = timezone.now() + timedelta(days=1)
    with connection.cursor() as cursor:
        for n in range(23):
            who = other if n == 22 else reporter
            cursor.execute(
                """INSERT INTO admin_support_ticket (id, created_at, updated_at, reference, title, category, description,
                   urgency, status, reporter_id, reporter_role, route, page_title, object_type, object_id, browser,
                   request_id, resolution)
                   VALUES (%s, %s, %s, %s, %s, 'dead_button', 'It did nothing', 'medium', %s, %s, %s, '/planning', '', '',
                   '', '', '', %s)""",
                [
                    f"{P}{n:02d}",
                    start + timedelta(minutes=n),
                    start + timedelta(minutes=n),
                    f"GARP-{n:04d}",
                    f"Golden report {n}",
                    statuses[n % len(statuses)],
                    who.id,
                    who.active_role,
                    "Fixed the button handler" if n % 4 == 0 else "",
                ],
            )


def table_rows(table):
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT row_to_json(t)::text FROM "{table}" t WHERE id LIKE %s ORDER BY id',  # noqa: S608  # nosec B608
            [P + "%"],
        )
        return [json.loads(r[0]) for r in cursor.fetchall()]


clear()
try:
    file_rows()
    tables = {table: table_rows(table) for table in TABLES}
    os.environ["WEB_PATH"] = PAGE
    os.environ["WEB_READERS"] = ",".join(READERS)
    os.environ["WEB_QUERIES"] = json.dumps([{}, {"route": "/planning"}])
    oracle = os.path.join(
        settings.BASE_DIR, "platform/backend/internal/webpages/testdata/web_page.py"
    )
    with open(oracle, encoding="utf-8") as fh:
        exec(compile(fh.read(), oracle, "exec"), {"__name__": "__main__"})  # noqa: S102  # nosec B102
    with open(os.environ["GOLDEN_OUT"], encoding="utf-8") as fh:
        out = json.load(fh)
    out["tables"] = tables
    with open(os.environ["GOLDEN_OUT"], "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True, ensure_ascii=False)
    print(f"filed {sum(len(v) for v in tables.values())} rows")
finally:
    clear()
