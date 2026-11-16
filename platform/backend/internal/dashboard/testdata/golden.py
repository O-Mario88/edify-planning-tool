"""Write golden.json: a field officer's Home (/dashboard) as the existing feed
reads it, over work the development seed lacks.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/golden.json \\
    python manage.py shell < platform/backend/internal/dashboard/testdata/golden.py

Only against a database whose name ends in "_test". The seed's officers hold
past-due work from April and nothing this week. It files, every id starting
"gdsh": an officer's past-due work in each state "What needs you now" draws
(scheduled, returned, under way, undated but scheduled, done without its
Salesforce ID, done and complete), this week's work in each state the week
draws (due today, ahead, awaiting the lead, verified, done without its ID), a
partner's work the officer monitors, the officer's leave this week, and a
second officer with no work at all; asks the page of both, for this week and
the weeks either side; writes the rows and the answers to GOLDEN_OUT and
deletes the rows. Dates sit around the day it was written, so
internal/integration/dashboard_test.go compares within half an hour.
"""

import json
import os
from datetime import datetime, time, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone as dj_timezone

from apps.accounts.models import Leave, StaffProfile
from apps.activities.models import Activity
from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/dashboard"
P = "gdsh"
TODAY = dj_timezone.localdate()
MONDAY = TODAY - timedelta(days=TODAY.weekday())
TABLES = ("user", "staff_profile", "activity", "leave")
OFFICER = "cceo1@edify.org"
EMPTY = "gdsh-officer@edify.test"


def clear():
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])


def at(day, hour=10):
    return dj_timezone.make_aware(datetime.combine(day, time(hour)))


def file_rows():
    officer = User.objects.get(email=OFFICER)
    sp = StaffProfile.objects.get(user=officer)
    mine = Activity.objects.filter(
        deleted_at__isnull=True, responsible_staff_id__in=[officer.id, sp.id]
    )
    school = mine.exclude(school=None).first().school
    other = mine.exclude(school=None).exclude(school=school).first().school
    cluster = mine.exclude(cluster=None).first().cluster

    def activity(key, kind, status, planned, **extra):
        place = {"cluster": cluster} if "cluster" in kind else {"school": school}
        Activity.objects.create(
            id=P + key,
            activity_type=kind,
            status=status,
            delivery_type=extra.pop("delivery", "staff"),
            responsible_staff_id=extra.pop("owner", sp.id),
            planned_date=TODAY + timedelta(days=planned)
            if planned is not None
            else None,
            fy="2027",
            **{**place, **extra},
        )

    # Past due, of every kind and state.
    activity("A1", "school_visit", "scheduled", -3)
    activity("A2", "school_visit", "returned", -5, school=other)
    activity(
        "A3",
        "cluster_training",
        "in_progress",
        -10,
        expected_participants=25,
        focus_intervention="leadership",
        activity_purpose_text="Golden training topic",
    )
    activity(
        "A4",
        "school_visit",
        "scheduled",
        None,
        scheduled_date=at(TODAY - timedelta(days=2)),
    )
    activity(
        "A5", "school_visit", "submitted_to_pl", -4, salesforce_activity_id="SVE-GDSH5"
    )
    activity("A6", "school_visit", "completed", -6)
    activity("A7", "cluster_meeting", "rescheduled", -1, expected_participants=12)
    # This week.
    activity("B1", "school_visit", "scheduled", 0)
    activity(
        "B2",
        "cluster_meeting",
        "scheduled",
        2,
        scheduled_date=at(TODAY + timedelta(days=2), 14),
    )
    activity("B3", "in_school_training", "scheduled", 1, school=other)
    activity(
        "B4", "school_visit", "submitted_to_pl", 3, salesforce_activity_id="SVE-GDSH4"
    )
    activity(
        "B5", "school_visit", "ia_verified", 1, salesforce_activity_id="SVE-GDSH5B"
    )
    activity("B6", "school_visit", "completed", 2)
    activity(
        "B7",
        "school_visit",
        "scheduled",
        4,
        delivery="partner",
        owner=None,
        monitored_by_staff_id=sp.id,
    )
    Leave.objects.create(
        id=P + "L1",
        staff=sp,
        type="personal_time_off",
        start_date=(TODAY + timedelta(days=1)).isoformat(),
        end_date=(TODAY + timedelta(days=2)).isoformat(),
        days=2,
        status="approved",
        reason="Golden leave",
        coverage_status="Not Required",
    )
    # An officer with no work at all.
    empty = User.objects.create(
        id=P + "U1",
        email=EMPTY,
        name="Golden Officer",
        roles=["CCEO"],
        active_role="CCEO",
        password=officer.password,
    )
    StaffProfile.objects.create(id=P + "S1", user=empty)


def dump_rows():
    out = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f'SELECT row_to_json(t)::text FROM "{table}" t WHERE id LIKE %s ORDER BY id',
                [P + "%"],
            )
            out[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return out


def ask(reader, query):
    with transaction.atomic():
        status, body = read_page(reader, PATH, query)
        transaction.set_rollback(True)
    return {
        "email": reader.email,
        "path": PATH,
        "query": query,
        "status": status,
        "body": body,
    }


QUERIES = (
    {},
    {"view": "week"},
    {"week": (MONDAY - timedelta(days=7)).isoformat()},
    {"week": (MONDAY + timedelta(days=9)).isoformat()},
)

clear()
answers = []
try:
    file_rows()
    rows = dump_rows()
    for email in (OFFICER, EMPTY):
        reader = User.objects.get(email=email)
        for query in QUERIES:
            answers.append(ask(reader, query))
finally:
    clear()

with open(os.environ["GOLDEN_OUT"], "w", encoding="utf-8") as out:
    json.dump(
        {"written": dj_timezone.now().isoformat(), "rows": rows, "answers": answers},
        out,
        ensure_ascii=False,
        indent=1,
        default=str,
    )
print(f"wrote {len(answers)} answers")
