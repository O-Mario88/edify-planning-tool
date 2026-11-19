"""Write the Admin Dashboard's golden: /admin-panel
(extended_views.admin_panel_view, pages/admin/index.html) as the existing
feed reads it, with both of its alerts raised.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/out.json \\
    python manage.py shell < platform/backend/internal/adminpanel/testdata/hub_golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gadm", a school whose account owner is unmatched and a scheduled
visit with a cost estimate and no cost lines (plus an online training that
carries none by design); asks the dashboard of the readers who open it and
some who do not, writes the answers with the rows as the database held them
(`tables`), and deletes the rows. internal/integration/admin_hub_test.go
files them again and asks Go. The dashboard with no alerts is asked over
the database as it stands (the suite's scope-profiles golden).
"""

import json
import os

from django.conf import settings
from django.db import connection
from django.utils import timezone

from apps.activities.models import Activity

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("hub_golden.py runs only against a _test database")

P = "gadm"
PAGE = "/admin-panel"
READERS = ("admin@edify.org", "ia@edify.org", "cd@edify.org")
#: The tables filed, in the order they are filed (cleared in reverse).
TABLES = ("school", "activity")


def clear():
    with connection.cursor() as cursor:
        # Filing a school files its data-quality issues too.
        cursor.execute(
            'DELETE FROM "data_quality_issue" WHERE school_id LIKE %s', [P + "%"]
        )
        for table in reversed(TABLES):
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])


def file_rows(today):
    from apps.schools.models import School

    model = School.objects.filter(deleted_at__isnull=True).order_by("id").first()
    school = School.objects.create(
        id=P + "school",
        school_id="GADM-1",
        name="Unmatched Owner Primary",
        district=model.district,
        region=model.region,
        account_owner_status="unmatched",
    )
    fy = str(today.year + 1 if today.month >= 10 else today.year)
    for key, kind, mode, cents in (
        ("visit", "school_visit", None, 4500000),
        ("online", "cluster_training", "online", 4500000),
    ):
        Activity.objects.create(
            id=P + key,
            activity_type=kind,
            status="scheduled",
            delivery_type="staff",
            school=school,
            planned_date=today,
            fy=fy,
            est_cost_cents=cents,
            programme_delivery_mode=mode,
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
    file_rows(timezone.localdate())
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
