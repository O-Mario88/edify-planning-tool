"""Write stored_oracle.json: every live activity priced by the existing single
cost writer itself (apps.activities.services.reprice_activity), each inside
a transaction that is rolled back, for Go's pricing.PriceStored to price the
same way.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    ORACLE_OUT=/path/to/stored_oracle.json \\
    python manage.py shell < platform/backend/internal/pricing/testdata/stored_oracle.py

Only against a database whose name ends in "_test". Nothing it writes stays:
each activity is priced in its own transaction, its cost lines are read, and
the transaction is rolled back (the writer's after-commit work never runs).
It first files day_oracle.py's days (ids starting "gpd": several members a
day, a Mixed day, the trip home, a refused day), so that a visit joins a day
it shares; those rows go into ORACLE_OUT and are deleted at the end. An
activity the writer refuses (a finance lock, a missing rate) is recorded
with its refusal; one whose lines the writer leaves as they were is marked
unchanged. internal/integration/stored_pricing_test.go files the same rows
and prices each with Go.
"""

import json
import os
import runpy

from django.conf import settings
from django.db import transaction
from django.utils import timezone as dj_timezone

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.activities.services import reprice_activity
from apps.core.exceptions import BadRequest

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("stored_oracle.py runs only against a _test database")


def lines_of(activity_id):
    return sorted(
        [
            line.cost_setting_key,
            line.label,
            int(line.unit_cost or 0),
            int(line.quantity or 0),
            int(line.amount or 0),
        ]
        for line in ActivityScheduleCostLine.objects.filter(activity_id=activity_id)
    )


def answer(activity_id):
    with transaction.atomic():
        before = lines_of(activity_id)
        activity = Activity.objects.get(id=activity_id)
        try:
            reprice_activity(activity)
        except BadRequest as exc:
            transaction.set_rollback(True)
            return {
                "id": activity_id,
                "refused": str(exc),
                "unchanged": False,
                "lines": [],
            }
        after = lines_of(activity_id)
        transaction.set_rollback(True)
    return {
        "id": activity_id,
        "refused": "",
        "unchanged": after == before,
        "lines": after,
    }


HERE = "platform/backend/internal/pricing/testdata/day_oracle.py"
days = runpy.run_path(HERE, run_name="day_fixtures")
days["clear"]()
try:
    days["file_rows"]()
    rows = days["dump_rows"]()
    ids = list(
        Activity.objects.filter(deleted_at__isnull=True)
        .order_by("id")
        .values_list("id", flat=True)
    )
    answers = [answer(activity_id) for activity_id in ids]
finally:
    days["clear"]()
with open(os.environ["ORACLE_OUT"], "w") as handle:
    json.dump(
        {
            "today": dj_timezone.localdate().isoformat(),
            "rows": rows,
            "activities": answers,
        },
        handle,
        ensure_ascii=False,
        default=str,
    )
print(
    f"{len(answers)} activities priced, {sum(1 for a in answers if a['refused'])} refused"
)
