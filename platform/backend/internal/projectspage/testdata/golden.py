"""Write projects_golden.json: the Special Projects page (/projects) as the
existing feed reads it, over project work the development seed does not
hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/projects_golden.json \\
    python manage.py shell < platform/backend/internal/projectspage/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gpj": an Intervention Specific project led by someone else that a
CCEO is assigned to, and a deleted one; on the first seeded project (CCSEL) a
closed in-school training with its head counts, a partner-delivered visit, a
visit under way with a follow-up to come, one awaiting IA, one returned by
IA, one handed to a partner and one in the year before, with their costs; on
the second (DIP) a closed visit whose money has been paid; and two partners
on CCSEL and one on DIP. It asks the page of every reader it opens for (and
one it does not) with no query, each filter (a year, a type, each status,
values the page does not offer), another tab, another selected project and
both, writes the rows and the answers to GOLDEN_OUT and deletes the rows.
internal/integration/projects_page_test.go files the same rows and compares.
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
#: Children first.
TABLES = (
    "activity_schedule_cost_line",
    "activity",
    "project_partner_assignment",
    "project_staff_assignment",
    "project",
)
CCSEL, DIP = "cmw9p8dew00haokekherx", "cmw9p8df500327kekheh0"


def clear():
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f"DELETE FROM \"{table}\" WHERE id LIKE 'gpj%%'")  # noqa: S608  # nosec B608


def clone(cursor, table, base_id, overrides):
    cursor.execute(
        f'INSERT INTO "{table}" SELECT (json_populate_record(NULL::"{table}", '  # noqa: S608  # nosec B608
        f'(row_to_json(t)::jsonb || %s::jsonb)::json)).* FROM "{table}" t WHERE id = %s',
        [json.dumps(overrides), base_id],
    )


def file_rows():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM staff_profile WHERE user_id = (SELECT id FROM \"user\" WHERE email = 'cceo@edify.org')"
        )
        cceo_profile = cursor.fetchone()[0]
        cursor.execute(
            "SELECT id FROM staff_profile WHERE user_id = (SELECT id FROM \"user\" WHERE email = 'pl1@edify.org')"
        )
        pl_profile = cursor.fetchone()[0]
        cursor.execute(
            "SELECT school_id FROM project_school_assignment WHERE project_id = %s ORDER BY school_id",
            [CCSEL],
        )
        schools = [r[0] for r in cursor.fetchall()]
        cursor.execute(
            "SELECT school_id FROM project_school_assignment WHERE project_id = %s ORDER BY school_id LIMIT 1",
            [DIP],
        )
        dip_school = cursor.fetchone()[0]
        cursor.execute("SELECT id FROM partner ORDER BY name LIMIT 2")
        partners = [r[0] for r in cursor.fetchall()]
        cursor.execute(
            "SELECT id FROM activity WHERE activity_type = 'school_visit' AND deleted_at IS NULL ORDER BY id LIMIT 1"
        )
        base_activity = cursor.fetchone()[0]
        cursor.execute("SELECT id FROM activity_schedule_cost_line ORDER BY id LIMIT 1")
        base_line = cursor.fetchone()[0]

        # A project led by the Program Lead that a CCEO works on, and one
        # deleted.
        clone(
            cursor,
            "project",
            CCSEL,
            {
                "id": "gpjp1",
                "name": "Golden Leadership Drive",
                "code": None,
                "category": "intervention_specific",
                "manager_staff_id": pl_profile,
                "intervention": None,
                "target_interventions": ["leadership", "spiritual_formation"],
            },
        )
        clone(
            cursor,
            "project",
            CCSEL,
            {
                "id": "gpjp2",
                "name": "Golden Gone",
                "code": "SP-GPJ-GONE",
                "deleted_at": "2026-01-01T00:00:00+00:00",
            },
        )
        cursor.execute(
            """INSERT INTO project_staff_assignment (id, created_at, updated_at, fy, responsibility,
               is_active, project_id, staff_id, assigned_by_role)
               VALUES ('gpjs1', now(), now(), '2027', 'delivery', true, 'gpjp1', %s, 'Admin')""",
            [cceo_profile],
        )
        for n, (project, partner) in enumerate(
            ((CCSEL, partners[0]), (CCSEL, partners[1]), (DIP, partners[1]))
        ):
            cursor.execute(
                """INSERT INTO project_partner_assignment (id, created_at, updated_at, partner_id, project_id)
                   VALUES (%s, now(), now(), %s, %s)""",
                [f"gpjr{n}", partner, project],
            )

        def activity(suffix, project, school, **fields):
            clone(
                cursor,
                "activity",
                base_activity,
                {
                    "id": f"gpja{suffix}",
                    "created_at": f"2026-09-{10 + int(suffix)}T08:00:00+00:00",
                    "project_id": project,
                    "school_id": school,
                    "fy": "2027",
                    "fiscal_year": "2027",
                    "paired_school_visit_id": None,
                    "salesforce_activity_id": None,
                    "daily_visit_batch_id": None,
                    "status": "scheduled",
                    "delivery_type": "staff",
                    "assigned_partner_id": None,
                    "evidence_status": "none",
                    "ia_verification_status": "pending",
                    "payment_status": "none",
                    "teachers_attended": 0,
                    "leaders_attended": 0,
                    "focus_intervention": None,
                    "scheduled_date": "2026-10-20T10:00:00+03:00",
                    "planned_date": "2026-10-20",
                    **fields,
                },
            )

        def line(suffix, activity_id, amount):
            clone(
                cursor,
                "activity_schedule_cost_line",
                base_line,
                {"id": f"gpjl{suffix}", "activity_id": activity_id, "amount": amount},
            )

        activity(
            "1",
            CCSEL,
            schools[0],
            activity_type="in_school_training",
            status="closed",
            teachers_attended=7,
            leaders_attended=2,
            focus_intervention="leadership",
        )
        line("1", "gpja1", 50000)
        activity(
            "2",
            CCSEL,
            schools[1],
            status="completed",
            delivery_type="partner",
            assigned_partner_id=partners[0],
            evidence_status="accepted",
            focus_intervention="leadership",
        )
        activity(
            "3",
            CCSEL,
            schools[2],
            status="in_progress",
            scheduled_date="2026-12-01T10:00:00+03:00",
            planned_date="2026-12-01",
            focus_intervention="christlike_behaviour",
        )
        line("3", "gpja3", 120000)
        activity("4", CCSEL, schools[3], status="awaiting_ia_verification")
        activity(
            "5",
            CCSEL,
            schools[4],
            status="returned_by_ia",
            ia_verification_status="flagged",
        )
        activity(
            "6",
            CCSEL,
            schools[0],
            status="assigned_to_partner",
            delivery_type="partner",
            assigned_partner_id=partners[0],
        )
        activity("7", CCSEL, schools[1], fy="2026", fiscal_year="2026")
        activity(
            "8",
            DIP,
            dip_school,
            status="closed",
            payment_status="paid",
            focus_intervention="teaching_environment",
        )
        line("8", "gpja8", 2500000)


def dump_rows():
    rows = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM \"{table}\" t WHERE id LIKE 'gpj%%' ORDER BY id"  # noqa: S608  # nosec B608
            )
            rows[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return rows


def questions():
    asked = [
        {},
        {"fy": "2026"},
        {"fy": "1999"},
        {"type": "intervention_specific"},
        {"type": "pilot"},
        {"type": "bogus"},
        {"status": "planning"},
        {"status": "on_track"},
        {"status": "at_risk"},
        {"status": "behind"},
        {"status": "bogus"},
        {"tab": DIP},
        {"tab": "gpjp1"},
        {"tab": "bogus"},
        {"project": DIP},
        {"project": DIP, "tab": "cmw9p8dff00sov1ekheht"},
        {"fy": "2026", "type": "pilot", "status": "planning"},
    ]
    readers = (
        "admin@edify.org",
        "cd@edify.org",
        "ia@edify.org",
        "pl1@edify.org",
        "coordinator@edify.org",
        "cceo@edify.org",
        "cceo1@edify.org",
    )
    out = {email: asked for email in readers}
    out["accountant@edify.org"] = [{}]
    return out


clear()
answers = []
try:
    file_rows()
    rows = dump_rows()
    for email, asked in questions().items():
        user = User.objects.get(email=email)
        for query in asked:
            status, body = read_page(user, "/projects", query)
            answers.append(
                {
                    "email": email,
                    "path": "/projects",
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
print(f"{len(answers)} pages asked")
