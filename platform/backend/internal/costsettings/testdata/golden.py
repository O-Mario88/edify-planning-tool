"""Write cost_settings_golden.json: the Cost Catalogue and Cost Intelligence
as the existing feed reads them, over a register and a review queue the
development seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/cost_settings_golden.json \\
    python manage.py shell < platform/backend/internal/costsettings/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gcs": 35 costs linked to the first governed activity on the
published card (so the register has two pages and that activity's recipe
lists them), with and without a minimum; and three cost reviews on an
existing snapshot, two waiting (one with no proposed amount) and one
decided. It asks both doors for the readers who open them, the register's
and the coverage's second pages, a page past the end and one that is not a
number, and a reader who opens neither; writes the rows and the answers to
GOLDEN_OUT and deletes the rows. internal/integration/cost_settings_test.go
files the same rows and compares.
"""

import json
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone as dj_timezone

from apps.activity_catalogue.services import effective_items
from apps.budget.costing_service import active_catalogue
from apps.budget.models import ActivityCostReview, ActivityCostSnapshot, CostSetting
from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
#: Children first.
TABLES = ("activity_cost_review", "cost_setting")


def clear():
    ActivityCostReview.objects.filter(id__startswith="gcs").delete()
    CostSetting.objects.filter(id__startswith="gcs").delete()


def file_rows():
    card = active_catalogue()
    if card is None:
        raise SystemExit("no published card on this database")
    item = effective_items().order_by("display_name").first()
    for i in range(35):
        CostSetting.objects.create(
            id=f"gcsr{i:02d}",
            key=f"activity:gcs:{i:02d}",
            label=f"Golden cost {i:02d}",
            unit="per day",
            unit_cost=1000 + i,
            approved_minimum=None if i % 2 else 500 + i,
            version=1 + i % 3,
            catalogue=card,
            catalogue_item=item,
        )
    snapshot = ActivityCostSnapshot.objects.order_by("id").first()
    if snapshot is None:
        raise SystemExit("no cost snapshot on this database")
    reasons = [c[0] for c in ActivityCostReview._meta.get_field("reason_code").choices]
    now = dj_timezone.now()
    for n, (proposed, status) in enumerate(
        [(None, "submitted"), (99000, "submitted"), (5, "approved")]
    ):
        review = ActivityCostReview.objects.create(
            id=f"gcsv{n}",
            activity_id=snapshot.activity_id,
            snapshot=snapshot,
            reason_code=reasons[n % len(reasons)],
            explanation="golden",
            current_operational_cost=12345 * (n + 1),
            proposed_operational_cost=proposed,
            status=status,
            requested_by="golden",
        )
        ActivityCostReview.objects.filter(pk=review.pk).update(
            created_at=now - timedelta(minutes=n)
        )


def dump_rows():
    rows = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM \"{table}\" t WHERE id LIKE 'gcs%%' ORDER BY id"  # noqa: S608  # nosec B608
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


def questions():
    settings_door = "/cost-settings"
    intelligence = "/cost-intelligence"
    asked = {
        "cd@edify.org": [
            (settings_door, {}),
            (settings_door, {"cost_items_page": "2", "fy": "2026"}),
            (settings_door, {"activity_coverage_page": "2"}),
            (settings_door, {"cost_items_page": "9"}),
            (settings_door, {"cost_items_page": "x"}),
            (intelligence, {}),
        ],
        "admin@edify.org": [
            (settings_door, {}),
            (intelligence, {"cost_items_page": "2"}),
        ],
        "ia@edify.org": [(settings_door, {}), (intelligence, {})],
        "rvp@edify.org": [(intelligence, {}), (settings_door, {})],
        "accountant@edify.org": [(intelligence, {})],
        "cceo1@edify.org": [(settings_door, {}), (intelligence, {})],
    }
    return {
        email: questions
        for email, questions in asked.items()
        if User.objects.filter(email=email).exists()
    }


def main():
    clear()
    try:
        file_rows()
        rows = dump_rows()
        answers = []
        for email, asked in questions().items():
            user = User.objects.get(email=email)
            for path, query in asked:
                status, body = read_page(user, path, query)
                answers.append(
                    {
                        "email": email,
                        "path": path,
                        "query": query,
                        "status": status,
                        "body": body,
                    }
                )
    finally:
        clear()
    with open(os.environ["GOLDEN_OUT"], "w") as handle:
        json.dump(
            {
                "today": dj_timezone.localdate().isoformat(),
                "rows": rows,
                "answers": answers,
            },
            handle,
            ensure_ascii=False,
            indent=1,
            default=str,
        )
    print(f"{len(answers)} answers written")


main()
