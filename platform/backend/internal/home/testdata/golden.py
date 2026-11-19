"""Write Home's golden: what the existing feed answers each reader for Home
(apps.mobile_feed.views.HomeFeedView over home_service.build_home).

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/home_golden.json \\
    python manage.py shell < platform/backend/internal/home/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "ghome", an officer's work in each state Home reads: planned for
today, a cluster's work with no purpose of its own, an undated piece with a
time of day, a dated piece saved at local midnight, under way, overdue, and
done (in no figure); asks Home, its Priority actions and its To-Do figures of a reader in
every role the seed holds, and the reader's To-Do rows as the queue words them
(todo_service.get_todos), which Home's Priority actions are drawn from;
writes the instant it asked, the rows and the answers to GOLDEN_OUT, and
deletes the rows. internal/integration/home_test.go files them again and
asks Go at the same instant.
"""

import json
import os
from datetime import datetime, time, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone as dj_timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity
from apps.mobile_feed.views import (
    HomeFeedView,
    HomeQueueFeedView,
    HomeTodoFiguresFeedView,
)

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
P = "ghome"
OFFICER = "cceo1@edify.org"
READERS = (
    "cceo1@edify.org",
    "cceo@edify.org",
    "cceo2@edify.org",
    "pl1@edify.org",
    "pl2@edify.org",
    "cd@edify.org",
    "admin@edify.org",
    "ia@edify.org",
    "accountant@edify.org",
    "hr@edify.org",
    "rvp@edify.org",
    "regional-lead@edify.org",
    "coordinator@edify.org",
    "business-transformation@edify.org",
    "mfi-admin@edify.org",
    "mfi-officer@edify.org",
    "partner@edify.org",
    "partner-admin@edify.org",
    "cluster-leader@edify.org",
)


#: The tables the golden files rows in besides activities: the RVP's budgets
#: to review and an RVP strategy note for the Country Director.
TABLES = ("monthly_work_plan_budget", "country_annual_budget", "rvp_strategy_note")


def clear():
    with connection.cursor() as cursor:
        cursor.execute('DELETE FROM "activity" WHERE id LIKE %s', [P + "%"])
        for table in TABLES:
            cursor.execute(f'DELETE FROM "{table}" WHERE id LIKE %s', [P + "%"])


def file_executive_rows(today):
    """A General Budget and a Country Annual Budget submitted to the RVP, and
    an open strategy note addressed to the Country Director."""
    from apps.monthly_work_plan.models import (
        CountryAnnualBudget,
        MonthlyWorkPlanBudget,
        StrategyNote,
    )

    fy = str(today.year + 1 if today.month >= 10 else today.year)
    MonthlyWorkPlanBudget.objects.create(
        id=P + "budget",
        fy=fy,
        month_key=f"{fy}-gh",
        country_id="Uganda",
        status="submitted_to_rvp",
        total_amount=12_345_000,
        activity_count=17,
    )
    CountryAnnualBudget.objects.create(
        id=P + "annual",
        fy=fy,
        country_id="Uganda",
        status="submitted_to_rvp",
        total_amount=987_654_321,
    )
    StrategyNote.objects.create(
        id=P + "note",
        author_id=User.objects.get(email="rvp@edify.org").id,
        responsible_cd_id=User.objects.get(email="cd@edify.org").id,
        priority_label="Learning outcomes",
        scope="Central region",
        instruction="Visit every school in the lowest decile before the term ends.",
        deadline=today + timedelta(days=5),
        status="open",
    )


def table_rows(table):
    with connection.cursor() as cursor:
        cursor.execute(
            f'SELECT row_to_json(t)::text FROM "{table}" t WHERE id LIKE %s ORDER BY id',
            [P + "%"],
        )
        return [json.loads(r[0]) for r in cursor.fetchall()]


def at(day, hour, minute=0):
    return dj_timezone.make_aware(datetime.combine(day, time(hour, minute)))


def file_rows(today):
    officer = User.objects.get(email=OFFICER)
    sp = StaffProfile.objects.get(user=officer)
    mine = Activity.objects.filter(
        deleted_at__isnull=True, responsible_staff_id__in=[officer.id, sp.id]
    )
    school = mine.exclude(school=None).first().school
    cluster = mine.exclude(cluster=None).first().cluster
    fy = str(today.year + 1 if today.month >= 10 else today.year)

    def activity(key, kind, status, planned, **extra):
        place = (
            {"cluster": cluster}
            if extra.pop("on_cluster", False)
            else {"school": school}
        )
        Activity.objects.create(
            id=P + key,
            activity_type=kind,
            status=status,
            delivery_type="staff",
            responsible_staff_id=sp.id,
            planned_date=today + timedelta(days=planned)
            if planned is not None
            else None,
            fy=fy,
            **{**place, **extra},
        )

    activity(
        "today",
        "school_visit",
        "scheduled",
        0,
        activity_purpose_text="Coaching the head teacher",
    )
    activity("cluster", "cluster_meeting", "planned", 1, on_cluster=True)
    activity(
        "timed",
        "follow_up_visit",
        "scheduled",
        None,
        scheduled_date=at(today + timedelta(days=2), 14, 30),
    )
    activity(
        "midnight",
        "school_visit",
        "rescheduled",
        3,
        scheduled_date=at(today + timedelta(days=3), 0, 0),
    )
    activity("underway", "school_visit", "in_progress", 1)
    activity("overdue", "school_visit", "planned", -4)
    activity("done", "school_visit", "completed", -2)


VIEWS = {
    "body": HomeFeedView,
    "queue": HomeQueueFeedView,
    "todo_figures": HomeTodoFiguresFeedView,
}


#: The words of a To-Do row Home reads (home_service._todo_row, _group_row).
ROW_KEYS = (
    "title",
    "description",
    "category",
    "priority",
    "status_key",
    "status_label",
    "status_tone",
    "due_label",
    "due_tone",
    "linked",
    "action_label",
    "action_url",
)


def todo_rows(user):
    """The reader's queue, row by row, or None where it cannot be built."""
    from apps.command_center.todo_service import get_todos

    try:
        todos = get_todos(user)["todos"]
    except Exception as exc:  # noqa: BLE001 - recorded, not compared
        return {"error": repr(exc)}
    return [{key: str(t.get(key) or "") for key in ROW_KEYS} for t in todos]


def ask(email):
    """Home's three answers for the reader, as the app asks them."""
    user = User.objects.get(email=email)
    out = {"todo_rows": todo_rows(user)}
    for name, view in VIEWS.items():
        request = APIRequestFactory().get("/api/mobile/v1/home")
        force_authenticate(request, user=user)
        response = view.as_view()(request)
        out["status"] = max(out.get("status", 0), response.status_code)
        out[f"{name}_status"] = response.status_code
        out[name] = json.loads(json.dumps(response.data, default=str))
    return out


clear()
try:
    now = dj_timezone.now()
    file_rows(dj_timezone.localdate())
    file_executive_rows(dj_timezone.localdate())
    tables = {table: table_rows(table) for table in TABLES}
    rows = [
        dict(zip([c.name for c in cur.description], r))
        for cur in [connection.cursor()]
        for _ in [
            cur.execute(
                'SELECT row_to_json(a)::text FROM "activity" a WHERE id LIKE %s ORDER BY id',
                [P + "%"],
            )
        ]
        for r in cur.fetchall()
    ]
    answers = [{"email": email, **ask(email)} for email in READERS]
    out = {
        "now": now.isoformat(),
        "rows": [json.loads(r["row_to_json"]) for r in rows],
        "tables": tables,
        "answers": answers,
    }
    with open(os.environ["GOLDEN_OUT"], "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, sort_keys=True)
    print(f"wrote {len(answers)} answers, {len(rows)} rows")
finally:
    clear()
