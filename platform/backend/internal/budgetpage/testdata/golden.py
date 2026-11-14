"""Write budget_golden.json: Budget as the existing feed reads it, for a CCEO
and a Program Lead, over planned costs the development seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/budget_golden.json \\
    python manage.py shell < platform/backend/internal/budgetpage/testdata/golden.py

Only against a database whose name ends in "_test". Every id starts "gbg";
the rows are copies of one of the CCEO's planned visits and of one of its
cost lines, written with SQL so no model signal prices or repairs them. For
the CCEO it files: a day shared by a training (whose transport and lunch
are the day's own rates), a cluster training fed by its planned headcount,
a cluster meeting dated only by its month, a programme activity in the
Admin category, a partner training the CCEO monitors (its lump sum shown as
the facilitation fee), a visit the CCEO is responsible for whose line names
no owner, a cost line with no label, a visit at the end of September in the
next year's ledger (the week that crosses 1 October), and a cancelled, a
deleted and an undated activity that draw nothing. It asks the month, the
quarter and the year, both scopes, and a reader the page refuses; writes the
rows and the answers to GOLDEN_OUT and deletes the rows.
internal/integration/budget_test.go files the same rows and compares.
"""

import json
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone as dj_timezone

from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/budget"
#: Children first.
TABLES = ("activity_schedule_cost_line", "activity", "daily_visit_batch")


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"DELETE FROM \"{table}\" WHERE id LIKE 'gbg%%'")  # noqa: S608  # nosec B608


def clone(cursor, table, base_id, overrides):
    cursor.execute(
        f'INSERT INTO "{table}" SELECT (json_populate_record(NULL::"{table}", '  # noqa: S608  # nosec B608
        f'(row_to_json(t)::jsonb || %s::jsonb)::json)).* FROM "{table}" t WHERE id = %s',
        [json.dumps(overrides), base_id],
    )


def file_rows():
    cceo = User.objects.get(email="cceo1@edify.org")
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM staff_profile WHERE user_id = %s", [cceo.id])
        profile = cursor.fetchone()[0]
        cursor.execute(
            """SELECT a.id, l.id FROM activity a JOIN activity_schedule_cost_line l ON l.activity_id = a.id
               WHERE l.responsible_user = %s AND a.activity_type = 'school_visit' AND a.delivery_type = 'staff'
               ORDER BY a.id, l.id LIMIT 1""",
            [cceo.id],
        )
        base_activity, base_line = cursor.fetchone()
        cursor.execute("SELECT id FROM partner ORDER BY id LIMIT 1")
        partner = cursor.fetchone()[0]
        cursor.execute(
            """INSERT INTO daily_visit_batch (id, created_at, updated_at, responsible_user, visit_date,
               district_type, rate_snapshot, daily_pool_amount, school_count, per_school_amount, workload_snapshot)
               VALUES ('gbgb1', now(), now(), %s, '2026-04-15', 'primary', %s, 0, 2, 0, '{}')""",
            [
                cceo.id,
                json.dumps(
                    {
                        "primary_transport_per_day": 60000,
                        "lunch_per_day": "15000",
                        "secondary_breakfast_per_day": 0,
                    }
                ),
            ],
        )

        def activity(suffix, **fields):
            clone(
                cursor,
                "activity",
                base_activity,
                {
                    "id": f"gbga{suffix}",
                    "paired_school_visit_id": None,
                    "salesforce_activity_id": None,
                    "status": "scheduled",
                    "scheduled_date": "2026-04-15T10:00:00+03:00",
                    "planned_date": "2026-04-15",
                    "daily_visit_batch_id": None,
                    "expected_participants": None,
                    "teachers_attended": 0,
                    "leaders_attended": 0,
                    "other_participants": 0,
                    "programme_activity_type": None,
                    **fields,
                },
            )

        def cost(suffix, activity_id, key, amount, **fields):
            clone(
                cursor,
                "activity_schedule_cost_line",
                base_line,
                {
                    "id": f"gbgl{suffix}",
                    "activity_id": activity_id,
                    "cost_setting_key": key,
                    "amount": amount,
                    "unit_cost": amount,
                    "quantity": 1,
                    "planned_date": "2026-04-15",
                    "month": 4,
                    "fiscal_year": "2026",
                    "partner_id": None,
                    "responsible_user": cceo.id,
                    **fields,
                },
            )

        activity(
            "1",
            activity_type="in_school_training",
            daily_visit_batch_id="gbgb1",
            teachers_attended=3,
            leaders_attended=2,
        )
        cost(
            "01",
            "gbga1",
            "primary_transport_per_day",
            30000,
            label="Transport Primary District",
            unit_cost=50000,
        )
        cost("02", "gbga1", "lunch_per_day", 6000, label="Lunch", unit_cost=12000)
        activity("2", activity_type="cluster_training", expected_participants=20)
        cost(
            "03",
            "gbga2",
            "group_training_meals",
            100000,
            label="Group Training - Participant Meals",
            quantity=20,
            unit_cost=5000,
            line_item_type="participant_meals",
        )
        cost("04", "gbga2", "group_training_venue_cost", 40000, label="")
        activity("3", activity_type="cluster_meeting", planned_date=None)
        cost(
            "05",
            "gbga3",
            "cluster_meetings_trainings_meals",
            75000,
            label="Cluster Meeting - Participant Meals",
            planned_date=None,
            month=4,
            quantity=15,
            unit_cost=5000,
            line_item_type="cluster_meeting_participant_meals",
        )
        activity("4", activity_type="partner_activity", programme_activity_type="admin")
        cost("06", "gbga4", "activity:gbg:office", 5000, label="Office items")
        activity(
            "5",
            activity_type="training",
            delivery_type="partner",
            monitored_by_staff_id=profile,
            responsible_staff_id=None,
        )
        cost(
            "07",
            "gbga5",
            "partner_training_lump_sum",
            90000,
            label="Partner training",
            responsible_user="",
        )
        activity("6", activity_type="school_visit", responsible_staff_id=profile)
        cost(
            "08",
            "gbga6",
            "primary_transport_per_day",
            50000,
            label="Transport Primary District",
            responsible_user="",
        )
        cost(
            "09",
            "gbga6",
            "lunch_per_day",
            12000,
            label="Lunch",
            partner_id=partner,
        )
        activity(
            "7",
            activity_type="school_visit",
            scheduled_date="2026-09-30T10:00:00+03:00",
            planned_date="2026-09-30",
            fy="2027",
        )
        cost(
            "10",
            "gbga7",
            "primary_transport_per_day",
            50000,
            label="Transport Primary District",
            planned_date="2026-09-30",
            month=9,
            fiscal_year="2027",
        )
        activity("8", activity_type="school_visit", status="cancelled")
        cost(
            "11",
            "gbga8",
            "primary_transport_per_day",
            50000,
            label="Cancelled transport",
        )
        activity(
            "9", activity_type="school_visit", deleted_at="2026-04-01T00:00:00+03:00"
        )
        cost(
            "12", "gbga9", "primary_transport_per_day", 50000, label="Deleted transport"
        )
        activity(
            "10", activity_type="school_visit", scheduled_date=None, planned_date=None
        )
        cost(
            "13",
            "gbga10",
            "primary_transport_per_day",
            50000,
            label="Undated transport",
        )


def dump_rows():
    rows = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM \"{table}\" t WHERE id LIKE 'gbg%%' ORDER BY id"  # noqa: S608  # nosec B608
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


def questions():
    april = {"fy": "2026", "date": "2026-04-10"}
    return {
        "cceo1@edify.org": [
            april,
            {**april, "period": "quarter"},
            {**april, "period": "fy"},
            {**april, "budget_scope": "team"},
            {**april, "period": "week"},
            {**april, "groups_page": "2"},
            {"fy": "2026", "date": "2026-09-30"},
            {"fy": "2027", "date": "2026-10-02"},
            {},
        ],
        "pl1@edify.org": [
            april,
            {**april, "budget_scope": "team", "period": "fy"},
            {**april, "budget_scope": "my"},
            {**april, "period": "quarter"},
        ],
        "cceo5@edify.org": [april],
        "hr@edify.org": [april],
    }


def main():
    clear()
    try:
        file_rows()
        rows = dump_rows()
        answers = []
        for email, asked in questions().items():
            user = User.objects.filter(email=email).first()
            if user is None:
                continue
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
