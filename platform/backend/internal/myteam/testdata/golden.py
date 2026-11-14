"""Write my_team_golden.json: My Team (/my-team) as the existing application
answers it.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/my_team_golden.json \\
    python manage.py shell < platform/backend/internal/myteam/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gmt", leave for a Programme Lead's officers (a request waiting
days for a decision, approved leave under way with nobody covering, leave
ahead, an unreadable span) and coaching by the lead (shared and not
acknowledged, with an open follow-up; and an older one). The existing page
rebuilds a ledger marked stale on its first read; each lead's page is read
once for that, then asked as the four Programme Leads (this year, last year,
a year not offered), Admin and Impact Assessment (who lead no team) and a
CCEO (who may not open it). It writes the rows and the answers to GOLDEN_OUT
and deletes the rows. internal/integration/my_team_test.go files the same
rows and compares.
"""

import json
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone as dj_timezone

from apps.accounts.models import Leave
from apps.cce_leadership.models import CceoCoaching
from apps.core.fy import get_operational_fy
from apps.hr.team_roster import team_members
from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/my-team"
TABLES = ("leave", "cce_cceo_coaching")
LEADS = ["pl1@edify.org", "pl2@edify.org", "pl3@edify.org", "pl4@edify.org"]


def clear():
    Leave.objects.filter(id__startswith="gmt").delete()
    CceoCoaching.objects.filter(id__startswith="gmt").delete()


def file_rows():
    today = dj_timezone.localdate()
    lead = User.objects.get(email="pl1@edify.org")
    officers = team_members(lead)
    if len(officers) < 3:
        raise SystemExit("pl1 needs three officers for the golden")
    a, b, c = officers[:3]

    def leave(key, staff, status, start, end):
        return Leave(
            id=f"gmtv{key}",
            staff=staff,
            type="annual",
            start_date=start,
            end_date=end,
            days=1,
            status=status,
        )

    Leave.objects.bulk_create(
        [
            leave(
                "1",
                a,
                "pending",
                (today + timedelta(days=20)).isoformat(),
                (today + timedelta(days=22)).isoformat(),
            ),
            leave(
                "2",
                b,
                "approved",
                (today - timedelta(days=1)).isoformat(),
                (today + timedelta(days=3)).isoformat(),
            ),
            leave(
                "3",
                c,
                "approved",
                (today + timedelta(days=9)).isoformat(),
                (today + timedelta(days=11)).isoformat(),
            ),
            leave("4", c, "approved", "soon", (today + timedelta(days=30)).isoformat()),
        ]
    )
    Leave.objects.filter(id="gmtv1").update(
        created_at=dj_timezone.now() - timedelta(days=8)
    )
    fy = get_operational_fy()
    CceoCoaching.objects.bulk_create(
        [
            CceoCoaching(
                id="gmtc1",
                author_id=lead.id,
                cceo_staff_id=a.id,
                cceo_user_id=a.user_id,
                kind="one_to_one",
                held_on=today - timedelta(days=4),
                fy=fy,
                country="Uganda",
                subject="Golden one-to-one",
                shared_at=dj_timezone.now(),
                follow_up_due=today + timedelta(days=5),
            ),
            CceoCoaching(
                id="gmtc2",
                author_id=lead.id,
                cceo_staff_id=a.id,
                cceo_user_id=a.user_id,
                kind="field_observation",
                held_on=today - timedelta(days=40),
                fy=fy,
                country="Uganda",
                subject="Golden observation",
            ),
            CceoCoaching(
                id="gmtc3",
                author_id=lead.id,
                cceo_staff_id=b.id,
                cceo_user_id=b.user_id,
                kind="recognition",
                held_on=today - timedelta(days=2),
                fy=fy,
                country="Uganda",
                subject="Golden recognition",
                shared_at=dj_timezone.now(),
                acknowledged_at=dj_timezone.now(),
            ),
        ]
    )


def dump_rows():
    rows = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM \"{table}\" t WHERE id LIKE 'gmt%%' ORDER BY id"  # noqa: S608  # nosec B608
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


def main():
    fy = get_operational_fy()
    questions = {
        email: [{}, {"fy": str(int(fy) - 1)}, {"fy": "1999"}] for email in LEADS
    }
    questions.update(
        {"admin@edify.org": [{}], "ia@edify.org": [{}], "cceo1@edify.org": [{}]}
    )
    clear()
    try:
        file_rows()
        rows = dump_rows()
        # The existing page rebuilds a stale ledger on its first read.
        for email in LEADS:
            for query in questions[email]:
                read_page(User.objects.get(email=email), PATH, query)
        answers = []
        for email, asked in questions.items():
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
