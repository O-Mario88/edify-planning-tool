"""Write pl_golden.json: a Programme Lead's Home (/dashboard) as the existing
feed reads it, over team work the development seed lacks.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/pl_golden.json \\
    python manage.py shell < platform/backend/internal/dashboard/testdata/pl_golden.py

Only against a database whose name ends in "_test". The seed's lead and team
hold nothing past due. It files, every id starting "gpld": the team's
past-due work in each state (last week's and older, scheduled, returned, under
way, done without its Salesforce ID, completed and waiting on the lead), a
reminder already sent for one, the lead's own past-due work, this week's work
asking each thing of the lead (Send to, Verify, the lead's own, verified),
and an officer's leave this week; asks the page of the lead for this week,
last week, a person's tab and the team's plans; writes the rows and the
answers to GOLDEN_OUT and deletes the rows. Dates sit around the day it was
written, so the comparison holds within half an hour.
"""

import json
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone as dj_timezone

from apps.accounts.models import Leave, StaffProfile
from apps.activities.models import Activity
from apps.mobile_feed.views import read_page
from apps.notifications.models import Notification

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("pl_golden.py runs only against a _test database")

User = get_user_model()
PATH = "/dashboard"
P = "gpld"
TODAY = dj_timezone.localdate()
MONDAY = TODAY - timedelta(days=TODAY.weekday())
TABLES = ("activity", "leave", "notification")
LEAD = "pl1@edify.org"


def clear():
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])


def profile(email):
    return StaffProfile.objects.get(user__email=email)


def file_rows():
    lead = profile(LEAD)
    paul = profile("cceo@edify.org")
    deo = profile("cceo4@edify.org")

    theirs = Activity.objects.filter(
        deleted_at__isnull=True, responsible_staff_id__in=[paul.id, paul.user_id]
    )
    school = theirs.exclude(school=None).first().school
    cluster = (
        Activity.objects.filter(deleted_at__isnull=True)
        .exclude(cluster=None)
        .first()
        .cluster
    )

    def place(owner, kind):
        return {"cluster": cluster} if "cluster" in kind else {"school": school}

    def activity(key, owner, kind, status, planned, **extra):
        Activity.objects.create(
            id=P + key,
            activity_type=kind,
            status=status,
            delivery_type="staff",
            responsible_staff_id=owner.id,
            planned_date=TODAY + timedelta(days=planned),
            fy="2027",
            **{**place(owner, kind), **extra},
        )

    # Past due: last week's and older, the team's and the lead's own.
    activity("P1", paul, "school_visit", "scheduled", -3)
    activity("P2", paul, "school_visit", "returned", -20)
    activity("P3", deo, "cluster_training", "in_progress", -5, expected_participants=30)
    activity("P4", deo, "school_visit", "completed", -6)
    activity("P5", lead, "school_visit", "scheduled", -2)
    activity(
        "P6",
        paul,
        "school_visit",
        "submitted_to_pl",
        -4,
        salesforce_activity_id="SVE-GPLD6",
    )
    # This week.
    activity("W1", paul, "school_visit", "scheduled", 1)
    activity(
        "W2",
        deo,
        "school_visit",
        "submitted_to_pl",
        0,
        salesforce_activity_id="SVE-GPLD2",
    )
    activity("W3", lead, "cluster_meeting", "scheduled", 2)
    activity(
        "W4", paul, "school_visit", "ia_verified", 1, salesforce_activity_id="SVE-GPLD4"
    )
    Notification.objects.create(
        id=P + "N1",
        recipient_id=paul.id,
        title="Golden reminder",
        body="Golden reminder",
        source_event_type="pl_activity_overdue_reminder",
        context_type="activity",
        context_id=P + "P1",
        category="action_required",
        priority="high",
    )
    Leave.objects.create(
        id=P + "L1",
        staff=deo,
        type="personal_time_off",
        start_date=(TODAY + timedelta(days=2)).isoformat(),
        end_date=(TODAY + timedelta(days=3)).isoformat(),
        days=2,
        status="approved",
        reason="Golden leave",
        coverage_status="Not Required",
    )
    return paul


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


clear()
answers = []
try:
    paul = file_rows()
    rows = dump_rows()
    reader = User.objects.get(email=LEAD)
    for query in (
        {},
        {"week": (MONDAY - timedelta(days=7)).isoformat()},
        {"who": "me"},
        {"who": paul.id},
        {"plans": "team"},
        {"week": (MONDAY + timedelta(days=21)).isoformat()},
        {"week": (MONDAY + timedelta(days=7)).isoformat(), "who": paul.id},
    ):
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
