"""Write fy_planning_golden.json: Fiscal Year Planning as the existing
application answers it over planning policies the seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/fy_planning_golden.json \\
    python manage.py shell < platform/backend/internal/fyplanning/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gfy", the next fiscal year opened for the default country (so the
form that opens it is gone), a later year not open yet in another country,
an earlier year with no opening moment and one whose follow-up needs a
prior training; asks the app's feed as the readers who open the page and
one who may not; writes the rows and the answers to GOLDEN_OUT and deletes
the rows. internal/integration/fy_planning_test.go files the same rows and
compares. The page without a policy for the next year (the form drawn) is
proved by the parity run over the seed.
"""

import json
import os
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone as dj_timezone

from apps.core.fy import get_operational_fy
from apps.mobile_feed.views import read_page
from apps.planning.fy_policy import default_country
from apps.planning.models import FiscalYearPlanningPolicy

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/planning/fiscal-years"


def clear():
    FiscalYearPlanningPolicy.objects.filter(id__startswith="gfy").delete()


def window(fy: int):
    return date(fy - 1, 10, 1), date(fy, 9, 30)


def file_rows():
    operational = int(get_operational_fy())
    now = dj_timezone.now()
    shapes = [
        # (fy, country, opening moment, follow-up needs a training)
        (operational + 1, default_country(), now - timedelta(days=3), True),
        (operational + 2, "Kenya", now + timedelta(days=30), False),
        (operational - 3, default_country(), None, False),
        (operational - 4, "Kenya", now - timedelta(days=900), True),
    ]
    for i, (fy, country, open_at, follow_up) in enumerate(shapes):
        start, end = window(fy)
        FiscalYearPlanningPolicy.objects.create(
            id=f"gfy{i:03d}",
            country=country,
            fy=str(fy),
            planning_open_at=open_at,
            execution_start=start,
            execution_end=end,
            follow_up_visit_requires_prior_training=follow_up,
        )


def dump_rows():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT row_to_json(t)::text FROM fiscal_year_planning_policy t WHERE id LIKE 'gfy%%' ORDER BY id"
        )
        return {
            "fiscal_year_planning_policy": [json.loads(r[0]) for r in cursor.fetchall()]
        }


ACCOUNTS = ["admin@edify.org", "cd@edify.org", "ia@edify.org", "cceo1@edify.org"]


def main():
    clear()
    try:
        file_rows()
        rows = dump_rows()
        answers = []
        for email in ACCOUNTS:
            status, body = read_page(User.objects.get(email=email), PATH, {})
            answers.append(
                {
                    "email": email,
                    "path": PATH,
                    "query": {},
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
