"""Write quality_flags_golden.json: Quality Flags as the existing application
answers it over flags the seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/quality_flags_golden.json \\
    python manage.py shell < platform/backend/internal/qualityflags/testdata/golden.py

Only against a database whose name ends in "_test". It files flags there,
every id starting "gqf" (every status and one the page does not know, each
priority, with and without a scope, a recommendation, a due day and a
resolution, a raiser without a name, an assignee without an account, other
raisers, more than the register lists), asks the app's feed as five accounts,
writes the rows and the answers to GOLDEN_OUT and deletes the rows.
internal/integration/quality_flags_test.go files the same rows and compares.
"""

import json
import os
from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone as dj_timezone

from apps.flags.models import CdFlag
from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/quality-checks"


def clear():
    CdFlag.objects.filter(id__startswith="gqf").delete()


def file_rows():
    cd = User.objects.get(email="cd@edify.org")
    pl1 = User.objects.get(email="pl1@edify.org")
    pl2 = User.objects.get(email="pl2@edify.org")
    # 22:30 UTC is the next day in Nairobi: the raised day is Nairobi's.
    at = datetime(2026, 11, 1, 22, 30, tzinfo=timezone.utc)
    statuses = ["open", "acknowledged", "resolved", "withdrawn"]
    for i in range(56):
        raiser = [cd.id, cd.id, "gqf-other-raiser"][i % 3]
        CdFlag.objects.create(
            id=f"gqf{i:03d}",
            raised_by_user_id=raiser,
            raised_by_name=None
            if i % 7 == 3
            else ("" if i % 7 == 5 else f"Raiser {i}"),
            assigned_to_user_id=[pl1.id, pl2.id, "gqf-no-account"][i % 3]
            if i % 4
            else pl1.id,
            category=["data-quality", "", "ssa"][i % 3],
            scope_type="school" if i % 2 else None,
            scope_id=f"s{i}" if i % 2 else None,
            scope_name=[None, "Kasana <b>PS</b>", "", "St. Mary's\n  Primary"][i % 4],
            note=["Check the scores", "Line one\n   line two", "Re-check & confirm"][
                i % 3
            ],
            recommended_action=[None, "", "Re-enter the SSA"][i % 3],
            priority=["normal", "high", "very-high", "o'neil"][i % 4],
            due_date=[None, "2026-12-01", "", "next week"][i % 4],
            status=statuses[i % 4],
            resolution_note="Done:\n fixed" if i % 4 == 2 else None,
        )
    # created_at is set on save: give every flag its own moment so the
    # register's newest-first order has no ties.
    for i in range(56):
        CdFlag.objects.filter(id=f"gqf{i:03d}").update(
            created_at=at - timedelta(hours=7 * i)
        )


def dump_rows():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT row_to_json(t)::text FROM cd_flag t WHERE id LIKE 'gqf%%' ORDER BY id"
        )
        return {"cd_flag": [json.loads(r[0]) for r in cursor.fetchall()]}


QUESTIONS = {
    "cd@edify.org": [
        {},
        {"scope_name": "  Gulu <i>PS</i> ", "note": "Look\n again", "category": "ssa"},
        {"assign_to": "nobody"},
        {"resolve": "gqf000"},
    ],
    "pl1@edify.org": [{}, {"resolve": "gqf000"}, {"scope_name": "Ignored"}],
    "pl2@edify.org": [{}],
    "ia@edify.org": [{}],
    "admin@edify.org": [{}, {"scope_name": "Kasana"}],
}


def main():
    clear()
    try:
        file_rows()
        rows = dump_rows()
        pl1 = User.objects.get(email="pl1@edify.org")
        QUESTIONS["cd@edify.org"].append({"assign_to": pl1.id})
        answers = []
        for email, asked in QUESTIONS.items():
            user = User.objects.get(email=email)
            for query in asked:
                status, body = read_page(user, PATH, query)
                answers.append(
                    {
                        "email": email,
                        "path": PATH,
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
