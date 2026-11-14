"""Write ia_pages_golden.json: the IA review pages as the existing
application answers them over records the development seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/ia_pages_golden.json \\
    python manage.py shell < platform/backend/internal/iapages/testdata/golden.py

Only against a database whose name ends in "_test". It flags pairs of the
database's own activities as possible duplicates, every id starting "gia"
(potential and already decided, in and out of a country, at a school and
cluster-wide, with and without a Salesforce ID and an owner), asks the app's
feed as four accounts, writes the rows and the answers to GOLDEN_OUT and
deletes the rows. internal/integration/ia_pages_test.go files the same rows
and compares Go's answers whole.
"""

import json
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone as dj_timezone

from datetime import datetime, timedelta, timezone

from apps.activities.ia_models import (
    DuplicateActivity,
    IAVerification,
    ReturnedReason,
    VerificationHistory,
)
from apps.activities.models import Activity
from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
TABLES = (
    "ia_verification_history",
    "ia_duplicate_activity",
    "ia_returned_reason",
    "ia_verification",
)
PATHS = ("/ia/duplicates/", "/ia/returned/", "/ia/history/")


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"DELETE FROM {table} WHERE id LIKE 'gia%%'")  # noqa: S608  # nosec B608


def file_rows():
    live = Activity.objects.filter(deleted_at__isnull=True)
    with_school = list(live.filter(school__isnull=False).order_by("id")[:8])
    without = list(live.filter(school__isnull=True).order_by("id")[:2])
    pairs = list(zip(with_school[::2], with_school[1::2])) + [
        (without[0], with_school[0])
    ] * bool(without)
    reasons = [
        "Same school, date, staff and type",
        "Repeated Salesforce ID",
        "Same evidence uploaded twice",
        "Same school, date, staff and type",
        "Cluster-wide repeat",
    ]
    for i, (a, b) in enumerate(pairs):
        DuplicateActivity.objects.create(
            id=f"gia{i:03d}",
            activity=a,
            duplicate_of=b,
            status="potential" if i != 2 else "ignored",
            reason=reasons[i % len(reasons)],
        )


#: The activities the golden marks returned by IA: (id, status, updated_at)
#: before, to put back.
RETURNED: list = []


def file_returned():
    live = Activity.objects.filter(deleted_at__isnull=True).order_by("id")
    picked = list(live.filter(school__isnull=False)[10:64]) + list(
        live.filter(school__isnull=True)[2:3]
    )
    at = datetime(2026, 11, 10, 9, 15, tzinfo=timezone.utc)
    for i, a in enumerate(picked):
        RETURNED.append((a.id, a.status, a.updated_at))
        Activity.objects.filter(id=a.id).update(
            status="returned_by_ia", updated_at=at - timedelta(hours=5 * i)
        )
        if i == 3:
            continue
        verification = IAVerification.objects.create(id=f"giav{i}", activity=a)
        for k in range(i % 3):
            ReturnedReason.objects.create(
                id=f"giar{i}{k}",
                verification=verification,
                reason=["Missing evidence", "Wrong school", "Date mismatch"][k],
            )


def file_history():
    live = Activity.objects.filter(deleted_at__isnull=True).order_by("id")
    with_partner = list(live.filter(assigned_partner_id__isnull=False)[:3])
    others = list(live.filter(school__isnull=False)[70:120]) + list(
        live.filter(school__isnull=True)[:2]
    )
    ia = User.objects.get(email="ia@edify.org")
    at = datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc)
    for i, a in enumerate(with_partner + others):
        VerificationHistory.objects.create(
            id=f"giah{i:03d}",
            activity=a,
            verified_by=[ia.id, "legacy-id", ia.id][i % 3],
            verified_at=at - timedelta(hours=3 * i),
            analytics_included=i % 4 != 1,
        )


def restore_returned():
    for activity_id, status, updated_at in RETURNED:
        Activity.objects.filter(id=activity_id).update(
            status=status, updated_at=updated_at
        )


def dump_rows():
    rows = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM {table} t WHERE id LIKE 'gia%%' ORDER BY ctid"  # noqa: S608  # nosec B608
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


def main():
    clear()
    try:
        file_rows()
        file_returned()
        file_history()
        rows = dump_rows()
        answers = []
        for email in (
            "ia@edify.org",
            "admin@edify.org",
            "cd@edify.org",
            "cceo1@edify.org",
        ):
            user = User.objects.get(email=email)
            for path in PATHS:
                for query in ({}, {"page": "2"}, {"page": "abc"}):
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
        rows["activity_status"] = [
            {"id": i, "status": "returned_by_ia", "updated_at": u}
            for i, u in Activity.objects.filter(id__in=[r[0] for r in RETURNED])
            .values_list("id", "updated_at")
            .order_by("id")
        ]
        rows["activity_restore"] = [
            {"id": i, "status": st, "updated_at": u} for i, st, u in RETURNED
        ]
    finally:
        clear()
        restore_returned()
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
