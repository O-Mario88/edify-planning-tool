"""Write calendar_golden.json: the Calendar as the existing application
answers it for records the development seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/calendar_golden.json \\
    python manage.py shell < platform/backend/internal/calendarpage/testdata/golden.py

Only against a database whose name ends in "_test". It files a set of rows
there, every id starting "gcal" (leave approved, pending, rejected, over a
year's turn, with a cover and with a date that is not one; organization
events of the country, of another one, inactive, over a month's turn;
recorded public holidays, one a day the national calendar already names and
one an announced Eid; and the officer's and a teammate's work on those days,
over the month's turn, dated at local midnight, programme events with and
without a place, a name with stray spaces, partner-delivered work, work
whose end is before its start, work at a school and in a cluster outside the
Programme Lead's reach), asks the app's feed (apps.mobile_feed.views.
read_page, the view, the template and the reader unmodified) a set of
questions as six accounts, writes the rows and the answers to GOLDEN_OUT and
deletes the rows. internal/integration/calendar_test.go files the same rows,
asks Go the same questions and compares each answer as a whole message.
"""

import json
import os
from datetime import date, datetime, timezone

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone as dj_timezone

from apps.accounts.models import CalendarBlock, Leave, PublicHoliday
from apps.activities.models import Activity
from apps.core.scoping import resolve_user_scope
from apps.mobile_feed.views import read_page
from apps.schools.models import School

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PAUL = "cmw9p7bwp00t19mekheun"  # cceo@edify.org's staff profile
PAUL_USER = "cmw9p7bny006entekhee1"
DEO = "cmw9p7cx800o9ukekheg9"  # on Program Lead 1's team
TABLES = ("activity", "leave", "calendar_block", "public_holiday")


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"DELETE FROM {table} WHERE id LIKE 'gcal%%'")  # noqa: S608  # nosec B608


def file_rows():
    lead = User.objects.get(email="pl1@edify.org")
    reach = set(resolve_user_scope(lead).school_ids or ())
    inside = (
        School.objects.filter(id__in=reach)
        .order_by("id")
        .values_list("id", flat=True)[:2]
    )
    outside = (
        School.objects.exclude(id__in=reach)
        .order_by("id")
        .values_list("id", flat=True)
        .first()
    )
    own, other = list(inside)[0], list(inside)[1]
    district = "cmw9p55h300a2o1eihgzn"
    cluster = "cmw9p8e4900p50wekhe46"

    def act(n, kind, status="scheduled", **kw):
        return Activity(
            id=f"gcal{n:04d}",
            activity_type=kind,
            status=status,
            responsible_staff_id=kw.pop("staff", PAUL),
            **kw,
        )

    nairobi_midnight = datetime(2026, 11, 30, 21, 0, tzinfo=timezone.utc)
    Activity.objects.bulk_create(
        [
            act(1, "school_visit", planned_date=date(2026, 11, 20), school_id=own),
            act(
                2,
                "training",
                planned_date=date(2026, 11, 9),
                end_date=date(2026, 11, 12),
                school_id=own,
            ),
            act(
                3,
                "school_visit",
                planned_date=date(2026, 12, 24),
                end_date=date(2026, 12, 26),
                school_id=other,
            ),
            act(4, "follow_up_visit", scheduled_date=nairobi_midnight, school_id=own),
            act(
                5,
                "coaching_visit",
                scheduled_date=datetime(2026, 10, 31, 21, 0, tzinfo=timezone.utc),
                school_id=own,
            ),
            act(
                6,
                "in_school_training",
                planned_date=date(2026, 10, 30),
                end_date=date(2026, 11, 2),
                school_id=own,
            ),
            act(
                7,
                "programme_event",
                planned_date=date(2026, 11, 17),
                event_district_id=district,
            ),
            act(
                8,
                "programme_event",
                planned_date=date(2026, 11, 17),
                venue="Kampala Serena",
            ),
            act(9, "programme_event", planned_date=date(2026, 11, 17)),
            act(
                10,
                "field_event",
                planned_date=date(2026, 11, 19),
                activity_name_snapshot="  Spaced   name  ",
            ),
            act(
                11,
                "school_visit",
                "assigned_to_partner",
                staff=None,
                monitored_by_staff_id=PAUL,
                delivery_type="partner",
                planned_date=date(2026, 11, 18),
                school_id=own,
            ),
            act(
                12,
                "school_visit",
                "cancelled",
                planned_date=date(2026, 11, 18),
                school_id=own,
            ),
            act(
                13,
                "school_visit",
                "completed",
                planned_date=date(2026, 11, 18),
                school_id=own,
            ),
            act(
                14,
                "school_visit",
                planned_date=date(2026, 11, 16),
                school_id=outside,
                staff=DEO,
            ),
            act(
                15,
                "cluster_meeting",
                planned_date=date(2026, 11, 16),
                cluster_id=cluster,
                staff=DEO,
            ),
            act(
                16,
                "school_visit",
                planned_date=date(2026, 11, 5),
                end_date=date(2026, 11, 1),
                school_id=own,
            ),
            act(
                17,
                "school_visit",
                "in_progress",
                planned_date=date(2026, 11, 20),
                school_id=other,
            ),
            act(
                18,
                "school_visit",
                planned_date=date(2026, 11, 16),
                school_id=other,
                staff=PAUL_USER,
            ),
            act(19, "school_visit", planned_date=date(2026, 11, 16), school_id=own),
            act(
                20,
                "core_visit",
                "rescheduled",
                planned_date=date(2026, 11, 6),
                school_id=own,
            ),
            act(
                21,
                "school_visit",
                planned_date=date(2026, 11, 10),
                school_id=own,
                staff=DEO,
            ),
            act(
                22,
                "school_visit",
                "awaiting_owner_approval",
                planned_date=date(2026, 11, 3),
                school_id=own,
            ),
        ]
    )
    Leave.objects.bulk_create(
        [
            Leave(
                id="gcal0101",
                staff_id=PAUL,
                type="annual_leave",
                status="approved",
                start_date="2026-11-10",
                end_date="2026-11-11",
                days=2,
                covering_staff_id=DEO,
            ),
            Leave(
                id="gcal0102",
                staff_id=PAUL,
                type="sick_leave",
                status="pending",
                start_date="2026-11-23",
                end_date="2026-11-24",
                days=2,
            ),
            Leave(
                id="gcal0103",
                staff_id=PAUL,
                type="study_leave",
                status="approved",
                start_date="2026-12-24",
                end_date="2027-01-02",
                days=6,
            ),
            Leave(
                id="gcal0104",
                staff_id=DEO,
                type="annual_leave",
                status="approved",
                start_date="2026-11-16",
                end_date="2026-11-16",
                days=1,
            ),
            Leave(
                id="gcal0105",
                staff_id=PAUL,
                type="annual_leave",
                status="rejected",
                start_date="2026-11-05",
                end_date="2026-11-05",
                days=1,
            ),
            Leave(
                id="gcal0106",
                staff_id=PAUL,
                type="annual_leave",
                status="approved",
                start_date="2026-11-3x",
                end_date="2026-11-30",
                days=1,
            ),
        ]
    )
    CalendarBlock.objects.bulk_create(
        [
            CalendarBlock(
                id="gcal0201",
                title="Strategy Summit",
                block_type="ORG_EVENT",
                start_date=date(2026, 11, 25),
                end_date=date(2026, 11, 27),
                country="Uganda",
            ),
            CalendarBlock(
                id="gcal0202",
                title="All-staff retreat",
                description="At Jinja",
                block_type="ORG_EVENT",
                start_date=date(2026, 10, 30),
                end_date=date(2026, 11, 3),
                country="Uganda",
            ),
            CalendarBlock(
                id="gcal0203",
                title="Nairobi review",
                block_type="ORG_EVENT",
                start_date=date(2026, 11, 12),
                end_date=date(2026, 11, 12),
                country="Kenya",
            ),
            CalendarBlock(
                id="gcal0204",
                title="Called off",
                block_type="ORG_EVENT",
                is_active=False,
                start_date=date(2026, 11, 12),
                end_date=date(2026, 11, 12),
                country="Uganda",
            ),
            CalendarBlock(
                id="gcal0205",
                title="Idd el Fitri",
                block_type="PUBLIC_HOLIDAY",
                start_date=date(2027, 3, 10),
                end_date=date(2027, 3, 10),
                country="Uganda",
            ),
            CalendarBlock(
                id="gcal0206",
                title="Bonus day",
                block_type="PUBLIC_HOLIDAY",
                start_date=date(2026, 11, 6),
                end_date=date(2026, 11, 7),
                country="Uganda",
            ),
        ]
    )
    PublicHoliday.objects.bulk_create(
        [
            PublicHoliday(
                id="gcal0301", name="Heroes Remembrance", date=date(2026, 11, 20)
            ),
            PublicHoliday(id="gcal0302", name="Christmas Day", date=date(2026, 12, 25)),
        ]
    )


def dump_rows():
    rows = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM {table} t WHERE id LIKE 'gcal%%' ORDER BY id"  # noqa: S608  # nosec B608
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


QUESTIONS = {
    "cceo@edify.org": [
        {},
        {"month": "12", "year": "2026"},
        {"month": "10", "year": "2026"},
        {"month": "3", "year": "2027"},
        {"month": "1", "year": "2027"},
        {"view": "agenda"},
        {"status": "cancelled"},
        {"event_kind": "leave"},
        {"status": "scheduled", "view": "agenda"},
    ],
    "cceo1@edify.org": [{}, {"month": "12", "year": "2026"}],
    "pl1@edify.org": [
        {},
        {"person": PAUL},
        {"person": DEO},
        {"person": PAUL, "month": "12", "year": "2026"},
        {"person": DEO, "view": "agenda"},
        {"person": PAUL, "view": "agenda"},
    ],
    "cd@edify.org": [{}, {"person": PAUL}, {"person": DEO}],
    "admin@edify.org": [{}, {"month": "12", "year": "2026"}, {"view": "agenda"}],
    "ia@edify.org": [{}],
}


def main():
    clear()
    try:
        file_rows()
        rows = dump_rows()
        answers = []
        for email, questions in QUESTIONS.items():
            user = User.objects.get(email=email)
            for query in questions:
                status, body = read_page(user, "/calendar", query)
                answers.append(
                    {"email": email, "query": query, "status": status, "body": body}
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
