"""Write hr_register_golden.json: the HR registers as the existing
application answers them for people the development seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/hr_register_golden.json \\
    python manage.py shell < platform/backend/internal/hrregister/testdata/golden.py

Only against a database whose name ends in "_test". It files a set of
accounts and People records there, every id starting "ghr" (enough to page
the register; departments, titles and none; pending, suspended and exited;
two lines to one person, a top role with no line, another country, a deleted
record and a deleted account), asks the app's feed (apps.mobile_feed.views.
read_page, the views, the templates and the reader unmodified) a set of
questions as three accounts, writes the rows and the answers to GOLDEN_OUT
and deletes the rows. internal/integration/hr_register_test.go files the same
rows, asks Go the same questions and compares each answer as a whole message.
"""

import json
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone as dj_timezone

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment
from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
#: Deleted children first.
TABLES = ("staff_supervisor_assignment", "staff_profile", "user")
PATHS = ("/org-structure",)


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"DELETE FROM \"{table}\" WHERE id LIKE 'ghr%%'")  # noqa: S608  # nosec B608


def file_rows():
    now = dj_timezone.now()
    profiles = []
    for i in range(62):
        user = User.objects.create(
            id=f"ghru{i:03d}",
            email=f"ghr{i:03d}@example.org",
            name=f"Golden Person {i % 50:02d}",
            roles=["CCEO"],
            active_role=["CCEO", "Program Lead", "CountryDirector"][i % 3],
            is_active=True,
            status="active",
            deleted_at=now if i == 61 else None,
        )
        profiles.append(
            StaffProfile.objects.create(
                id=f"ghrp{i:03d}",
                user=user,
                title=["", "Field Officer", None][i % 3],
                department=["Programmes", "", None, "Finance"][i % 4],
                country="Kenya" if i == 60 else "Uganda",
                onboarding_state=["active", "active", "pending", "suspended", "exited"][
                    i % 5
                ],
                deleted_at=now if i == 59 else None,
            )
        )
    for i in range(1, 40):
        StaffSupervisorAssignment.objects.create(
            id=f"ghrs{i:03d}", supervisee=profiles[i], supervisor=profiles[i % 5]
        )
    StaffSupervisorAssignment.objects.create(
        id="ghrs999", supervisee=profiles[1], supervisor=profiles[7]
    )


def dump_rows():
    rows = {}
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM \"{table}\" t WHERE id LIKE 'ghr%%' ORDER BY id"  # noqa: S608  # nosec B608
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


QUESTIONS = {
    "admin@edify.org": [
        {},
        {"page": "2"},
        {"page": "3"},
        {"page": "9"},
        {"q": "golden"},
        {"q": "golden", "page": "2"},
        {"q": "golden person 0"},
        {"q": "finance"},
        {"q": "kenya"},
    ],
    "hr@edify.org": [{}, {"page": "2"}, {"q": "field officer"}],
    "ia@edify.org": [{}, {"page": "2"}],
}


def main():
    clear()
    try:
        file_rows()
        rows = dump_rows()
        answers = []
        for email, asked in QUESTIONS.items():
            user = User.objects.get(email=email)
            for path in PATHS:
                for query in asked:
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
    out = {
        "today": dj_timezone.localdate().isoformat(),
        "rows": rows,
        "answers": answers,
    }
    with open(os.environ["GOLDEN_OUT"], "w") as handle:
        json.dump(out, handle, ensure_ascii=False, indent=1, default=str)
    print(f"{len(answers)} answers written")


main()
