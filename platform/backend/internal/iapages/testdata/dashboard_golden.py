"""Write dashboard_golden.json: Impact Assessment's dashboard
(/ia/dashboard/) on its Outcomes (the default), Today, Collection, Impact
reports and Operations views as
the existing feed reads it, over verification work and project enrolments the
development seed does not hold.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/dashboard_golden.json \\
    python manage.py shell < platform/backend/internal/iapages/testdata/dashboard_golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gid", copies of one stored visit: staff work waiting for
verification with a Salesforce ID (a core visit, an overdue one, a fresh one,
a cluster-wide session, one never stamped as submitted), owned by the
Project Coordinator, and one owned by the Impact Assessment officer (which
only the Country Director, standing in, sees); the work the queue leaves out
(partner-delivered, no Salesforce ID); delivered work with no Salesforce ID;
work returned for correction a day and ten days ago. Beside them: a
potential duplicate, an uploaded evidence file, a pending SSA record, an
unmatched SSA row and a failed upload batch; and project enrolments
measured from a confirmed SSA to a later one (improved, declined, kept
strong), under review, and with follow-ups overdue, due today and to come. Every submission time sits half
an hour from an hour, so the answers hold for half an hour after the file is
written. It asks each view of the readers the page opens for and those it
refuses, writes the rows and the answers to GOLDEN_OUT and deletes the rows.
internal/integration/ia_dashboard_test.go files the same rows and compares.
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
    raise SystemExit("dashboard_golden.py runs only against a _test database")

User = get_user_model()
PATH = "/ia/dashboard/"
NOW = dj_timezone.now()
#: Parents first: the order the rows are filed in, and cleared in reverse.
TABLES = (
    "activity",
    "ssa_record",
    "project_school_assignment",
    "upload_batch",
    "unmatched_ssa_record",
    "ia_duplicate_activity",
    "evidence_record",
)


def clear():
    with connection.cursor() as cursor:
        for table in reversed(TABLES):
            cursor.execute(f"DELETE FROM {table} WHERE id LIKE 'gid%%'")


def clone(cursor, table, base_id, overrides):
    cursor.execute(
        f'INSERT INTO "{table}" SELECT (json_populate_record(NULL::"{table}", '
        f'(row_to_json(t)::jsonb || %s::jsonb)::json)).* FROM "{table}" t WHERE id = %s',
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
        ia_user = one("SELECT id FROM \"user\" WHERE email = 'ia@edify.org'")
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
                "activity",
                base,
                {
                    "id": f"gid{n:02d}",
                    "status": "awaiting_ia_verification",
                    "delivery_type": "staff",
                    "responsible_staff_id": owner,
                    "salesforce_activity_id": f"SF-GID-{n:02d}",
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
            return f"gid{n:02d}"

        first = work(coordinator, 3, activity_type="core_visit", school_id=core)
        work(coordinator, 50, school_id=schools[1])
        work(coordinator, 1, school_id=schools[2])
        work(
            coordinator,
            5,
            activity_type="cluster_meeting",
            school_id=None,
            cluster_id=cluster,
        )
        # Never stamped as submitted: it sorts last, aged by its update.
        work(coordinator, 70, submitted_to_ia_at=None)
        work(officer, 8, school_id=schools[1])
        # Left out of the queue: partner-delivered, and no Salesforce ID.
        work(coordinator, 4, delivery_type="partner")
        work(coordinator, 6, salesforce_activity_id="")
        # Delivered with no Salesforce ID.
        work(coordinator, 90, status="completed", salesforce_activity_id=None)
        # Returned for correction, a day and ten days ago.
        work(coordinator, 24, status="returned_by_ia")
        work(coordinator, 240, status="returned_by_ia", school_id=schools[1])

        stamp = (NOW - timedelta(hours=2, minutes=30)).isoformat()
        ssa = one(
            "SELECT id FROM ssa_record WHERE deleted_at IS NULL AND school_id = %s ORDER BY id LIMIT 1",
            [schools[2]],
        ) or one(
            "SELECT id FROM ssa_record WHERE deleted_at IS NULL ORDER BY id LIMIT 1"
        )
        clone(
            cursor,
            "ssa_record",
            ssa,
            {
                "id": "gidS1",
                "verification_status": "pending",
                "fy": "2031",
                "created_at": stamp,
                "updated_at": stamp,
            },
        )
        cursor.execute(
            "INSERT INTO upload_batch (id, created_at, updated_at, source, file_name, uploaded_by, row_count, "
            "accepted_count, flagged_count, created_rows, duplicate_rows, failed_rows, skipped_rows, status, "
            "total_rows, updated_rows, upload_type) VALUES ('gidB1', %s, %s, 'manual', 'ssa.xlsx', %s, 3, 0, 0, 0, 0, 3, 0, "
            "'failed', 3, 0, 'ssa')",
            [stamp, stamp, ia_user],
        )
        cursor.execute(
            "INSERT INTO unmatched_ssa_record (id, created_at, updated_at, school_id, school_name_raw, status, "
            "suggested_school_id) VALUES ('gidU1', %s, %s, 'NOPE-1', 'Nowhere Primary', 'pending', %s)",
            [stamp, stamp, schools[0]],
        )
        cursor.execute(
            "INSERT INTO ia_duplicate_activity (id, created_at, updated_at, status, reason, activity_id, duplicate_of_id) "
            "VALUES ('gidD1', %s, %s, 'potential', 'Same school and day', 'gid02', 'gid03')",
            [stamp, stamp],
        )
        cursor.execute(
            "INSERT INTO evidence_record (id, created_at, updated_at, kind, uri, uploaded_by, status, storage_provider, "
            "scan_status, quarantined, preview_status, view_count, activity_id) VALUES "
            "('gidE1', %s, %s, 'photo', 'local://gid/e1.jpg', %s, 'uploaded', 'local', 'clean', false, 'none', 0, %s)",
            [stamp, stamp, ia_user, first],
        )
        enrolments(cursor, one, stamp)


def enrolments(cursor, one, stamp):
    """Project enrolments the seed lacks, at operating schools no project
    holds, each measured from the school's confirmed FY2026 SSA: improved,
    declined and kept strong to a later confirmed SSA, a follow-up under
    review, and follow-ups overdue, due today and to come."""
    project = one(
        "SELECT id FROM project WHERE deleted_at IS NULL ORDER BY name LIMIT 1"
    )
    base = one("SELECT id FROM project_school_assignment ORDER BY id LIMIT 1")
    cursor.execute(
        "SELECT s.id, r.id FROM school s JOIN ssa_record r ON r.school_id = s.id AND r.fy = '2026' "
        "AND r.verification_status = 'confirmed' AND r.deleted_at IS NULL "
        "WHERE s.deleted_at IS NULL AND s.operational_status = 'active' AND s.region_id IS NOT NULL "
        "AND s.id NOT IN (SELECT school_id FROM project_school_assignment) ORDER BY s.id LIMIT 7"
    )
    picked = cursor.fetchall()
    today = dj_timezone.localdate()
    later = (NOW - timedelta(hours=2)).isoformat()
    cases = [
        ("improved", 4.5, 7.25, None),
        ("declined", 8.0, 6.5, None),
        ("maintained_strong", 9.0, 9.0, None),
        ("not_yet_measurable", 5.0, 6.0, None),
        ("not_yet_measurable", 5.0, None, (today - timedelta(days=3)).isoformat()),
        ("not_yet_measurable", 5.0, None, today.isoformat()),
        ("not_yet_measurable", 5.0, None, (today + timedelta(days=9)).isoformat()),
    ]
    for n, ((school, record), (classification, before, after, due)) in enumerate(
        zip(picked, cases), start=1
    ):
        follow_up = None
        if after is not None:
            follow_up = f"gidS{n + 1}"
            clone(
                cursor,
                "ssa_record",
                record,
                {
                    "id": follow_up,
                    "fy": "2032",
                    "date_of_ssa": later,
                    "created_at": stamp,
                    "updated_at": stamp,
                },
            )
        clone(
            cursor,
            "project_school_assignment",
            base,
            {
                "id": f"gidP{n}",
                "project_id": project,
                "school_id": school,
                "matched_intervention": "leadership",
                "baseline_ssa_id": record,
                "baseline_score": before,
                "follow_up_ssa_id": follow_up,
                "follow_up_score": after,
                "impact_classification": classification,
                "follow_up_due_on": due,
                "created_at": stamp,
                "updated_at": stamp,
            },
        )


def dump_rows():
    out = {}
    with connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM {table} t WHERE id LIKE 'gid%%' ORDER BY ctid"
            )
            out[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return out


OUTCOMES = [
    {},
    {"view": "reports"},
    {"view": "outcomes"},
    {"fy": "2026"},
    {"fy": "2028"},
    {"fy": "2025"},
    {"view": "framework"},
]

VIEWS = [
    {"view": "today"},
    {"view": "operations"},
    {"view": " Operations "},
    {"view": "today", "project": "anything"},
]

clear()
answers = []
try:
    file_rows()
    rows = dump_rows()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM project WHERE deleted_at IS NULL ORDER BY name LIMIT 1"
        )
        first_project = cursor.fetchone()[0]
    OUTCOMES.append({"project": first_project})
    OUTCOMES.append({"view": "reports", "project": first_project})
    # A filtered worklist that runs past a page hands on (its pager keeps the
    # request's query order), so the filters asked here fit on one page.
    COLLECTION = [
        {"view": "collection"},
        {"view": "collection", "collection_page": "2"},
        {"view": "collection", "collection_page": "99"},
        {"view": "collection", "state": "pending_verification"},
        {"view": "collection", "school_type": "core"},
        {"view": "collection", "project": first_project},
    ]
    OUTCOMES.append({"project": first_project, "fy": "2026", "view": "outcomes"})
    readers = {
        "ia@edify.org": VIEWS + OUTCOMES + COLLECTION,
        "cd@edify.org": VIEWS[:2] + OUTCOMES[:2] + COLLECTION[:1],
        "admin@edify.org": VIEWS[:2] + OUTCOMES[:2] + COLLECTION[:1],
        "rvp@edify.org": VIEWS[:1],
        "pl1@edify.org": VIEWS[:1],
        "cceo@edify.org": VIEWS[:1],
        "accountant@edify.org": VIEWS[:1],
    }
    for email, qs in readers.items():
        user = User.objects.filter(email=email).first()
        if user is None:
            continue
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
