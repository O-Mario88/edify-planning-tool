"""Write golden.json: Programme Rollout (/programme-rollout) on its Trainings
view as the existing feed reads it, for the first Programme Lead over
trainings the development seed does not hold, and the readers it refuses.

    DATABASE_URL=postgresql://localhost:5432/edify_gorn_test \\
    GOLDEN_OUT=/path/to/golden.json \\
    python manage.py shell < platform/backend/internal/programmerollout/testdata/golden.py

Only against a database whose name ends in "_test". It files, every id
starting "gpr", copies of one stored visit as the team's trainings: an
in-school course delivered at an officer's school, a partner's cluster
training verified with one school's attendance confirmed, one held and in
review with no intervention, one scheduled in the next days, a partner's
dated cluster training, one planned months ahead, one cancelled, and one
delivered last year. It asks the page as the Lead (each year and the view
named) and as the officer and the Accountant it refuses, writes the rows and
the answers, and deletes the rows.
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
    raise SystemExit("golden.py runs only against a _test database")

User = get_user_model()
PATH = "/programme-rollout"
NOW = dj_timezone.now()
TODAY = dj_timezone.localdate()
TABLES = (
    ("activity", "id"),
    ("cluster_activity_attendance", "activity_id"),
    ("ssa_record", "id"),
    ("ssa_score", "ssa_record_id"),
    ("partner_assignment", "id"),
)


def clear():
    with connection.cursor() as cursor:
        for table, column in reversed(TABLES):
            cursor.execute(f"DELETE FROM {table} WHERE {column} LIKE 'gpr%%'")


def one(cursor, sql, args=()):
    cursor.execute(sql, args)
    row = cursor.fetchone()
    return row[0] if row else None


def file_rows():
    with connection.cursor() as cursor:
        officer = one(
            cursor,
            'SELECT sp.id FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id '
            "WHERE u.email = 'cceo@edify.org'",
        )
        cursor.execute(
            "SELECT s.id, s.cluster_id FROM staff_school_assignment a JOIN school s ON s.id = a.school_id "
            "WHERE a.staff_id = %s AND s.deleted_at IS NULL AND s.cluster_id IS NOT NULL ORDER BY s.id LIMIT 4",
            [officer],
        )
        schools = cursor.fetchall()
        course = one(
            cursor,
            "SELECT id FROM activity_catalogue_item WHERE is_training_course AND status = 'active' ORDER BY id LIMIT 1",
        )
        partner = one(
            cursor,
            "SELECT id FROM partner WHERE deleted_at IS NULL ORDER BY id LIMIT 1",
        )
        base = one(
            cursor,
            "SELECT id FROM activity WHERE activity_type = 'school_visit' AND deleted_at IS NULL ORDER BY id LIMIT 1",
        )
        stamp = NOW.isoformat()
        n = 0

        def work(**fields):
            nonlocal n
            n += 1
            overrides = {
                "id": f"gpr{n:02d}",
                "fy": "2027",
                "quarter": "Q1",
                "planned_month": TODAY.month,
                "delivery_type": "staff",
                "responsible_staff_id": officer,
                "monitored_by_staff_id": None,
                "assigned_partner_id": None,
                "school_id": schools[0][0],
                "cluster_id": None,
                "focus_intervention": "christlike_behaviour",
                "catalogue_item_id": None,
                "training_course_id": None,
                "activity_name_snapshot": "",
                "teachers_attended": 0,
                "leaders_attended": 0,
                "attended_school_ids": [],
                "paired_school_visit_id": None,
                "daily_visit_batch_id": None,
                "created_at": stamp,
                "updated_at": stamp,
                **fields,
            }
            cursor.execute(
                'INSERT INTO "activity" SELECT (json_populate_record(NULL::"activity", '
                '(row_to_json(t)::jsonb || %s::jsonb)::json)).* FROM "activity" t WHERE id = %s',
                [json.dumps(overrides, default=str), base],
            )
            return overrides["id"]

        def on(days):
            return (TODAY + timedelta(days=days)).isoformat()

        work(
            activity_type="in_school_training",
            status="completed",
            planned_date=on(-12),
            training_course_id=course,
            teachers_attended=6,
            leaders_attended=2,
        )
        cluster = work(
            activity_type="cluster_training",
            status="ia_verified",
            planned_date=on(-20),
            delivery_type="partner",
            assigned_partner_id=partner,
            responsible_staff_id=None,
            monitored_by_staff_id=officer,
            school_id=None,
            cluster_id=schools[1][1],
            focus_intervention="leadership",
            teachers_attended=14,
            leaders_attended=4,
            attended_school_ids=[schools[1][0]],
        )
        work(
            activity_type="training",
            status="submitted_to_pl",
            planned_date=on(-3),
            focus_intervention="",
            activity_name_snapshot="Classroom discipline refresher",
            school_id=schools[2][0],
        )
        work(
            activity_type="in_school_training",
            status="scheduled",
            planned_date=on(5),
            training_course_id=course,
            school_id=schools[3][0],
        )
        work(
            activity_type="cluster_training",
            status="partner_scheduled",
            planned_date=on(10),
            delivery_type="partner",
            assigned_partner_id=partner,
            responsible_staff_id=None,
            monitored_by_staff_id=officer,
            school_id=None,
            cluster_id=schools[1][1],
            focus_intervention="exposure_to_word_of_god",
        )
        work(activity_type="training", status="planned", planned_date=on(70))
        work(activity_type="training", status="cancelled", planned_date=on(2))
        work(
            activity_type="in_school_training",
            status="completed",
            planned_date=on(-300),
            fy="2026",
            teachers_attended=3,
            school_id=schools[2][0],
        )
        cursor.execute(
            "INSERT INTO cluster_activity_attendance (created_at, updated_at, activity_id, school_id, "
            "invited, attended, is_guest, recorded_by) VALUES (%s, %s, %s, %s, true, true, false, '')",
            [stamp, stamp, cluster, schools[0][0]],
        )
        file_ssa(cursor, work, on, officer, partner, stamp)


def file_ssa(cursor, work, on, officer, partner, stamp):
    """The Self-Assessments view's facts over schools with no confirmed SSA
    this year, each cluster's schools apart: records pending, flagged, deleted
    and newly confirmed with scores; collections at a school scheduled, held
    and cancelled; a cluster collection with nobody recorded and one with an
    invitation and a recorded school; a partner hand-over at a school, one at
    a cluster by its catalogue item, and one already scheduled."""
    cursor.execute(
        "SELECT s.id, s.cluster_id FROM staff_school_assignment a JOIN school s ON s.id = a.school_id "
        "WHERE a.staff_id = %s AND s.deleted_at IS NULL AND s.cluster_id IS NOT NULL "
        "AND s.operational_status IN ('active', 'reopened') AND NOT EXISTS (SELECT 1 FROM ssa_record r "
        "WHERE r.school_id = s.id AND r.fy = '2027' AND r.deleted_at IS NULL) ORDER BY s.cluster_id, s.id",
        [officer],
    )
    by_cluster = {}
    for school_id, cluster_id in cursor.fetchall():
        by_cluster.setdefault(cluster_id, []).append(school_id)
    clusters = sorted(by_cluster)
    # Single-school facts come from clusters the cluster-wide facts leave alone.
    single = [sid for c in clusters[3:] for sid in by_cluster[c]]
    invited = by_cluster[clusters[1]]
    confirmed_school = one_confirmed(cursor, officer)
    base_record = one(
        cursor,
        "SELECT id FROM ssa_record WHERE verification_status = 'confirmed' AND deleted_at IS NULL ORDER BY id LIMIT 1",
    )
    n = 0

    def record(school_id, **fields):
        nonlocal n
        n += 1
        overrides = {
            "id": f"gprs{n:02d}",
            "school_id": school_id,
            "fy": "2027",
            "quarter": "Q1",
            "date_of_ssa": on(-15) + "T09:00:00+00:00",
            "verification_status": "pending",
            "source_activity_id": None,
            "salesforce_id": None,
            "deleted_at": None,
            "created_at": stamp,
            "updated_at": stamp,
            **fields,
        }
        cursor.execute(
            'INSERT INTO "ssa_record" SELECT (json_populate_record(NULL::"ssa_record", '
            '(row_to_json(t)::jsonb || %s::jsonb)::json)).* FROM "ssa_record" t WHERE id = %s',
            [json.dumps(overrides, default=str), base_record],
        )
        return overrides["id"]

    record(single[0])
    record(single[1], verification_status="flagged")
    record(single[2], deleted_at=stamp)
    scored = record(single[3], verification_status="confirmed", average_score=7.25)
    for index, (intervention, score) in enumerate(
        (
            ("christlike_behaviour", 8.25),
            ("exposure_to_word_of_god", 6.75),
            ("financial_health", 4.0),
            ("leadership", 9.5),
        )
    ):
        cursor.execute(
            "INSERT INTO ssa_score (id, created_at, updated_at, ssa_record_id, intervention, score) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            [f"{scored}x{index}", stamp, stamp, scored, intervention, score],
        )

    collection = {"fy": "2027", "focus_intervention": "", "school_id": None}
    work(
        activity_type="school_visit_ssa_collection",
        status="scheduled",
        planned_date=on(6),
        **{**collection, "school_id": single[4]},
    )
    work(
        activity_type="baseline_ssa_visit",
        status="completed",
        planned_date=on(-9),
        **{**collection, "school_id": single[5]},
    )
    work(
        activity_type="ssa_activity",
        status="cancelled",
        planned_date=on(3),
        **{**collection, "school_id": single[6]},
    )
    work(
        activity_type="school_visit_ssa_collection",
        status="scheduled",
        planned_date=on(4),
        **{**collection, "school_id": confirmed_school},
    )
    work(
        activity_type="cluster_training_ssa_collection",
        status="partner_scheduled",
        planned_date=on(8),
        delivery_type="partner",
        assigned_partner_id=partner,
        responsible_staff_id=None,
        monitored_by_staff_id=None,
        **{**collection, "cluster_id": clusters[0]},
    )
    reviewed = work(
        activity_type="cluster_meeting_ssa_review",
        status="evidence_uploaded",
        planned_date=on(-4),
        responsible_staff_id=None,
        monitored_by_staff_id=None,
        attended_school_ids=[invited[1]],
        **{**collection, "cluster_id": clusters[1]},
    )
    cursor.execute(
        "INSERT INTO cluster_activity_attendance (created_at, updated_at, activity_id, school_id, "
        "invited, attended, is_guest, recorded_by) VALUES (%s, %s, %s, %s, true, false, false, '')",
        [stamp, stamp, reviewed, invited[0]],
    )

    base_assignment = one(
        cursor, "SELECT id FROM partner_assignment ORDER BY id LIMIT 1"
    )
    workflow_item = one(
        cursor,
        "SELECT id FROM activity_catalogue_item WHERE workflow_kind = 'school_visit_ssa_collection' ORDER BY id LIMIT 1",
    )
    m = 0

    def assignment(**fields):
        nonlocal m
        m += 1
        overrides = {
            "id": f"gpra{m:02d}",
            "status": "assigned",
            "partner_id": partner,
            "school_id": None,
            "cluster_id": None,
            "catalogue_item_id": None,
            "expected_activity_type": "",
            "scheduled_activity_id": None,
            "source_activity_id": None,
            "source_ssa_id": None,
            "replaces_assignment_id": None,
            "support_type": None,
            "visit_number": None,
            "training_number": None,
            "purpose_of_visit": "",
            "created_at": stamp,
            "updated_at": stamp,
            **fields,
        }
        cursor.execute(
            'INSERT INTO "partner_assignment" SELECT (json_populate_record(NULL::"partner_assignment", '
            '(row_to_json(t)::jsonb || %s::jsonb)::json)).* FROM "partner_assignment" t WHERE id = %s',
            [json.dumps(overrides, default=str), base_assignment],
        )

    assignment(school_id=single[7], expected_activity_type="partner_ssa_collection")
    assignment(
        cluster_id=clusters[2],
        status="pending_scheduling",
        catalogue_item_id=workflow_item,
    )
    assignment(
        school_id=single[8],
        status="partner_scheduled",
        expected_activity_type="partner_ssa_collection",
    )
    assignment(
        school_id=single[9],
        expected_activity_type="partner_ssa_collection",
        created_at="2025-06-01T08:00:00+00:00",
    )


def one_confirmed(cursor, officer):
    return one(
        cursor,
        "SELECT r.school_id FROM ssa_record r JOIN staff_school_assignment a ON a.school_id = r.school_id "
        "WHERE a.staff_id = %s AND r.fy = '2027' AND r.verification_status = 'confirmed' AND r.deleted_at IS NULL "
        "ORDER BY r.school_id LIMIT 1",
        [officer],
    )


def dump_rows():
    out = {}
    with connection.cursor() as cursor:
        for table, column in TABLES:
            cursor.execute(
                f"SELECT row_to_json(t)::text FROM {table} t WHERE {column} LIKE 'gpr%%' ORDER BY ctid"
            )
            out[table] = [json.loads(r[0]) for r in cursor.fetchall()]
    return out


clear()
answers = []
try:
    file_rows()
    rows = dump_rows()
    for email, query in (
        ("pl1@edify.org", {}),
        ("pl1@edify.org", {"view": "trainings"}),
        ("pl1@edify.org", {"view": " Trainings "}),
        ("pl1@edify.org", {"fy": "2026"}),
        ("pl1@edify.org", {"fy": "bogus"}),
        ("pl1@edify.org", {"view": "ssa"}),
        ("pl1@edify.org", {"view": "SSA", "fy": "2026"}),
        ("pl1@edify.org", {"view": "ssa", "fy": "2025"}),
        ("cceo@edify.org", {}),
        ("accountant@edify.org", {}),
    ):
        with transaction.atomic():
            status, body = read_page(User.objects.get(email=email), PATH, query)
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
        {"written": NOW.isoformat(), "rows": rows, "answers": answers},
        handle,
        ensure_ascii=False,
        indent=1,
        default=str,
    )
print(f"{len(answers)} pages asked")
