"""Write verification_golden.json: Impact Assessment's Verification Queue
(/ia/verification/) as the existing feed reads it, over work waiting for
verification the development seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/verification_golden.json \\
    python manage.py shell < platform/backend/internal/iapages/testdata/verification_golden.py

Only against a database whose name ends in "_test". It files, every id
starting "giv", copies of one stored visit waiting for verification with a
Salesforce ID, owned by the Project Coordinator (which Impact Assessment
verifies) and by an Impact Assessment officer (which only the Country
Director, standing in, sees): a core visit, an overdue visit, a fresh one, a
core-school visit, a cluster-wide session, a training next year; and the work
the queue leaves out (partner-delivered, no Salesforce ID) or that only the
"missing Salesforce ID" drill-down lists (completed and closed work with
none). Every submission time sits half an hour from an hour, so the ages hold
for half an hour after the file is written. It asks the queue of the readers
the page opens for and one it refuses, with each filter, each drill-down, a
search and a page past the end, writes the rows and the answers to
GOLDEN_OUT and deletes the rows. internal/integration/ia_verification_test.go
files the same rows and compares.
"""

import json
import os
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone as dj_timezone

from apps.mobile_feed.views import read_page

if not settings.DATABASES["default"]["NAME"].endswith("_test"):
    raise SystemExit("verification_golden.py runs only against a _test database")

User = get_user_model()
PATH = "/ia/verification/"
NOW = dj_timezone.now()


def clear():
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM activity WHERE id LIKE 'giv%%'")


def clone(cursor, base_id, overrides):
    cursor.execute(
        'INSERT INTO "activity" SELECT (json_populate_record(NULL::"activity", '
        '(row_to_json(t)::jsonb || %s::jsonb)::json)).* FROM "activity" t WHERE id = %s',
        [json.dumps(overrides), base_id],
    )


def file_rows():
    with connection.cursor() as cursor:

        def one(sql, args=()):
            cursor.execute(sql, args)
            row = cursor.fetchone()
            return row[0] if row else None

        coordinator = one(
            "SELECT sp.id FROM staff_profile sp JOIN \"user\" u ON u.id = sp.user_id WHERE u.email = 'coordinator@edify.org'"
        )
        officer = one(
            "SELECT sp.id FROM staff_profile sp JOIN \"user\" u ON u.id = sp.user_id WHERE u.email = 'ia@edify.org'"
        )
        base = one(
            "SELECT id FROM activity WHERE activity_type = 'school_visit' AND deleted_at IS NULL ORDER BY id LIMIT 1"
        )
        core = one(
            "SELECT id FROM school WHERE school_type = 'core' AND deleted_at IS NULL AND district_id IS NOT NULL ORDER BY id LIMIT 1"
        )
        cursor.execute(
            "SELECT id FROM school WHERE school_type <> 'core' AND deleted_at IS NULL AND district_id IS NOT NULL "
            "AND region_id IS NOT NULL ORDER BY id LIMIT 3"
        )
        schools = [r[0] for r in cursor.fetchall()]
        cluster = one("SELECT id FROM cluster ORDER BY id LIMIT 1")
        n = 0

        def work(owner, hours, **fields):
            nonlocal n
            n += 1
            at = (NOW - timedelta(hours=hours, minutes=30)).isoformat()
            clone(
                cursor,
                base,
                {
                    "id": f"giv{n:02d}",
                    "status": "awaiting_ia_verification",
                    "delivery_type": "staff",
                    "responsible_staff_id": owner,
                    "salesforce_activity_id": f"SF-GIV-{n:02d}",
                    "submitted_to_ia_at": at,
                    "updated_at": at,
                    "created_at": at,
                    "paired_school_visit_id": None,
                    "daily_visit_batch_id": None,
                    "fy": "2027",
                    "quarter": "Q1",
                    "planned_month": 11,
                    "ssa_collection_expected": False,
                    "school_id": schools[0],
                    "cluster_id": None,
                    **fields,
                },
            )

        work(coordinator, 3, activity_type="core_visit", school_id=core)
        work(coordinator, 50, school_id=schools[1])
        work(coordinator, 1, school_id=schools[2], ssa_collection_expected=True)
        # A day old to the hour: the age turns from hours to days.
        work(coordinator, 24, school_id=schools[2])
        work(
            coordinator,
            30,
            activity_type="training",
            fy="2026",
            quarter="Q4",
            planned_month=9,
        )
        work(
            coordinator,
            5,
            activity_type="cluster_meeting",
            school_id=None,
            cluster_id=cluster,
        )
        work(officer, 8, school_id=schools[1])
        work(
            officer,
            26,
            activity_type="core_training",
            school_id=core,
            quarter="Q2",
            planned_month=1,
        )
        # Left out of the queue: partner-delivered, and no Salesforce ID.
        work(coordinator, 4, delivery_type="partner")
        work(coordinator, 6, salesforce_activity_id="")
        # Delivered with no Salesforce ID (the drill-down's population).
        work(coordinator, 70, status="completed", salesforce_activity_id=None)
        work(officer, 90, status="closed", salesforce_activity_id="")


def dump_rows():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT row_to_json(t)::text FROM activity t WHERE id LIKE 'giv%%' ORDER BY id"
        )
        return {"activity": [json.loads(r[0]) for r in cursor.fetchall()]}


def questions(district, school, region, cluster):
    return [
        {},
        {"fy": "2027"},
        {"fy": "2026"},
        {"quarter": "Q2"},
        {"activity_type": "core_visit"},
        {"activity_type": "training"},
        {"core_school": "true"},
        {"age": "overdue"},
        {"sf_id": "missing"},
        {"evidence": "ready"},
        {"age": "overdue", "activity_type": "school_visit"},
        {"district": district[:5]},
        {"school": school},
        {"region": region},
        {"cluster": cluster},
        {"month": "11"},
        {"month": "x"},
        {"status": "awaiting_ia_verification"},
        {"q": "SF-GIV-02"},
        {"q": school[:4]},
        {"staff": "Coordin"},
        {"page": "2"},
        {"sf_id": "bogus"},
        {"sf_id": "missing", "page": "2"},
        {"sf_id": "missing", "page": "99"},
    ]


clear()
answers = []
try:
    file_rows()
    rows = dump_rows()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT d.name, s.id, s.region_id FROM activity a JOIN school s ON s.id = a.school_id "
            "JOIN district d ON d.id = s.district_id WHERE a.id = 'giv02'"
        )
        district, school, region = cursor.fetchone()
        cursor.execute(
            "SELECT cluster_id FROM activity WHERE id LIKE 'giv%%' AND cluster_id IS NOT NULL LIMIT 1"
        )
        cluster = cursor.fetchone()[0]
    asked = questions(district, school, region, cluster)
    readers = {
        "ia@edify.org": asked,
        "cd@edify.org": asked,
        "admin@edify.org": [{}, {"sf_id": "missing"}],
        "pl1@edify.org": [{}],
        "cceo@edify.org": [{}],
    }
    for email, qs in readers.items():
        user = User.objects.get(email=email)
        for query in qs:
            with transaction.atomic():
                status, body = read_page(user, PATH, query)
                transaction.set_rollback(True)
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
            "written": NOW.isoformat(),
            "rows": rows,
            "answers": answers,
        },
        handle,
        ensure_ascii=False,
        indent=1,
        default=str,
    )
print(f"{len(answers)} pages asked")
