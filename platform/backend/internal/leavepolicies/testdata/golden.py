"""Write leave_policies_golden.json: Leave Policies as the existing
application answers it over recorded holidays the seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/leave_policies_golden.json \\
    python manage.py shell < platform/backend/internal/leavepolicies/testdata/golden.py

Only against a database whose name ends in "_test". It records public
holidays there, every id starting "glp" (a declared day, one on a national
holiday, an announced Eid, a past day), asks the app's feed as three
accounts, writes the rows and the answers to GOLDEN_OUT and deletes the rows.
The existing view writes the default leave policies on its first read of a
database that has none; in such a test database that first question leaves
them there, as the existing application does, and the golden carries them so
the Go test can file them where they are missing.
internal/integration/leave_policies_test.go files the same rows and compares.
"""

import json
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone as dj_timezone

from apps.accounts.models import PublicHoliday
from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()


def clear():
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM public_holiday WHERE id LIKE 'glp%%'")


def main():
    clear()
    today = dj_timezone.localdate()
    try:
        for i, (name, day) in enumerate(
            [
                ("Heroes Day (declared)", today + timedelta(days=12)),
                ("Christmas Day", today.replace(month=12, day=25)),
                ("Eid al-Adha", today + timedelta(days=200)),
                ("Past declared day", today - timedelta(days=40)),
            ]
        ):
            PublicHoliday.objects.create(id=f"glp{i}", name=name, date=day)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT row_to_json(t)::text FROM public_holiday t WHERE id LIKE 'glp%%' ORDER BY id"
            )
            rows = [json.loads(r[0]) for r in cursor.fetchall()]

        answers = []
        for email in (
            "hr@edify.org",
            "admin@edify.org",
            "ia@edify.org",
            "cd@edify.org",
        ):
            status, body = read_page(
                User.objects.get(email=email), "/leave/policies", {}
            )
            answers.append(
                {"email": email, "query": {}, "status": status, "body": body}
            )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT row_to_json(t)::text FROM leave_type_policy t ORDER BY ctid"
            )
            policies = [json.loads(r[0]) for r in cursor.fetchall()]
    finally:
        clear()
    with open(os.environ["GOLDEN_OUT"], "w") as handle:
        json.dump(
            {
                "today": today.isoformat(),
                "rows": {"public_holiday": rows, "leave_type_policy": policies},
                "answers": answers,
            },
            handle,
            ensure_ascii=False,
            indent=1,
            default=str,
        )
    print(f"{len(answers)} answers written")


main()
